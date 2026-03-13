"""Transaction matching algorithms for cross-referencing financial data sources."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


@dataclass
class MatchResult:
    source_tx: dict[str, Any]
    matched_tx: dict[str, Any] | None
    match_type: str  # "exact", "amount_only", "date_only", "none"
    confidence: float
    notes: str = ""


def dates_within_tolerance(
    date1: str | datetime.date,
    date2: str | datetime.date,
    tolerance_days: int = 2,
) -> bool:
    """Check if two dates are within the given tolerance window."""
    if isinstance(date1, str):
        date1 = datetime.date.fromisoformat(date1)
    if isinstance(date2, str):
        date2 = datetime.date.fromisoformat(date2)
    return abs((date1 - date2).days) <= tolerance_days


def amounts_match(amount1: int, amount2: int, tolerance: int = 0) -> bool:
    """Compare two amounts (both in the same unit) with optional tolerance."""
    return abs(amount1 - amount2) <= tolerance


def cents_to_milliunits(cents: int) -> int:
    """Convert cents (Privacy.com) to YNAB milliunits. $10.00 = 1000 cents = 10000 milliunits."""
    return cents * 10


def dollars_to_milliunits(dollars: float) -> int:
    """Convert dollar amounts to YNAB milliunits."""
    return round(dollars * 1000)


def find_best_match(
    target_amount: int,
    target_date: str | datetime.date,
    candidates: list[dict[str, Any]],
    amount_key: str = "amount",
    date_key: str = "date",
    tolerance_days: int = 2,
    amount_tolerance: int = 0,
) -> MatchResult | None:
    """Find the best matching transaction from a list of candidates.

    Returns the best match or None if no candidates match.
    """
    best: MatchResult | None = None

    for candidate in candidates:
        cand_amount = candidate[amount_key]
        cand_date = candidate[date_key]

        amt_ok = amounts_match(target_amount, cand_amount, amount_tolerance)
        date_ok = dates_within_tolerance(target_date, cand_date, tolerance_days)

        if amt_ok and date_ok:
            result = MatchResult(
                source_tx={},
                matched_tx=candidate,
                match_type="exact",
                confidence=1.0,
            )
            return result  # exact match, return immediately

        if amt_ok:
            result = MatchResult(
                source_tx={},
                matched_tx=candidate,
                match_type="amount_only",
                confidence=0.6,
                notes="Date outside tolerance window",
            )
            if best is None or result.confidence > best.confidence:
                best = result

        if date_ok:
            diff = abs(target_amount - cand_amount)
            # Only consider near-misses in amount
            if diff <= max(abs(target_amount) * 0.05, 500):  # 5% or $0.50
                result = MatchResult(
                    source_tx={},
                    matched_tx=candidate,
                    match_type="date_only",
                    confidence=0.4,
                    notes=f"Amount difference: {diff} milliunits",
                )
                if best is None or result.confidence > best.confidence:
                    best = result

    return best


def find_combination_match(
    target_amount: int,
    items: list[dict[str, Any]],
    amount_key: str = "amount",
    tolerance: int = 500,  # $0.50 tolerance for tax rounding
    max_items: int = 6,
) -> list[dict[str, Any]] | None:
    """Find a combination of items whose amounts sum to the target (within tolerance).

    Uses a bounded depth-first search. Returns the matching items or None.
    """
    items = items[:max_items]  # limit search space

    for size in range(1, len(items) + 1):
        result = _find_combo(items, target_amount, tolerance, amount_key, size, 0, [])
        if result is not None:
            return result
    return None


def _find_combo(
    items: list[dict],
    target: int,
    tolerance: int,
    amount_key: str,
    remaining: int,
    start: int,
    current: list[dict],
) -> list[dict] | None:
    if remaining == 0:
        total = sum(abs(item[amount_key]) for item in current)
        if abs(total - abs(target)) <= tolerance:
            return list(current)
        return None

    for i in range(start, len(items)):
        current.append(items[i])
        result = _find_combo(
            items, target, tolerance, amount_key, remaining - 1, i + 1, current
        )
        if result is not None:
            return result
        current.pop()
    return None
