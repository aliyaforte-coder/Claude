"""Privacy.com API client."""

from __future__ import annotations

from typing import Any

import httpx

from src.config import settings
from src.utils.logging import logger


class PrivacyClient:
    def __init__(self) -> None:
        self.base_url = settings.privacy_base_url
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"api-key {settings.privacy_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_transactions(
        self,
        begin: str | None = None,
        end: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch transactions from Privacy.com.

        Args:
            begin: Start date in YYYY-MM-DD format.
            end: End date in YYYY-MM-DD format.
            page: Page number (1-indexed).
            page_size: Number of results per page.
        """
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if begin:
            params["begin"] = begin
        if end:
            params["end"] = end

        all_transactions: list[dict] = []
        while True:
            resp = await self._client.get("/v1/transactions", params=params)
            resp.raise_for_status()
            data = resp.json()
            txns = data.get("data", [])
            if not txns:
                break
            all_transactions.extend(txns)
            if len(txns) < page_size:
                break
            params["page"] = params.get("page", 1) + 1

        return all_transactions

    async def get_cards(self, page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        """Fetch cards from Privacy.com."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        resp = await self._client.get("/v1/cards", params=params)
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def health_check(self) -> bool:
        """Test connectivity to Privacy.com API."""
        try:
            await self.get_cards(page=1, page_size=1)
            return True
        except Exception as e:
            logger.error("Privacy.com health check failed: %s", e)
            return False
