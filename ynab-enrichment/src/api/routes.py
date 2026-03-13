"""API endpoint definitions."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File

from src.api.auth import verify_api_key
from src.db.database import get_last_runs
from src.db.models import EnrichmentSummary, HealthStatus, ValidationReport
from src.enrichment.amazon_enricher import enrich_amazon_transactions
from src.enrichment.categorizer import Categorizer
from src.enrichment.validator import validate_transactions
from src.services.amazon import AmazonParser
from src.services.simplefin import SimpleFinClient
from src.services.ynab import YNABClient
from src.utils.logging import logger

router = APIRouter(dependencies=[Depends(verify_api_key)])

# Shared client instances — initialized in lifespan
_ynab = None
_simplefin = None
_categorizer = None


def init_clients(
    ynab: YNABClient,
    simplefin: SimpleFinClient,
    categorizer: Categorizer,
) -> None:
    global _ynab, _simplefin, _categorizer
    _ynab = ynab
    _simplefin = simplefin
    _categorizer = categorizer


@router.post("/validate", response_model=ValidationReport)
async def validate(
    start_date: Optional[str] = Query(
        default=None,
        description="Start date (YYYY-MM-DD). Defaults to 30 days ago.",
    ),
    end_date: Optional[str] = Query(
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


@router.post("/enrich/amazon", response_model=EnrichmentSummary)
async def enrich_amazon(
    days_back: int = Query(default=90, ge=1, le=365),
    dry_run: bool = Query(default=True),
    csv_path: Optional[str] = Query(default=None, description="Path to Amazon CSV file"),
    csv_file: Optional[UploadFile] = File(default=None, description="Upload Amazon CSV"),
) -> EnrichmentSummary:
    """Run Amazon order enrichment on recent YNAB transactions."""
    actual_path = csv_path
    temp_path = None

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


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    """Health check — tests connectivity to all external APIs."""
    status = HealthStatus(status="ok")

    ynab_ok = await _ynab.health_check() if _ynab else False
    status.ynab = "connected" if ynab_ok else "error"

    simplefin_ok = await _simplefin.health_check() if _simplefin else False
    status.simplefin = "connected" if simplefin_ok else "error"

    parser = AmazonParser()
    status.amazon_csv = "found" if parser.csv_exists() else "not_found"

    if not all([ynab_ok, simplefin_ok]):
        status.status = "degraded"

    return status


@router.get("/status")
async def status() -> Dict[str, Any]:
    """Return last run timestamps and results for each module."""
    return await get_last_runs()
