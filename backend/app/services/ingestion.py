"""Reads the allowlisted CSVs and writes them to Supabase.

Order: reference tables, then raw_events, then events (ingest_all / the
events route run these phases in that sequence). Writes are chunked (1000
rows) and use upsert with the on_conflict key for that table, so running the
same file twice never creates duplicates. Transient write errors are retried
with backoff; anything still failing after that raises IngestionError.

dry_run=True parses and validates every row but writes nothing.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app import database
from app.config import get_settings
from app.services import normalize
from app.services.normalize import RejectedRow

log = logging.getLogger("fsia.ingestion")

CHUNK_SIZE = 1000
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 0.5  # seconds; doubles each retry

EVENT_FILES = ("authentication_logs.csv", "api_logs.csv", "transactions.csv")
_SOURCE_TO_FILE = {"auth": "authentication_logs.csv", "api": "api_logs.csv",
                   "transaction": "transactions.csv"}


class IngestionError(RuntimeError):
    """A write to Supabase failed after retries. Never carries row values."""


@dataclass
class IngestResult:
    table: str
    rows_read: int = 0
    rows_written: int = 0
    rejected: list[RejectedRow] = field(default_factory=list)
    duration_seconds: float = 0.0


def _csv_path(filename: str) -> Path:
    # Allowlist check by construction: filename always comes from the
    # hardcoded tuples/dicts above, never from a request parameter.
    if filename not in normalize.ALLOWED_FILES:
        raise ValueError(f"{filename!r} is not an allowed ingestion file")
    return get_settings().DATA_DIR / filename


def _files_for_source(source: str) -> list[str]:
    if source == "all":
        return list(EVENT_FILES)
    if source not in _SOURCE_TO_FILE:
        raise ValueError(f"unknown source: {source!r}")
    return [_SOURCE_TO_FILE[source]]


def _upsert_with_retry(table: str, rows: list[dict], on_conflict: str) -> None:
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            database.get_admin_client().table(table).upsert(rows, on_conflict=on_conflict).execute()
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == RETRY_ATTEMPTS - 1:
                break
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            log.warning("upsert into %s failed (%s), retrying in %.1fs",
                       table, type(last_exc).__name__, delay)
            time.sleep(delay)
    raise IngestionError(
        f"writing {len(rows)} row(s) to {table} failed after {RETRY_ATTEMPTS} attempts "
        f"({type(last_exc).__name__})"
    ) from last_exc


def _flush(buffer: list[dict], table: str, on_conflict: str, dry_run: bool) -> int:
    if not buffer:
        return 0
    n = len(buffer)
    if dry_run:
        buffer.clear()
        return 0   # dry_run writes nothing, so nothing counts as written
    _upsert_with_retry(table, buffer, on_conflict)
    buffer.clear()
    return n


# --------------------------------------------------------------------------
# phase 1: reference tables
# --------------------------------------------------------------------------
def _ingest_reference_file(filename: str, table: str, normalizer, on_conflict: str,
                           dry_run: bool) -> IngestResult:
    path = _csv_path(filename)
    start = time.perf_counter()
    result = IngestResult(table=table)
    buffer: list[dict] = []
    for line_no, row in normalize.read_csv_rows(path):
        result.rows_read += 1
        try:
            record = normalizer(row)
        except normalize.RowError as exc:
            result.rejected.append(RejectedRow(filename, line_no,
                                                normalize.row_id_for_report(filename, row), str(exc)))
            continue
        buffer.append(record)
        if len(buffer) >= CHUNK_SIZE:
            result.rows_written += _flush(buffer, table, on_conflict, dry_run)
    result.rows_written += _flush(buffer, table, on_conflict, dry_run)
    result.duration_seconds = time.perf_counter() - start
    return result


def ingest_reference(dry_run: bool = False) -> list[IngestResult]:
    return [
        _ingest_reference_file(filename, table, normalizer, on_conflict, dry_run)
        for filename, (table, normalizer, on_conflict) in normalize.REFERENCE_TABLES.items()
    ]


# --------------------------------------------------------------------------
# phase 2: raw_events (untouched evidence copy)
# --------------------------------------------------------------------------
def ingest_raw_events(source: str = "all", dry_run: bool = False) -> IngestResult:
    files = _files_for_source(source)
    start = time.perf_counter()
    result = IngestResult(table="raw_events")
    buffer: list[dict] = []
    for filename in files:
        path = _csv_path(filename)
        for line_no, row in normalize.read_csv_rows(path):
            result.rows_read += 1
            ids = normalize.extract_raw(filename, row)
            if ids is None:
                result.rejected.append(RejectedRow(filename, line_no, None,
                                                    "missing id field; row skipped for raw_events"))
                continue
            source_type, source_event_id = ids
            buffer.append({"source_type": source_type, "source_event_id": source_event_id,
                           "payload": dict(row)})
            if len(buffer) >= CHUNK_SIZE:
                result.rows_written += _flush(buffer, "raw_events", "source_type,source_event_id", dry_run)
    result.rows_written += _flush(buffer, "raw_events", "source_type,source_event_id", dry_run)
    result.duration_seconds = time.perf_counter() - start
    return result


# --------------------------------------------------------------------------
# phase 3: events (validated / normalized)
# --------------------------------------------------------------------------
def ingest_events(source: str = "all", dry_run: bool = False) -> IngestResult:
    files = _files_for_source(source)
    start = time.perf_counter()
    result = IngestResult(table="events")
    buffer: list[dict] = []
    for filename in files:
        normalizer = normalize.EVENT_NORMALIZERS[filename]
        path = _csv_path(filename)
        for line_no, row in normalize.read_csv_rows(path):
            result.rows_read += 1
            try:
                parsed = normalizer(row)
            except normalize.RowError as exc:
                result.rejected.append(RejectedRow(filename, line_no,
                                                    normalize.row_id_for_report(filename, row), str(exc)))
                continue
            buffer.append(parsed.event)
            if len(buffer) >= CHUNK_SIZE:
                result.rows_written += _flush(buffer, "events", "event_id", dry_run)
    result.rows_written += _flush(buffer, "events", "event_id", dry_run)
    result.duration_seconds = time.perf_counter() - start
    return result


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def result_dict(r: IngestResult) -> dict:
    return {
        "table": r.table,
        "rows_read": r.rows_read,
        "rows_written": r.rows_written,
        "rejected_count": len(r.rejected),
        "rejected_samples": [asdict(x) for x in r.rejected[:20]],
        "duration_seconds": round(r.duration_seconds, 3),
    }


def combine_results(results: list[IngestResult]) -> dict:
    all_rejected = [x for r in results for x in r.rejected]
    return {
        "tables": [result_dict(r) for r in results],
        "rows_read": sum(r.rows_read for r in results),
        "rows_written": sum(r.rows_written for r in results),
        "rejected_count": len(all_rejected),
        "rejected_samples": [asdict(x) for x in all_rejected[:20]],
        "duration_seconds": round(sum(r.duration_seconds for r in results), 3),
    }


# --------------------------------------------------------------------------
# summary: CSV row counts vs database counts, per table
# --------------------------------------------------------------------------
_CSV_ROW_COUNT_SOURCES = {
    "user_devices": ("users_devices.csv",),
    "threat_indicators": ("threat_indicators.csv",),
    "raw_events": EVENT_FILES,
    "events": EVENT_FILES,
}


def _db_row_count(table: str) -> int:
    res = database.get_admin_client().table(table).select("*", count="exact").limit(1).execute()
    return res.count or 0


def summary() -> dict:
    out = {}
    for table, files in _CSV_ROW_COUNT_SOURCES.items():
        csv_rows = sum(normalize.count_data_rows(_csv_path(f)) for f in files)
        out[table] = {"csv_rows": csv_rows, "db_rows": _db_row_count(table)}
    return out
