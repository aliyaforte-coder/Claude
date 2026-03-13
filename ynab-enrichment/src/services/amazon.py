"""Amazon order history CSV parser."""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Any

from src.config import settings
from src.utils.logging import logger
from src.utils.matching import dollars_to_milliunits

# Common column name variations in Amazon exports
_COLUMN_ALIASES = {
    "order_date": ["order date", "order_date", "date"],
    "order_id": ["order id", "order_id", "orderid"],
    "title": ["title", "item title", "product name", "item_title", "product_name", "description"],
    "price": [
        "item total", "item_total", "total owed", "total_owed",
        "price", "item price", "item_price", "unit price", "unit_price",
    ],
    "quantity": ["quantity", "qty"],
    "category": ["category", "product category", "item category"],
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_")


def _map_columns(headers: list[str]) -> dict[str, str]:
    """Map our canonical field names to actual CSV column names."""
    mapping: dict[str, str] = {}
    normalized = {_normalize_header(h): h for h in headers}

    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize_header(alias)
            if norm_alias in normalized:
                mapping[canonical] = normalized[norm_alias]
                break

    return mapping


def _parse_price(value: str) -> float:
    """Parse a price string like '$12.34' or '12.34' into a float."""
    cleaned = value.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return 0.0
    return float(cleaned)


def _parse_date(value: str) -> datetime.date | None:
    """Parse common Amazon date formats."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning("Could not parse date: %s", value)
    return None


class AmazonParser:
    def __init__(self, csv_path: str | None = None) -> None:
        self.csv_path = Path(csv_path or settings.amazon_export_path)

    def parse_orders(self) -> list[dict[str, Any]]:
        """Parse Amazon order history CSV into a list of order items."""
        if not self.csv_path.exists():
            logger.warning("Amazon CSV not found at %s", self.csv_path)
            return []

        with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return []

            col_map = _map_columns(list(reader.fieldnames))
            if "order_date" not in col_map or "price" not in col_map:
                logger.error(
                    "Amazon CSV missing required columns. Found: %s, Mapped: %s",
                    reader.fieldnames,
                    col_map,
                )
                return []

            orders: list[dict[str, Any]] = []
            for row in reader:
                date_val = _parse_date(row.get(col_map["order_date"], ""))
                if date_val is None:
                    continue

                price = _parse_price(row.get(col_map["price"], "0"))
                if price == 0:
                    continue

                quantity = 1
                if "quantity" in col_map:
                    try:
                        quantity = int(row.get(col_map["quantity"], "1"))
                    except ValueError:
                        quantity = 1

                item: dict[str, Any] = {
                    "date": date_val.isoformat(),
                    "order_id": row.get(col_map.get("order_id", ""), ""),
                    "title": row.get(col_map.get("title", ""), "Unknown Item"),
                    "price": price,
                    "amount": dollars_to_milliunits(price),  # negative for outflow
                    "quantity": quantity,
                    "category": row.get(col_map.get("category", ""), ""),
                }
                orders.append(item)

            logger.info("Parsed %d items from Amazon CSV", len(orders))
            return orders

    def csv_exists(self) -> bool:
        return self.csv_path.exists()
