"""Tests for Amazon enrichment logic."""

from src.enrichment.amazon_enricher import (
    _is_amazon_transaction,
    _build_memo,
    _dominant_category,
    YNAB_MEMO_LIMIT,
)


class TestIsAmazonTransaction:
    def test_amazon(self):
        assert _is_amazon_transaction("Amazon") is True

    def test_amzn(self):
        assert _is_amazon_transaction("AMZN Mktp US") is True

    def test_amazon_com(self):
        assert _is_amazon_transaction("AMAZON.COM") is True

    def test_prime_video(self):
        assert _is_amazon_transaction("Prime Video") is True

    def test_no_match(self):
        assert _is_amazon_transaction("Walmart") is False

    def test_none(self):
        assert _is_amazon_transaction(None) is False


class TestBuildMemo:
    def test_single_item(self):
        items = [{"title": "USB-C Cable", "quantity": 1}]
        assert _build_memo(items) == "USB-C Cable"

    def test_multiple_items(self):
        items = [
            {"title": "USB-C Cable", "quantity": 1},
            {"title": "Kitchen Sponges", "quantity": 2},
        ]
        assert _build_memo(items) == "USB-C Cable, Kitchen Sponges (2)"

    def test_truncation(self):
        items = [{"title": "A" * 150, "quantity": 1}, {"title": "B" * 150, "quantity": 1}]
        memo = _build_memo(items)
        assert len(memo) <= YNAB_MEMO_LIMIT

    def test_empty(self):
        assert _build_memo([]) == ""


class TestDominantCategory:
    def test_single_category(self):
        items = [
            {"category": "Electronics", "price": 50.0},
            {"category": "Electronics", "price": 30.0},
        ]
        assert _dominant_category(items) == "Electronics"

    def test_multiple_categories(self):
        items = [
            {"category": "Electronics", "price": 100.0},
            {"category": "Books", "price": 10.0},
        ]
        assert _dominant_category(items) == "Electronics"

    def test_no_category(self):
        items = [{"price": 10.0}]
        assert _dominant_category(items) == ""
