"""SQLite database for run history and undo logging."""

from __future__ import annotations

import aiosqlite
import json
import datetime
from pathlib import Path

from src.config import get_db_path

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        db_path = get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(db_path)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            result_summary TEXT,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS undo_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ynab_transaction_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            changed_at TEXT NOT NULL,
            run_id INTEGER,
            FOREIGN KEY (run_id) REFERENCES run_history(id)
        );

        CREATE TABLE IF NOT EXISTS enriched_transactions (
            ynab_transaction_id TEXT NOT NULL,
            module TEXT NOT NULL,
            enriched_at TEXT NOT NULL,
            PRIMARY KEY (ynab_transaction_id, module)
        );
    """)
    await db.commit()


async def log_run_start(module: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO run_history (module, started_at, status) VALUES (?, ?, ?)",
        (module, datetime.datetime.now(datetime.timezone.utc).isoformat(), "running"),
    )
    await db.commit()
    return cursor.lastrowid


async def log_run_complete(
    run_id: int, status: str = "success", summary: dict | None = None, error: str | None = None
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE run_history SET completed_at = ?, status = ?, result_summary = ?, error_message = ? WHERE id = ?",
        (
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status,
            json.dumps(summary) if summary else None,
            error,
            run_id,
        ),
    )
    await db.commit()


async def log_undo_entry(
    ynab_transaction_id: str,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    run_id: int,
) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO undo_log (ynab_transaction_id, field_name, old_value, new_value, changed_at, run_id) VALUES (?, ?, ?, ?, ?, ?)",
        (
            ynab_transaction_id,
            field_name,
            old_value,
            new_value,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            run_id,
        ),
    )
    await db.commit()


async def is_already_enriched(ynab_transaction_id: str, module: str) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM enriched_transactions WHERE ynab_transaction_id = ? AND module = ?",
        (ynab_transaction_id, module),
    )
    row = await cursor.fetchone()
    return row is not None


async def mark_enriched(ynab_transaction_id: str, module: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO enriched_transactions (ynab_transaction_id, module, enriched_at) VALUES (?, ?, ?)",
        (
            ynab_transaction_id,
            module,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )
    await db.commit()


async def get_last_runs() -> dict:
    db = await get_db()
    results = {}
    for module in ("validate", "privacy", "amazon"):
        cursor = await db.execute(
            "SELECT * FROM run_history WHERE module = ? ORDER BY id DESC LIMIT 1",
            (module,),
        )
        row = await cursor.fetchone()
        if row:
            results[module] = {
                "id": row["id"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "status": row["status"],
                "result_summary": json.loads(row["result_summary"]) if row["result_summary"] else None,
                "error_message": row["error_message"],
            }
    return results
