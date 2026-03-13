"""Tests for transaction matching algorithms."""

import datetime

from src.utils.matching import (
    amounts_match,
    cents_to_milliunits,
    dates_within_tolerance,
    dollars_to_milliunits,
    find_best_match,
    find_combination_match,
)


class TestDatesWithinTolerance:
    def test_same_date(self):
        assert dates_within_tolerance("2024-01-15", "2024-01-15") is True

    def test_within_tolerance(self):
        assert dates_within_tolerance("2024-01-15", "2024-01-17", tolerance_days=2) is True

    def test_outside_tolerance(self):
        assert dates_within_tolerance("2024-01-15", "2024-01-18", tolerance_days=2) is False

    def test_with_date_objects(self):
        d1 = datetime.date(2024, 1, 15)
        d2 = datetime.date(2024, 1, 16)
        assert dates_within_tolerance(d1, d2, tolerance_days=1) is True

    def test_negative_direction(self):
        assert dates_within_tolerance("2024-01-17", "2024-01-15", tolerance_days=2) is True


class TestAmountsMatch:
    def test_exact_match(self):
        assert amounts_match(10000, 10000) is True

    def test_no_match(self):
        assert amounts_match(10000, 10001) is False

    def test_with_tolerance(self):
        assert amounts_match(10000, 10050, tolerance=100) is True

    def test_outside_tolerance(self):
        assert amounts_match(10000, 10200, tolerance=100) is False


class TestConversions:
    def test_cents_to_milliunits(self):
        assert cents_to_milliunits(1000) == 10000  # $10.00

    def test_dollars_to_milliunits(self):
        assert dollars_to_milliunits(10.00) == 10000

    def test_dollars_to_milliunits_cents(self):
        assert dollars_to_milliunits(10.50) == 10500


class TestFindBestMatch:
    def test_exact_match(self):
        candidates = [
            {"amount": 10000, "date": "2024-01-15"},
            {"amount": 20000, "date": "2024-01-16"},
        ]
        result = find_best_match(10000, "2024-01-15", candidates)
        assert result is not None
        assert result.match_type == "exact"
        assert result.matched_tx["amount"] == 10000

    def test_no_match(self):
        candidates = [
            {"amount": 99999, "date": "2024-06-01"},
        ]
        result = find_best_match(10000, "2024-01-15", candidates)
        assert result is None

    def test_amount_only_match(self):
        candidates = [
            {"amount": 10000, "date": "2024-06-01"},  # date way off
        ]
        result = find_best_match(10000, "2024-01-15", candidates)
        assert result is not None
        assert result.match_type == "amount_only"


class TestFindCombinationMatch:
    def test_single_item_combo(self):
        items = [{"amount": 10000}, {"amount": 5000}]
        result = find_combination_match(10000, items)
        assert result is not None
        assert len(result) == 1

    def test_two_item_combo(self):
        items = [{"amount": 6000}, {"amount": 4000}, {"amount": 3000}]
        result = find_combination_match(10000, items)
        assert result is not None
        assert sum(abs(i["amount"]) for i in result) == 10000

    def test_no_combo(self):
        items = [{"amount": 1000}, {"amount": 2000}]
        result = find_combination_match(50000, items)
        assert result is None

    def test_with_tolerance(self):
        items = [{"amount": 9800}]
        result = find_combination_match(10000, items, tolerance=500)
        assert result is not None
