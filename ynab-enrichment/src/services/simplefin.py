"""SimpleFin API client."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlparse

import httpx

from src.config import settings
from src.utils.logging import logger


class SimpleFinClient:
    def __init__(self) -> None:
        self.access_url = settings.simplefin_access_url
        self._client: httpx.AsyncClient | None = None

    async def _ensure_access_url(self) -> str:
        """If we only have a setup token, claim it to get an access URL."""
        if self.access_url:
            return self.access_url

        setup_token = settings.simplefin_setup_token
        if not setup_token:
            raise ValueError(
                "Neither SIMPLEFIN_ACCESS_URL nor SIMPLEFIN_SETUP_TOKEN is configured"
            )

        # The setup token is base64-encoded and contains a claim URL
        claim_url = base64.b64decode(setup_token).decode("utf-8").strip()
        logger.info("Claiming SimpleFin setup token at %s", claim_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(claim_url)
            resp.raise_for_status()
            self.access_url = resp.text.strip()

        logger.info("SimpleFin access URL claimed successfully")
        return self.access_url

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client

        access_url = await self._ensure_access_url()
        parsed = urlparse(access_url)

        # Extract credentials from URL
        base_url = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            base_url += f":{parsed.port}"
        base_url += parsed.path.rstrip("/")

        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=(parsed.username or "", parsed.password or ""),
            timeout=30.0,
        )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_accounts(
        self, start_date: int | None = None, end_date: int | None = None
    ) -> list[dict[str, Any]]:
        """Fetch accounts and their transactions from SimpleFin.

        Args:
            start_date: Unix timestamp for start of date range.
            end_date: Unix timestamp for end of date range.
        """
        client = await self._get_client()
        params: dict[str, Any] = {}
        if start_date is not None:
            params["start-date"] = start_date
        if end_date is not None:
            params["end-date"] = end_date

        resp = await client.get("/accounts", params=params or None)
        resp.raise_for_status()
        data = resp.json()

        # SimpleFin returns {"errors": [], "accounts": [...]}
        if data.get("errors"):
            logger.warning("SimpleFin returned errors: %s", data["errors"])

        return data.get("accounts", [])

    async def health_check(self) -> bool:
        """Test connectivity to SimpleFin."""
        try:
            await self.get_accounts()
            return True
        except Exception as e:
            logger.error("SimpleFin health check failed: %s", e)
            return False
