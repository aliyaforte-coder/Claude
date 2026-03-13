"""Tests for Privacy.com enrichment logic."""

from src.enrichment.privacy_enricher import _is_privacy_transaction, _get_merchant_name


class TestIsPrivacyTransaction:
    def test_exact_match(self):
        assert _is_privacy_transaction("PRIVACY.COM") is True

    def test_partial_match(self):
        assert _is_privacy_transaction("Privacy.com Purchase") is True

    def test_case_insensitive(self):
        assert _is_privacy_transaction("privacy.com") is True

    def test_priv_star(self):
        assert _is_privacy_transaction("PRIV*Something") is True

    def test_no_match(self):
        assert _is_privacy_transaction("Amazon") is False

    def test_none(self):
        assert _is_privacy_transaction(None) is False

    def test_empty(self):
        assert _is_privacy_transaction("") is False


class TestGetMerchantName:
    def test_card_memo(self):
        tx = {"card": {"memo": "Netflix"}, "merchant": {"descriptor": "NFLX*12345"}}
        assert _get_merchant_name(tx) == "Netflix"

    def test_merchant_descriptor_fallback(self):
        tx = {"card": {"memo": ""}, "merchant": {"descriptor": "NFLX*12345"}}
        assert _get_merchant_name(tx) == "NFLX*12345"

    def test_no_info(self):
        tx = {"card": {}, "merchant": {}}
        assert _get_merchant_name(tx) == ""

    def test_empty_tx(self):
        assert _get_merchant_name({}) == ""
