"""Privacy.com → YNAB transaction enrichment."""

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
from src.services.privacy import PrivacyClient
from src.services.ynab import YNABClient
from src.utils.logging import logger
from src.utils.matching import cents_to_milliunits, dates_within_tolerance

_PRIVACY_PATTERNS = re.compile(
    r"privacy\.?com|privacy\s|priv\*", re.IGNORECASE
)


def _is_privacy_transaction(payee_name: str | None) -> bool:
    if not payee_name:
        return False
    return bool(_PRIVACY_PATTERNS.search(payee_name))


def _get_merchant_name(privacy_tx: dict[str, Any]) -> str:
    """Extract the best merchant name from a Privacy.com transaction."""
    # Prefer card memo (user's custom label)
    card = privacy_tx.get("card", {})
    memo = card.get("memo", "").strip()
    if memo:
        return memo

    # Fall back to merchant descriptor
    merchant = privacy_tx.get("merchant", {})
    descriptor = merchant.get("descriptor", "").strip()
    if descriptor:
        return descriptor

    return ""


async def enrich_privacy_transactions(
    ynab_client: YNABClient,
    privacy_client: PrivacyClient,
    categorizer: Categorizer,
    days_back: int = 30,
    dry_run: bool = True,
) -> EnrichmentSummary:
    """Match Privacy.com transactions to YNAB and enrich with real merchant names.

    Args:
        days_back: How many days back to look for transactions.
        dry_run: If True, don't actually update YNAB.
    """
    run_id = await log_run_start("privacy")
    summary = EnrichmentSummary(module="privacy", dry_run=dry_run)

    try:
        # Calculate date range
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days_back)

        # Fetch YNAB transactions and filter for Privacy.com
        ynab_txns = await ynab_client.get_transactions(
            since_date=start_date.isoformat()
        )
        privacy_ynab_txns = [
            tx for tx in ynab_txns if _is_privacy_transaction(tx.get("payee_name"))
        ]
        logger.info(
            "Found %d Privacy.com transactions in YNAB (out of %d total)",
            len(privacy_ynab_txns),
            len(ynab_txns),
        )

        if not privacy_ynab_txns:
            await log_run_complete(run_id, summary=summary.model_dump())
            return summary

        # Fetch Privacy.com transactions
        privacy_txns = await privacy_client.get_transactions(
            begin=start_date.isoformat(), end=end_date.isoformat()
        )
        logger.info("Fetched %d transactions from Privacy.com", len(privacy_txns))

        # Normalize Privacy.com transactions for matching
        privacy_normalized: list[dict[str, Any]] = []
        for ptx in privacy_txns:
            amount_cents = ptx.get("amount", 0)
            # Privacy.com dates come as ISO strings
            tx_date = ptx.get("created", "")[:10]
            privacy_normalized.append(
                {
                    "original": ptx,
                    "amount_milliunits": cents_to_milliunits(amount_cents),
                    "date": tx_date,
                    "merchant_name": _get_merchant_name(ptx),
                }
            )

        # Match and enrich
        used_privacy_indices: set[int] = set()

        for ynab_tx in privacy_ynab_txns:
            summary.transactions_processed += 1
            tx_id = ynab_tx["id"]

            # Skip already-enriched transactions
            if await is_already_enriched(tx_id, "privacy"):
                summary.transactions_skipped += 1
                continue

            ynab_amount = abs(ynab_tx.get("amount", 0))
            ynab_date = ynab_tx.get("date", "")

            # Find matching Privacy.com transaction
            best_match: dict | None = None
            best_idx: int = -1

            for idx, pnorm in enumerate(privacy_normalized):
                if idx in used_privacy_indices:
                    continue

                p_amount = abs(pnorm["amount_milliunits"])
                p_date = pnorm["date"]

                if (
                    abs(ynab_amount - p_amount) <= 10  # $0.01 tolerance
                    and dates_within_tolerance(
                        ynab_date, p_date, settings.date_tolerance_days
                    )
                ):
                    best_match = pnorm
                    best_idx = idx
                    break

            if not best_match:
                summary.needs_manual_review.append(
                    {
                        "ynab_id": tx_id,
                        "payee": ynab_tx.get("payee_name", ""),
                        "amount": ynab_tx.get("amount", 0),
                        "date": ynab_date,
                        "reason": "No matching Privacy.com transaction found",
                    }
                )
                continue

            used_privacy_indices.add(best_idx)
            merchant_name = best_match["merchant_name"]
            if not merchant_name:
                summary.needs_manual_review.append(
                    {
                        "ynab_id": tx_id,
                        "amount": ynab_tx.get("amount", 0),
                        "date": ynab_date,
                        "reason": "Privacy.com transaction matched but no merchant name available",
                    }
                )
                continue

            # Build update
            updates: dict[str, Any] = {"payee_name": merchant_name}
            detail: dict[str, Any] = {
                "ynab_id": tx_id,
                "old_payee": ynab_tx.get("payee_name", ""),
                "new_payee": merchant_name,
            }

            # Try auto-categorization
            cat_id, confidence = categorizer.categorize_merchant(merchant_name)
            if cat_id and categorizer.should_auto_categorize(confidence):
                updates["category_id"] = cat_id
                detail["auto_categorized"] = True
                detail["category_confidence"] = confidence
                summary.auto_categorized += 1
            else:
                # Flag in memo for manual review
                existing_memo = ynab_tx.get("memo") or ""
                flag = "[needs-category]"
                if flag not in existing_memo:
                    updates["memo"] = f"{existing_memo} {flag}".strip()
                detail["auto_categorized"] = False

            if not dry_run:
                # Log undo entry before making changes
                await log_undo_entry(
                    tx_id, "payee_name", ynab_tx.get("payee_name"), merchant_name, run_id
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
                await mark_enriched(tx_id, "privacy")

            summary.transactions_enriched += 1
            summary.details.append(detail)

        result_summary = summary.model_dump()
        await log_run_complete(run_id, summary=result_summary)
        logger.info(
            "Privacy enrichment complete: %d processed, %d enriched, %d auto-categorized",
            summary.transactions_processed,
            summary.transactions_enriched,
            summary.auto_categorized,
        )
        return summary

    except Exception as e:
        await log_run_complete(run_id, status="error", error=str(e))
        raise
