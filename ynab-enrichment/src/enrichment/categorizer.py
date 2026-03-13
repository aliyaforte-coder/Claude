"""Auto-categorization engine using historical YNAB data and configurable mappings."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.config import settings, get_category_mappings_path
from src.services.ynab import YNABClient
from src.utils.logging import logger


class Categorizer:
    def __init__(self) -> None:
        self._learned_map: dict[str, dict[str, Any]] = {}
        self._override_map: dict[str, str] = {}
        self._amazon_map: dict[str, str] = {}
        self._initialized = False

    async def initialize(self, ynab_client: YNABClient) -> None:
        """Build category mappings from historical data and config files."""
        if self._initialized:
            return

        self._load_config_overrides()
        await self._learn_from_history(ynab_client)
        self._initialized = True

    def _load_config_overrides(self) -> None:
        """Load manual category overrides from JSON config."""
        path = get_category_mappings_path()
        if not path.exists():
            logger.info("No category mappings file found at %s", path)
            return

        try:
            with open(path) as f:
                data = json.load(f)
            self._override_map = {
                k: v for k, v in data.get("merchant_to_category", {}).items() if v
            }
            self._amazon_map = {
                k: v for k, v in data.get("amazon_category_to_ynab", {}).items() if v
            }
            logger.info(
                "Loaded %d merchant overrides and %d Amazon category mappings",
                len(self._override_map),
                len(self._amazon_map),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load category mappings: %s", e)

    async def _learn_from_history(self, ynab_client: YNABClient) -> None:
        """Build a merchant → category mapping from existing YNAB transactions."""
        try:
            transactions = await ynab_client.get_transactions()
        except Exception as e:
            logger.error("Failed to fetch YNAB transactions for learning: %s", e)
            return

        # Count category usage per merchant
        merchant_categories: dict[str, Counter] = {}
        for tx in transactions:
            payee = tx.get("payee_name")
            cat_id = tx.get("category_id")
            if not payee or not cat_id:
                continue
            payee_normalized = payee.strip().lower()
            if payee_normalized not in merchant_categories:
                merchant_categories[payee_normalized] = Counter()
            merchant_categories[payee_normalized][cat_id] += 1

        # Build mapping with confidence scores
        for merchant, counter in merchant_categories.items():
            total = sum(counter.values())
            most_common_cat, most_common_count = counter.most_common(1)[0]
            confidence = most_common_count / total
            self._learned_map[merchant] = {
                "category_id": most_common_cat,
                "confidence": confidence,
                "sample_size": total,
            }

        logger.info(
            "Learned category mappings for %d merchants", len(self._learned_map)
        )

    def categorize_merchant(self, merchant_name: str) -> tuple[str | None, float]:
        """Get the best category for a merchant name.

        Returns:
            Tuple of (category_id or None, confidence).
        """
        if not merchant_name:
            return None, 0.0

        # 1. Check manual overrides first (100% confidence)
        if merchant_name in self._override_map:
            return self._override_map[merchant_name], 1.0

        # Also check case-insensitive
        for override_name, cat_id in self._override_map.items():
            if override_name.lower() == merchant_name.lower():
                return cat_id, 1.0

        # 2. Check learned historical mapping
        normalized = merchant_name.strip().lower()
        if normalized in self._learned_map:
            entry = self._learned_map[normalized]
            return entry["category_id"], entry["confidence"]

        return None, 0.0

    def categorize_amazon(self, amazon_category: str) -> tuple[str | None, float]:
        """Get the YNAB category for an Amazon product category.

        Returns:
            Tuple of (category_id or None, confidence).
        """
        if not amazon_category:
            return self._amazon_map.get("default"), 0.5 if "default" in self._amazon_map else 0.0

        if amazon_category in self._amazon_map:
            return self._amazon_map[amazon_category], 0.9

        # Case-insensitive match
        for amz_cat, ynab_cat in self._amazon_map.items():
            if amz_cat.lower() == amazon_category.lower():
                return ynab_cat, 0.9

        # Fall back to default
        if "default" in self._amazon_map:
            return self._amazon_map["default"], 0.5

        return None, 0.0

    def should_auto_categorize(self, confidence: float) -> bool:
        """Check if the confidence meets the threshold for auto-categorization."""
        return confidence >= settings.confidence_threshold
