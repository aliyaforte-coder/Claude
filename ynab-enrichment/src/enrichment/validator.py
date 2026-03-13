"""SimpleFin ↔ YNAB transaction validation."""

from __future__ import annotations

import datetime
from typing import Any

from src.db.database import log_run_start, log_run_complete
from src.db.models import ValidationReport
from src.services.simplefin import SimpleFinClient
from src.services.ynab import YNABClient
from src.utils.logging import logger
from src.utils.matching import dates_within_tolerance, amounts_match


# Map SimpleFin account IDs to YNAB account IDs.
# Users should configure this via a file or env, but for now we match by name heuristic.


async def validate_transactions(
    ynab_client: YNABClient,
    simplefin_client: SimpleFinClient,
    start_date: str,
    end_date: str,
    account_mapping: dict[str, str] | None = None,
    date_tolerance: int = 2,
) -> ValidationReport:
    """Cross-reference SimpleFin and YNAB transactions to find discrepancies.

    Args:
        start_date: ISO date string (YYYY-MM-DD).
        end_date: ISO date string (YYYY-MM-DD).
        account_mapping: Optional dict mapping SimpleFin account IDs to YNAB account IDs.
        date_tolerance: Days of tolerance for date matching.
    """
    run_id = await log_run_start("validate")

    try:
        # Fetch SimpleFin transactions
        start_ts = int(
            datetime.datetime.strptime(start_date, "%Y-%m-%d")
            .replace(tzinfo=datetime.timezone.utc)
            .timestamp()
        )
        end_ts = int(
            datetime.datetime.strptime(end_date, "%Y-%m-%d")
            .replace(tzinfo=datetime.timezone.utc)
            .timestamp()
        )

        sf_accounts = await simplefin_client.get_accounts(
            start_date=start_ts, end_date=end_ts
        )

        # Flatten SimpleFin transactions across all accounts
        sf_transactions: list[dict[str, Any]] = []
        for account in sf_accounts:
            acct_id = account.get("id", "")
            for tx in account.get("transactions", []):
                tx["_sf_account_id"] = acct_id
                tx["_sf_account_name"] = account.get("name", "")
                # Normalize amount to milliunits (SimpleFin uses decimal dollars)
                if "amount" in tx:
                    tx["_amount_milliunits"] = round(float(tx["amount"]) * 1000)
                # Normalize date
                if "posted" in tx:
                    tx["_date"] = datetime.date.fromtimestamp(tx["posted"]).isoformat()
                elif "transacted_at" in tx:
                    tx["_date"] = datetime.date.fromtimestamp(
                        tx["transacted_at"]
                    ).isoformat()
                sf_transactions.append(tx)

        # Fetch YNAB transactions
        ynab_transactions = await ynab_client.get_transactions(since_date=start_date)

        logger.info(
            "Validating %d SimpleFin transactions against %d YNAB transactions",
            len(sf_transactions),
            len(ynab_transactions),
        )

        # Build match indices
        report = ValidationReport()
        matched_ynab_ids: set[str] = set()

        for sf_tx in sf_transactions:
            sf_amount = sf_tx.get("_amount_milliunits", 0)
            sf_date = sf_tx.get("_date", "")

            best_match: dict | None = None
            best_match_type = ""

            for ynab_tx in ynab_transactions:
                ynab_id = ynab_tx["id"]
                if ynab_id in matched_ynab_ids:
                    continue

                # Check account mapping if provided
                if account_mapping:
                    sf_acct = sf_tx.get("_sf_account_id", "")
                    ynab_acct = ynab_tx.get("account_id", "")
                    if sf_acct in account_mapping:
                        if account_mapping[sf_acct] != ynab_acct:
                            continue

                ynab_amount = ynab_tx.get("amount", 0)
                ynab_date = ynab_tx.get("date", "")

                amt_ok = amounts_match(sf_amount, ynab_amount)
                date_ok = dates_within_tolerance(sf_date, ynab_date, date_tolerance)

                if amt_ok and date_ok:
                    best_match = ynab_tx
                    best_match_type = "exact"
                    break
                elif amt_ok and not best_match:
                    best_match = ynab_tx
                    best_match_type = "amount_mismatch_date"
                elif date_ok and not best_match:
                    best_match = ynab_tx
                    best_match_type = "date_mismatch_amount"

            if best_match and best_match_type == "exact":
                report.matched_count += 1
                matched_ynab_ids.add(best_match["id"])
            elif best_match:
                report.mismatches.append(
                    {
                        "simplefin": {
                            "description": sf_tx.get("description", ""),
                            "amount": sf_amount,
                            "date": sf_date,
                            "account": sf_tx.get("_sf_account_name", ""),
                        },
                        "ynab": {
                            "id": best_match["id"],
                            "payee": best_match.get("payee_name", ""),
                            "amount": best_match.get("amount", 0),
                            "date": best_match.get("date", ""),
                        },
                        "mismatch_type": best_match_type,
                    }
                )
                matched_ynab_ids.add(best_match["id"])
            else:
                report.unmatched_simplefin.append(
                    {
                        "description": sf_tx.get("description", ""),
                        "amount": sf_amount,
                        "date": sf_date,
                        "account": sf_tx.get("_sf_account_name", ""),
                    }
                )

        # Find YNAB transactions not matched to any SimpleFin transaction
        for ynab_tx in ynab_transactions:
            if ynab_tx["id"] not in matched_ynab_ids:
                # Skip transfers and other internal transactions
                if ynab_tx.get("transfer_account_id"):
                    continue
                report.unmatched_ynab.append(
                    {
                        "id": ynab_tx["id"],
                        "payee": ynab_tx.get("payee_name", ""),
                        "amount": ynab_tx.get("amount", 0),
                        "date": ynab_tx.get("date", ""),
                        "account": ynab_tx.get("account_name", ""),
                    }
                )

        summary = {
            "matched": report.matched_count,
            "unmatched_simplefin": len(report.unmatched_simplefin),
            "unmatched_ynab": len(report.unmatched_ynab),
            "mismatches": len(report.mismatches),
        }
        await log_run_complete(run_id, summary=summary)
        logger.info("Validation complete: %s", summary)
        return report

    except Exception as e:
        await log_run_complete(run_id, status="error", error=str(e))
        raise
