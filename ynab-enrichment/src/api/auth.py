"""API key authentication middleware."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from src.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Verify the API key from the request header.

    If no API_KEY is configured in settings, authentication is disabled.
    """
    if not settings.api_key:
        return "no-auth"

    if not api_key or api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return api_key
