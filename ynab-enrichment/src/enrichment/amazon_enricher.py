"""Amazon → YNAB transaction enrichment."""

from __future__ import annotations

import datetime
import re
from typing import Any

from src.config import settings
from src.db.database import (
    is_already_enriched,
    log_run_start,
    log_run_complete,
    log_undo_entry,
    mark_enriched,
)
from src.db.models import EnrichmentSummary
from src.enrichment.categorizer import Categorizer
from src.services.amazon import AmazonParser
from src.services.ynab import YNABClient
from src.utils.logging import logger
from src.utils.matching import (
    dates_within_tolerance,
    dollars_to_milliunits,
    find_combination_match,
)

_AMAZON_PATTERNS = re.compile(
    r"amazon|amzn|amzn\s*mktp|amazon\.com|prime\s*video", re.IGNORECASE
)

YNAB_MEMO_LIMIT = 200


def _is_amazon_transaction(payee_name: str | None) -> bool:
    if not payee_name:
        return False
    return bool(_AMAZON_PATTERNS.search(payee_name))


def _build_memo(items: list[dict[str, Any]]) -> str:
    """Build a YNAB memo string from matched Amazon items, respecting the character limit."""
    parts: list[str] = []
    for item in items:
        title = item.get("title", "Unknown")
        qty = item.get("quantity", 1)
        if qty > 1:
            parts.append(f"{title} ({qty})")
        else:
            parts.append(title)

    memo = ", ".join(parts)
    if len(memo) > YNAB_MEMO_LIMIT:
        memo = memo[: YNAB_MEMO_LIMIT - 3] + "..."
    return memo


def _dominant_category(items: list[dict[str, Any]]) -> str:
    """Find the most common Amazon category among matched items."""
    categories: dict[str, float] = {}
    for item in items:
        cat = item.get("category", "")
        if cat:
            categories[cat] = categories.get(cat, 0) + abs(item.get("price", 0))
    if not categories:
        return ""
    return max(categories, key=lambda c: categories[c])


async def enrich_amazon_transactions(
    ynab_client: YNABClient,
    amazon_parser: AmazonParser,
    categorizer: Categorizer,
    days_back: int = 90,
    dry_run: bool = True,
) -> EnrichmentSummary:
    """Match Amazon orders to YNAB transactions and enrich with item details.

    Args:
        days_back: How many days back to look for transactions.
        dry_run: If True, don't actually update YNAB.
    """
    run_id = await log_run_start("amazon")
    summary = EnrichmentSummary(module="amazon", dry_run=dry_run)

    try:
        # Parse Amazon orders
        amazon_orders = amazon_parser.parse_orders()
        if not amazon_orders:
            logger.warning("No Amazon orders found in CSV")
            await log_run_complete(run_id, summary=summary.model_dump())
            return summary

        # Fetch YNAB transactions and filter for Amazon
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days_back)

        ynab_txns = await ynab_client.get_transactions(
            since_date=start_date.isoformat()
        )
        amazon_ynab_txns = [
            tx for tx in ynab_txns if _is_amazon_transaction(tx.get("payee_name"))
        ]
        logger.info(
            "Found %d Amazon transactions in YNAB (out of %d total)",
            len(amazon_ynab_txns),
            len(ynab_txns),
        )

        if not amazon_ynab_txns:
            await log_run_complete(run_id, summary=summary.model_dump())
            return summary

        # Filter Amazon orders to the relevant date range
        relevant_orders = [
            o
            for o in amazon_orders
            if start_date.isoformat() <= o["date"] <= end_date.isoformat()
        ]
        logger.info("Found %d Amazon orders in date range", len(relevant_orders))

        # Track which Amazon orders have been used
        used_order_indices: set[int] = set()

        for ynab_tx in amazon_ynab_txns:
            summary.transactions_processed += 1
            tx_id = ynab_tx["id"]

            # Skip already-enriched transactions
            if await is_already_enriched(tx_id, "amazon"):
                summary.transactions_skipped += 1
                continue

            ynab_amount = abs(ynab_tx.get("amount", 0))
            ynab_date = ynab_tx.get("date", "")

            # Try exact single-item match first
            matched_items: list[dict[str, Any]] = []
            for idx, order in enumerate(relevant_orders):
                if idx in used_order_indices:
                    continue
                order_amount = abs(order["amount"])
                if (
                    abs(ynab_amount - order_amount) <= 500  # $0.50 tolerance for tax
                    and dates_within_tolerance(
                        ynab_date,
                        order["date"],
                        settings.amazon_date_tolerance_days,
                    )
                ):
                    matched_items = [order]
                    used_order_indices.add(idx)
                    break

            # Try combination match if no single match found
            if not matched_items:
                available = [
                    o
                    for i, o in enumerate(relevant_orders)
                    if i not in used_order_indices
                    and dates_within_tolerance(
                        ynab_date,
                        o["date"],
                        settings.amazon_date_tolerance_days,
                    )
                ]
                combo = find_combination_match(
                    ynab_amount, available, amount_key="amount", tolerance=500
                )
                if combo:
                    matched_items = combo
                    # Mark these orders as used
                    for item in combo:
                        for idx, order in enumerate(relevant_orders):
                            if idx not in used_order_indices and order is item:
                                used_order_indices.add(idx)
                                break

            if not matched_items:
                # Ambiguous or no match — skip
                summary.needs_manual_review.append(
                    {
                        "ynab_id": tx_id,
                        "payee": ynab_tx.get("payee_name", ""),
                        "amount": ynab_tx.get("amount", 0),
                        "date": ynab_date,
                        "reason": "No matching Amazon order found",
                    }
                )
                continue

            # Build update
            memo = _build_memo(matched_items)
            updates: dict[str, Any] = {"memo": memo}
            detail: dict[str, Any] = {
                "ynab_id": tx_id,
                "matched_items": [item.get("title", "") for item in matched_items],
                "memo": memo,
            }

            # Try auto-categorization based on Amazon category
            dominant_cat = _dominant_category(matched_items)
            if dominant_cat:
                cat_id, confidence = categorizer.categorize_amazon(dominant_cat)
                if cat_id and categorizer.should_auto_categorize(confidence):
                    updates["category_id"] = cat_id
                    detail["auto_categorized"] = True
                    detail["amazon_category"] = dominant_cat
                    summary.auto_categorized += 1
                elif len(set(item.get("category", "") for item in matched_items if item.get("category"))) > 1:
                    # Multiple categories — note in memo
                    categories = ", ".join(
                        set(item.get("category", "") for item in matched_items if item.get("category"))
                    )
                    note = f" [categories: {categories}]"
                    if len(memo + note) <= YNAB_MEMO_LIMIT:
                        updates["memo"] = memo + note

            if not dry_run:
                # Log undo entries
                await log_undo_entry(
                    tx_id, "memo", ynab_tx.get("memo"), updates.get("memo"), run_id
                )
                if "category_id" in updates:
                    await log_undo_entry(
                        tx_id,
                        "category_id",
                        ynab_tx.get("category_id"),
                        updates["category_id"],
                        run_id,
                    )

                await ynab_client.update_transaction(tx_id, updates)
                await mark_enriched(tx_id, "amazon")

            summary.transactions_enriched += 1
            summary.details.append(detail)

        result_summary = summary.model_dump()
        await log_run_complete(run_id, summary=result_summary)
        logger.info(
            "Amazon enrichment complete: %d processed, %d enriched, %d auto-categorized",
            summary.transactions_processed,
            summary.transactions_enriched,
            summary.auto_categorized,
        )
        return summary

    except Exception as e:
        await log_run_complete(run_id, status="error", error=str(e))
        raise
