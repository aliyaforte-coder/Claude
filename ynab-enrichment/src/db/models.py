"""Pydantic models for database records and API responses."""

from __future__ import annotations

from pydantic import BaseModel


class RunHistoryRecord(BaseModel):
    id: int
    module: str
    started_at: str
    completed_at: str | None = None
    status: str
    result_summary: dict | None = None
    error_message: str | None = None


class UndoLogRecord(BaseModel):
    id: int
    ynab_transaction_id: str
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_at: str
    run_id: int | None = None


class ValidationReport(BaseModel):
    matched_count: int = 0
    unmatched_simplefin: list[dict] = []
    unmatched_ynab: list[dict] = []
    mismatches: list[dict] = []


class EnrichmentSummary(BaseModel):
    module: str
    transactions_processed: int = 0
    transactions_enriched: int = 0
    transactions_skipped: int = 0
    auto_categorized: int = 0
    needs_manual_review: list[dict] = []
    details: list[dict] = []
    dry_run: bool = False


class HealthStatus(BaseModel):
    status: str
    ynab: str = "unknown"
    simplefin: str = "unknown"
    amazon_csv: str = "unknown"
