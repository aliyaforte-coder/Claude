"""API endpoint definitions."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, UploadFile, File

from src.api.auth import verify_api_key
from src.db.database import get_last_runs
from src.db.models import EnrichmentSummary, HealthStatus, ValidationReport
from src.enrichment.amazon_enricher import enrich_amazon_transactions
from src.enrichment.categorizer import Categorizer
from src.enrichment.privacy_enricher import enrich_privacy_transactions
from src.enrichment.validator import validate_transactions
from src.services.amazon import AmazonParser
from src.services.privacy import PrivacyClient
from src.services.simplefin import SimpleFinClient
from src.services.ynab import YNABClient
from src.utils.logging import logger

router = APIRouter(dependencies=[Depends(verify_api_key)])

# Shared client instances — initialized in lifespan
_ynab: YNABClient | None = None
_simplefin: SimpleFinClient | None = None
_privacy: PrivacyClient | None = None
_categorizer: Categorizer | None = None


def init_clients(
    ynab: YNABClient,
    simplefin: SimpleFinClient,
    privacy: PrivacyClient,
    categorizer: Categorizer,
) -> None:
    global _ynab, _simplefin, _privacy, _categorizer
    _ynab = ynab
    _simplefin = simplefin
    _privacy = privacy
    _categorizer = categorizer


@router.post("/validate", response_model=ValidationReport)
async def validate(
    start_date: str = Query(
        default=None,
        description="Start date (YYYY-MM-DD). Defaults to 30 days ago.",
    ),
    end_date: str = Query(
        default=None,
        description="End date (YYYY-MM-DD). Defaults to today.",
    ),
) -> ValidationReport:
    """Run SimpleFin ↔ YNAB transaction validation."""
    today = datetime.date.today()
    if not end_date:
        end_date = today.isoformat()
    if not start_date:
        start_date = (today - datetime.timedelta(days=30)).isoformat()

    return await validate_transactions(
        ynab_client=_ynab,
        simplefin_client=_simplefin,
        start_date=start_date,
        end_date=end_date,
    )


@router.post("/enrich/privacy", response_model=EnrichmentSummary)
async def enrich_privacy(
    days_back: int = Query(default=30, ge=1, le=365),
    dry_run: bool = Query(default=True),
) -> EnrichmentSummary:
    """Run Privacy.com enrichment on recent YNAB transactions."""
    return await enrich_privacy_transactions(
        ynab_client=_ynab,
        privacy_client=_privacy,
        categorizer=_categorizer,
        days_back=days_back,
        dry_run=dry_run,
    )


@router.post("/enrich/amazon", response_model=EnrichmentSummary)
async def enrich_amazon(
    days_back: int = Query(default=90, ge=1, le=365),
    dry_run: bool = Query(default=True),
    csv_path: str | None = Query(default=None, description="Path to Amazon CSV file"),
    csv_file: UploadFile | None = File(default=None, description="Upload Amazon CSV"),
) -> EnrichmentSummary:
    """Run Amazon order enrichment on recent YNAB transactions."""
    actual_path = csv_path
    temp_path: Path | None = None

    if csv_file:
        # Save uploaded file temporarily
        temp_path = Path("data") / f"upload_{csv_file.filename}"
        content = await csv_file.read()
        temp_path.write_bytes(content)
        actual_path = str(temp_path)

    try:
        parser = AmazonParser(csv_path=actual_path)
        return await enrich_amazon_transactions(
            ynab_client=_ynab,
            amazon_parser=parser,
            categorizer=_categorizer,
            days_back=days_back,
            dry_run=dry_run,
        )
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


@router.post("/enrich/all")
async def enrich_all(
    days_back: int = Query(default=30, ge=1, le=365),
    dry_run: bool = Query(default=True),
) -> dict[str, Any]:
    """Run all enrichment modules in sequence."""
    privacy_result = await enrich_privacy_transactions(
        ynab_client=_ynab,
        privacy_client=_privacy,
        categorizer=_categorizer,
        days_back=days_back,
        dry_run=dry_run,
    )
    amazon_result = await enrich_amazon_transactions(
        ynab_client=_ynab,
        amazon_parser=AmazonParser(),
        categorizer=_categorizer,
        days_back=days_back,
        dry_run=dry_run,
    )
    return {
        "privacy": privacy_result.model_dump(),
        "amazon": amazon_result.model_dump(),
    }


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    """Health check — tests connectivity to all external APIs."""
    status = HealthStatus(status="ok")

    ynab_ok = await _ynab.health_check() if _ynab else False
    status.ynab = "connected" if ynab_ok else "error"

    simplefin_ok = await _simplefin.health_check() if _simplefin else False
    status.simplefin = "connected" if simplefin_ok else "error"

    privacy_ok = await _privacy.health_check() if _privacy else False
    status.privacy = "connected" if privacy_ok else "error"

    parser = AmazonParser()
    status.amazon_csv = "found" if parser.csv_exists() else "not_found"

    if not all([ynab_ok, simplefin_ok, privacy_ok]):
        status.status = "degraded"

    return status


@router.get("/status")
async def status() -> dict[str, Any]:
    """Return last run timestamps and results for each module."""
    return await get_last_runs()
