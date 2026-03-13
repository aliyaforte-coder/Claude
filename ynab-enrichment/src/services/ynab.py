"""YNAB API client with rate limiting."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.config import settings
from src.utils.logging import logger


class YNABRateLimiter:
    """Simple sliding-window rate limiter for YNAB's 200 req/hour limit."""

    def __init__(self, max_requests: int = 200, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []

    async def acquire(self) -> None:
        now = time.monotonic()
        # Prune old timestamps
        self._timestamps = [t for t in self._timestamps if now - t < self.window_seconds]
        if len(self._timestamps) >= self.max_requests:
            wait = self._timestamps[0] + self.window_seconds - now + 0.1
            logger.warning("YNAB rate limit reached, waiting %.1f seconds", wait)
            await asyncio.sleep(wait)
        self._timestamps.append(time.monotonic())


class YNABClient:
    def __init__(self) -> None:
        self.base_url = settings.ynab_base_url
        self.budget_id = settings.ynab_budget_id
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {settings.ynab_api_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._limiter = YNABRateLimiter(settings.ynab_rate_limit)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        await self._limiter.acquire()
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, path: str, json_body: dict) -> dict:
        await self._limiter.acquire()
        resp = await self._client.patch(path, json=json_body)
        resp.raise_for_status()
        return resp.json()

    async def get_transactions(
        self, since_date: str | None = None, server_knowledge: int | None = None
    ) -> list[dict[str, Any]]:
        """Fetch transactions from YNAB. Handles pagination via server_knowledge."""
        params: dict[str, Any] = {}
        if since_date:
            params["since_date"] = since_date
        if server_knowledge is not None:
            params["last_knowledge_of_server"] = server_knowledge

        data = await self._get(
            f"/budgets/{self.budget_id}/transactions", params=params or None
        )
        return data["data"]["transactions"]

    async def get_categories(self) -> list[dict[str, Any]]:
        """Fetch all category groups and their categories."""
        data = await self._get(f"/budgets/{self.budget_id}/categories")
        return data["data"]["category_groups"]

    async def update_transaction(
        self, transaction_id: str, updates: dict[str, Any]
    ) -> dict:
        """Update a single YNAB transaction."""
        data = await self._patch(
            f"/budgets/{self.budget_id}/transactions/{transaction_id}",
            {"transaction": updates},
        )
        return data["data"]["transaction"]

    async def bulk_update_transactions(
        self, transactions: list[dict[str, Any]]
    ) -> dict:
        """Bulk update transactions."""
        await self._limiter.acquire()
        resp = await self._client.patch(
            f"/budgets/{self.budget_id}/transactions",
            json={"transactions": transactions},
        )
        resp.raise_for_status()
        return resp.json()["data"]

    async def health_check(self) -> bool:
        """Test connectivity to YNAB API."""
        try:
            await self._get(f"/budgets/{self.budget_id}")
            return True
        except Exception as e:
            logger.error("YNAB health check failed: %s", e)
            return False
