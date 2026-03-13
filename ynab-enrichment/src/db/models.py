"""Pydantic models for database records and API responses."""

from typing import Dict, List, Optional

from pydantic import BaseModel


class RunHistoryRecord(BaseModel):
    id: int
    module: str
    started_at: str
    completed_at: Optional[str] = None
    status: str
    result_summary: Optional[dict] = None
    error_message: Optional[str] = None


class UndoLogRecord(BaseModel):
    id: int
    ynab_transaction_id: str
    field_name: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_at: str
    run_id: Optional[int] = None


class ValidationReport(BaseModel):
    matched_count: int = 0
    unmatched_simplefin: List[dict] = []
    unmatched_ynab: List[dict] = []
    mismatches: List[dict] = []


class EnrichmentSummary(BaseModel):
    module: str
    transactions_processed: int = 0
    transactions_enriched: int = 0
    transactions_skipped: int = 0
    auto_categorized: int = 0
    needs_manual_review: List[dict] = []
    details: List[dict] = []
    dry_run: bool = False


class HealthStatus(BaseModel):
    status: str
    ynab: str = "unknown"
    simplefin: str = "unknown"
    amazon_csv: str = "unknown"
