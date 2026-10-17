"""CSV parsing + mapping to database-shaped dicts. No database access here.

Reads the 5 allowlisted CSVs and maps each row to the shape `ingestion.py`
writes to Supabase. A row that fails validation raises RowError; the caller
(`ingestion.py`) catches it, records a RejectedRow, and keeps going -- one
bad row never stops the load.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

# Exact filenames only. Never build a path from anything else (no user input,
# no directory listing). ground_truth_*.csv and data/README.md are never here.
ALLOWED_FILES = (
    "authentication_logs.csv",
    "api_logs.csv",
    "transactions.csv",
    "users_devices.csv",
    "threat_indicators.csv",
)


class RowError(ValueError):
    """A single row is unusable. Caught per-row; never raised past one row."""


@dataclass
class RejectedRow:
    file: str
    line: int
    id: str | None
    reason: str


@dataclass
class ParsedEvent:
    raw: dict    # {source_type, source_event_id, payload} for raw_events
    event: dict  # for the events table


# --------------------------------------------------------------------------
# field helpers
# --------------------------------------------------------------------------
def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


def _require(value: str | None, field: str) -> str:
    v = _blank_to_none(value)
    if v is None:
        raise RowError(f"{field} is blank")
    return v


def parse_timestamp(value: str | None, field: str = "timestamp") -> str:
    v = _require(value, field)
    try:
        dt = datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        raise RowError(f"{field} is not 'YYYY-MM-DD HH:MM:SS': {v!r}") from None
    return dt.isoformat()


def parse_date(value: str | None, field: str = "last_seen") -> str | None:
    v = _blank_to_none(value)
    if v is None:
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise RowError(f"{field} is not 'YYYY-MM-DD': {v!r}") from None
    return v


def parse_numeric(value: str | None, field: str) -> float | None:
    v = _blank_to_none(value)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        raise RowError(f"{field} is not numeric: {v!r}") from None


def parse_int(value: str | None, field: str) -> int | None:
    v = _blank_to_none(value)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        raise RowError(f"{field} is not an integer: {v!r}") from None


def parse_yn(value: str | None, field: str) -> bool:
    v = _require(value, field).upper()
    if v == "Y":
        return True
    if v == "N":
        return False
    raise RowError(f"{field} must be Y or N: {v!r}")


def read_csv_rows(path: Path) -> Iterator[tuple[int, dict]]:
    """Yields (line_number, row). line_number counts the header as line 1,
    so the first data row is line 2 (matches what you'd see in an editor).
    utf-8-sig quietly drops a BOM if one is present; files are CRLF."""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for line_no, row in enumerate(reader, start=2):
            yield line_no, row


def count_data_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        return sum(1 for _ in reader)


# --------------------------------------------------------------------------
# events: authentication_logs.csv, api_logs.csv, transactions.csv
# --------------------------------------------------------------------------
_EVENT_SHAPE = dict(
    event_id=None, event_kind=None, source_type=None, ts=None, user_id=None,
    ip_address=None, device_id=None, location=None, status=None, mfa_status=None,
    endpoint=None, http_method=None, status_code=None, amount=None, merchant=None,
)


def normalize_auth_row(row: dict) -> ParsedEvent:
    event_id = _require(row.get("event_id"), "event_id")
    ts = parse_timestamp(row.get("timestamp"))
    event_type = _require(row.get("event_type"), "event_type")
    if event_type not in ("login", "logout"):
        raise RowError(f"event_type must be login or logout: {event_type!r}")

    event = dict(_EVENT_SHAPE)
    event.update(
        event_id=event_id,
        event_kind=event_type,
        source_type="auth",
        ts=ts,
        user_id=_blank_to_none(row.get("user_id")),
        ip_address=_blank_to_none(row.get("ip_address")),
        device_id=_blank_to_none(row.get("device_id")),
        location=_blank_to_none(row.get("location")),
        status=_blank_to_none(row.get("status")),
        mfa_status=_blank_to_none(row.get("mfa_status")),  # keeps 'n/a' as-is
    )
    raw = {"source_type": "auth", "source_event_id": event_id, "payload": dict(row)}
    return ParsedEvent(raw=raw, event=event)


def normalize_api_row(row: dict) -> ParsedEvent:
    event_id = _require(row.get("event_id"), "event_id")
    ts = parse_timestamp(row.get("timestamp"))
    status_code = parse_int(row.get("status_code"), "status_code")

    event = dict(_EVENT_SHAPE)
    event.update(
        event_id=event_id,
        event_kind="api_call",
        source_type="api",
        ts=ts,
        user_id=_blank_to_none(row.get("user_id")),
        ip_address=_blank_to_none(row.get("ip_address")),
        endpoint=_blank_to_none(row.get("endpoint")),
        http_method=_blank_to_none(row.get("method")),
        status_code=status_code,
        # status stays NULL: api_logs has no success/failed field -- never invent one.
    )
    raw = {"source_type": "api", "source_event_id": event_id, "payload": dict(row)}
    return ParsedEvent(raw=raw, event=event)


def normalize_transaction_row(row: dict) -> ParsedEvent:
    transaction_id = _require(row.get("transaction_id"), "transaction_id")
    ts = parse_timestamp(row.get("timestamp"))
    amount = parse_numeric(row.get("amount"), "amount")

    event = dict(_EVENT_SHAPE)
    event.update(
        event_id=transaction_id,
        event_kind="transaction",
        source_type="transaction",
        ts=ts,
        user_id=_blank_to_none(row.get("user_id")),
        ip_address=_blank_to_none(row.get("ip_address")),
        device_id=_blank_to_none(row.get("device_id")),
        location=_blank_to_none(row.get("location")),
        status=_blank_to_none(row.get("status")),
        amount=amount,
        merchant=_blank_to_none(row.get("merchant")),
    )
    raw = {"source_type": "transaction", "source_event_id": transaction_id, "payload": dict(row)}
    return ParsedEvent(raw=raw, event=event)


EVENT_NORMALIZERS: dict[str, Callable[[dict], ParsedEvent]] = {
    "authentication_logs.csv": normalize_auth_row,
    "api_logs.csv": normalize_api_row,
    "transactions.csv": normalize_transaction_row,
}

# For raw_events: which source_type + which column holds the id.
# raw_events keeps EVERY row that has an id, even ones normalize_*_row rejects
# above -- it is the untouched evidence copy, independent of validation.
EVENT_SOURCE_TYPE = {
    "authentication_logs.csv": "auth",
    "api_logs.csv": "api",
    "transactions.csv": "transaction",
}
EVENT_ID_FIELD = {
    "authentication_logs.csv": "event_id",
    "api_logs.csv": "event_id",
    "transactions.csv": "transaction_id",
}


def extract_raw(filename: str, row: dict) -> tuple[str, str] | None:
    """Returns (source_type, source_event_id) for raw_events, or None if the
    row has no usable id (the only thing that can make raw_events reject a row)."""
    source_type = EVENT_SOURCE_TYPE[filename]
    id_field = EVENT_ID_FIELD[filename]
    v = row.get(id_field)
    sid = v.strip() if v else None
    if not sid:
        return None
    return source_type, sid


# --------------------------------------------------------------------------
# reference tables: users_devices.csv, threat_indicators.csv
# --------------------------------------------------------------------------
def normalize_user_device_row(row: dict) -> dict:
    user_id = _require(row.get("user_id"), "user_id")
    device_id = _require(row.get("device_id"), "device_id")
    registered_device = parse_yn(row.get("registered_device"), "registered_device")
    avg_txn_amount = parse_numeric(row.get("avg_txn_amount"), "avg_txn_amount")
    return {
        "user_id": user_id,
        "device_id": device_id,
        "registered_device": registered_device,
        "usual_location": _blank_to_none(row.get("usual_location")),
        "usual_ip": _blank_to_none(row.get("usual_ip")),
        "secondary_ip": _blank_to_none(row.get("secondary_ip")),
        "device_type": _blank_to_none(row.get("device_type")),
        "avg_txn_amount": avg_txn_amount,
    }


_THREAT_LEVELS = ("High", "Medium", "Low")


def normalize_threat_indicator_row(row: dict) -> dict:
    ip_address = _require(row.get("ip_address"), "ip_address")
    threat_level = _blank_to_none(row.get("threat_level"))
    if threat_level is not None and threat_level not in _THREAT_LEVELS:
        raise RowError(f"threat_level must be High/Medium/Low: {threat_level!r}")
    last_seen = parse_date(row.get("last_seen"))
    return {
        "ip_address": ip_address,
        "indicator_type": _blank_to_none(row.get("indicator_type")),
        "threat_level": threat_level,
        "source": _blank_to_none(row.get("source")),
        "description": _blank_to_none(row.get("description")),
        "last_seen": last_seen,
    }


# (table, normalizer, on_conflict key)
REFERENCE_TABLES: dict[str, tuple[str, Callable[[dict], dict], str]] = {
    "users_devices.csv": ("user_devices", normalize_user_device_row, "user_id,device_id"),
    "threat_indicators.csv": ("threat_indicators", normalize_threat_indicator_row, "ip_address"),
}


# --------------------------------------------------------------------------
# id extraction for RejectedRow reporting
# --------------------------------------------------------------------------
def row_id_for_report(filename: str, row: dict) -> str | None:
    if filename == "users_devices.csv":
        u = _blank_to_none(row.get("user_id"))
        d = _blank_to_none(row.get("device_id"))
        if u and d:
            return f"{u}/{d}"
        return u or d
    if filename == "threat_indicators.csv":
        return _blank_to_none(row.get("ip_address"))
    field = EVENT_ID_FIELD.get(filename)
    return _blank_to_none(row.get(field)) if field else None
