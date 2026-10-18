"""Parse backend/ml/output/ and load it into Supabase as ONE pipeline run.

Part A (no database): read_outputs / parse_outputs / dry_parse. Files come only from a
fixed allowlist inside ML_OUTPUT_DIR. A bad row is skipped and counted, never invented.
Part B (database): load(). Order: pipeline_runs (running) -> ml_results -> incidents ->
read back incident uuids -> incident_events -> rule_alerts -> reports -> dashboard_snapshots,
then verify counts, mark the run completed and switch it current with
rpc("set_current_run") (migration 004). Upserts reuse the ingestion retry helper; the
pipeline_runs insert and the rpc are NOT retried. Errors and logs carry the exception
type and step name only, never row values.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import database
from app.services import ingestion

log = logging.getLogger("fsia.ml_loader")

REQUIRED_FILES = ("scored_auth.csv", "scored_txn.csv", "incidents.json",
                  "dashboard.json", "pipeline_run.json", "rule_alerts.csv")
OPTIONAL_FILES = ("reports.json",)
ALLOWED_FILES = REQUIRED_FILES + OPTIONAL_FILES

SEVERITIES = ("critical", "high", "medium", "low")
STATUSES = ("OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED")
REPORT_SOURCES = ("llm", "llm_corrected", "template")

ML_CHUNK = 1000
INCIDENT_CHUNK = 500
PAGE_SIZE = 1000
IN_CHUNK = 50

_CSV_COLUMNS = {
    "scored_auth.csv": ("event_id", "anomaly_score", "is_flagged", "top_reasons", "flag_reason"),
    "scored_txn.csv": ("transaction_id", "anomaly_score", "is_flagged", "top_reasons", "flag_reason"),
    "rule_alerts.csv": ("event_id", "rule_id", "rule_name", "severity", "timestamp"),
}


class MissingOutputError(Exception):
    """A required output file is missing: the pipeline has not been run."""


class InconsistentOutputError(Exception):
    """The files do not belong together (or cannot be read); nothing is written."""


class LoadError(Exception):
    """A database load failed. The message is safe to show (type + step, no values)."""

    def __init__(self, message: str, run_id: str | None = None):
        super().__init__(message)
        self.public_message = message
        self.run_id = run_id


# ---------------------------------------------------------------------------
# Part A: reading and parsing (no database)
# ---------------------------------------------------------------------------
def _path(output_dir: Path, name: str) -> Path:
    if name not in ALLOWED_FILES:
        raise ValueError(f"{name!r} is not an allowed pipeline output file")
    return Path(output_dir) / name


def _reject_constant(name: str):
    raise ValueError(f"non-finite JSON constant {name}")


def _read_json(output_dir: Path, name: str):
    try:
        with _path(output_dir, name).open("r", encoding="utf-8") as fh:
            return json.load(fh, parse_constant=_reject_constant)
    except (OSError, ValueError):
        raise InconsistentOutputError(f"{name} is not valid JSON") from None


def _read_csv(output_dir: Path, name: str) -> list[dict]:
    try:
        with _path(output_dir, name).open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _CSV_COLUMNS[name] if c not in (reader.fieldnames or [])]
            if missing:
                raise InconsistentOutputError(f"{name} lacks column(s): {', '.join(missing)}")
            return list(reader)
    except (OSError, csv.Error):
        raise InconsistentOutputError(f"{name} cannot be read") from None


def read_outputs(output_dir: Path) -> dict:
    missing = [n for n in REQUIRED_FILES if not _path(output_dir, n).is_file()]
    if missing:
        raise MissingOutputError("Pipeline output is missing (run the pipeline first): "
                                 + ", ".join(missing))
    data: dict[str, Any] = {
        "auth": _read_csv(output_dir, "scored_auth.csv"),
        "txn": _read_csv(output_dir, "scored_txn.csv"),
        "alerts": _read_csv(output_dir, "rule_alerts.csv"),
        "incidents": _read_json(output_dir, "incidents.json"),
        "dashboard": _read_json(output_dir, "dashboard.json"),
        "pipeline_run": _read_json(output_dir, "pipeline_run.json"),
        "reports": None,
    }
    if _path(output_dir, "reports.json").is_file():
        data["reports"] = _read_json(output_dir, "reports.json")
    if not isinstance(data["incidents"], list):
        raise InconsistentOutputError("incidents.json is not a list")
    if not isinstance(data["dashboard"], dict) or not isinstance(data["pipeline_run"], dict):
        raise InconsistentOutputError("dashboard.json / pipeline_run.json is not an object")
    if data["reports"] is not None and not isinstance(data["reports"], list):
        raise InconsistentOutputError("reports.json is not a list")
    return data


def check_consistency(pipeline_run: dict, incidents: list, dashboard: dict) -> str:
    """The same pipeline_run_id must be in pipeline_run.json, every incident and
    dashboard.json. Returns that fingerprint, or raises InconsistentOutputError."""
    fingerprint = pipeline_run.get("pipeline_run_id")
    if not isinstance(fingerprint, str) or not fingerprint.strip() or len(fingerprint) > 64:
        raise InconsistentOutputError("pipeline_run.json has no usable pipeline_run_id")
    in_incidents = {i.get("pipeline_run_id") if isinstance(i, dict) else None for i in incidents}
    if in_incidents != {fingerprint}:
        raise InconsistentOutputError(
            f"pipeline_run_id differs: pipeline_run.json has {fingerprint}, "
            f"incidents.json has {len(in_incidents)} distinct value(s)")
    if dashboard.get("pipeline_run_id") != fingerprint:
        raise InconsistentOutputError(
            f"pipeline_run_id differs: pipeline_run.json has {fingerprint}, "
            "dashboard.json has another value")
    return fingerprint


def _utc_iso(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("not a string")
    dt = datetime.fromisoformat(value.strip())
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.isoformat()


def _num(value: Any, limit: float) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool")
    number = float(value)
    if not math.isfinite(number) or abs(number) >= limit:
        raise ValueError("out of range")
    return number


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool")
    number = float(value)
    if not number.is_integer() or abs(number) >= 2**31:
        raise ValueError("not an integer")
    return int(number)


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


@dataclass
class ParsedOutputs:
    fingerprint: str
    created_at: str | None
    ml_results: list[dict]
    incidents: list[dict]
    incident_pairs: list[tuple[str, str]]          # (incident external_id, event_id)
    rule_alerts: list[dict]
    reports: list[dict]                            # each has "external_id" + report columns
    dashboard: dict
    rows_read: dict[str, int]
    skips: dict[str, Counter]
    flagged_count: int
    reports_file_present: bool
    checks: dict[str, bool | None] = field(default_factory=dict)


def parse_ml_results(auth_rows: list[dict], txn_rows: list[dict], skips: Counter) -> list[dict]:
    out, seen = [], set()
    for rows, id_col in ((auth_rows, "event_id"), (txn_rows, "transaction_id")):
        for row in rows:
            event_id = (row.get(id_col) or "").strip()
            if not event_id:
                skips["missing_id"] += 1
                continue
            if event_id in seen:
                skips["duplicate_event_id"] += 1
                continue
            flag = (row.get("is_flagged") or "").strip()
            if flag not in ("0", "1"):                   # is_flagged only; is_anomaly is ignored
                skips["bad_is_flagged"] += 1
                continue
            try:
                score = _num(row.get("anomaly_score"), 1e9)
            except ValueError:
                score = None
            if score is None:
                skips["bad_anomaly_score"] += 1
                continue
            reasons_text = (row.get("top_reasons") or "").strip()
            reasons = None
            if reasons_text:
                try:
                    reasons = json.loads(reasons_text, parse_constant=_reject_constant)
                except ValueError:
                    reasons = "bad"
                if not isinstance(reasons, list):
                    skips["bad_top_reasons"] += 1
                    continue
            seen.add(event_id)
            out.append({"event_id": event_id, "anomaly_score": score, "is_anomalous": flag == "1",
                        "shap_reasons": reasons, "flag_reason": _blank_to_none(row.get("flag_reason"))})
    return out


_LIST_FIELDS = ("users", "ips", "ip_details", "reasons", "timeline", "rule_hits",
                "ml_event_ids", "rule_mitre")


def parse_incidents(items: list, skips: Counter) -> tuple[list[dict], list[tuple[str, str]]]:
    rows, pairs, seen = [], [], set()
    for inc in items:
        if not isinstance(inc, dict):
            skips["not_an_object"] += 1
            continue
        external_id = _blank_to_none(inc.get("id"))
        if not isinstance(external_id, str):
            skips["missing_id"] += 1
            continue
        if external_id in seen:
            skips["duplicate_id"] += 1
            continue
        severity = str(inc.get("sev") or "").strip().lower()
        if severity not in SEVERITIES:
            skips["bad_severity"] += 1
            continue
        title = _blank_to_none(inc.get("title"))
        if not isinstance(title, str):
            skips["missing_title"] += 1
            continue
        try:
            confidence = _num(inc.get("confidence"), 1000)
            impact = _num(inc.get("impact"), 1000)
            risk_score = _num(inc.get("risk_score"), 1000)
            amount_total = _num(inc.get("amount_total"), 1e12)
            event_count = _int(inc.get("event_count"))
        except (ValueError, TypeError):
            skips["bad_number"] += 1
            continue
        try:
            started_at = _utc_iso(inc["start"]) if inc.get("start") else None
            ended_at = _utc_iso(inc["end"]) if inc.get("end") else None
        except (ValueError, TypeError):
            skips["bad_timestamp"] += 1
            continue
        lists = {name: inc.get(name) if inc.get(name) is not None else [] for name in _LIST_FIELDS}
        event_ids = inc.get("event_ids")
        sequence, threat_intel = inc.get("sequence"), inc.get("threat_intel")
        if (any(not isinstance(v, list) for v in lists.values())
                or not isinstance(event_ids, list)
                or (sequence is not None and not isinstance(sequence, dict))
                or (threat_intel is not None and not isinstance(threat_intel, dict))):
            skips["bad_field_type"] += 1
            continue
        status = inc.get("status") if inc.get("status") in STATUSES else "OPEN"
        threat_level = _blank_to_none(inc.get("ip_threat_level"))
        seen.add(external_id)
        rows.append({
            "external_id": external_id, "severity": severity, "status": status, "title": title,
            "asset": inc.get("asset"), "source_ip": inc.get("ip"),
            "analyst": _blank_to_none(inc.get("analyst")) or "Unassigned",
            "vector": inc.get("vector"), "confidence": confidence, "impact": impact,
            "risk_score": risk_score, "started_at": started_at, "ended_at": ended_at,
            "event_count": event_count, "amount_total": amount_total,
            "ip_threat_level": None if threat_level in (None, "None") else threat_level,
            "users": lists["users"], "ips": lists["ips"], "ip_details": lists["ip_details"],
            "reasons": lists["reasons"], "sequence": sequence, "timeline": lists["timeline"],
            "detected_by": inc.get("detected_by"), "ml_severity": inc.get("ml_severity"),
            "rule_severity": inc.get("rule_severity"), "rule_hits": lists["rule_hits"],
            "ml_event_ids": lists["ml_event_ids"], "rule_mitre": lists["rule_mitre"],
            "threat_actor": inc.get("threat_actor"), "threat_intel": threat_intel,
            "ai_summary": inc.get("ai_summary"),
            "raw": inc,        # the whole original object; its own pipeline_run_id key lives only here
        })
        for event_id in dict.fromkeys(e for e in event_ids if isinstance(e, str) and e.strip()):
            pairs.append((external_id, event_id.strip()))
    return rows, pairs


def parse_rule_alerts(rows: list[dict], skips: Counter) -> list[dict]:
    out, seen = [], set()
    for row in rows:
        event_id = (row.get("event_id") or "").strip()
        rule_id = (row.get("rule_id") or "").strip()
        if not event_id or not rule_id:
            skips["missing_id"] += 1
            continue
        severity = (row.get("severity") or "").strip().lower()
        if severity not in SEVERITIES:
            skips["bad_severity"] += 1
            continue
        try:
            ts = _utc_iso(row.get("timestamp"))
        except (ValueError, TypeError):
            skips["bad_timestamp"] += 1
            continue
        if (event_id, rule_id) in seen:
            skips["duplicate_pair"] += 1
            continue
        seen.add((event_id, rule_id))
        out.append({"event_id": event_id, "rule_id": rule_id,
                    "rule_name": _blank_to_none(row.get("rule_name")),
                    "severity": severity, "ts": ts})
    return out


def parse_reports(items: list | None, fingerprint: str, incident_ids: set[str],
                  skips: Counter) -> list[dict]:
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict):
            skips["not_an_object"] += 1
            continue
        if item.get("pipeline_run_id") != fingerprint:
            skips["stale_run_id"] += 1
            continue
        external_id = item.get("id")
        if external_id not in incident_ids:
            skips["unknown_incident"] += 1
            continue
        if external_id in seen:
            skips["duplicate_id"] += 1
            continue
        source = item.get("source")
        if source not in REPORT_SOURCES:
            skips["bad_source"] += 1
            continue
        grounding = item.get("grounding")
        grounded = grounding.get("grounded") if isinstance(grounding, dict) else None
        unverified = grounding.get("unverified") if isinstance(grounding, dict) else None
        unverified = [] if unverified is None else unverified
        if not isinstance(grounded, bool) or not isinstance(unverified, list):
            skips["bad_grounding"] += 1
            continue
        seen.add(external_id)
        out.append({"external_id": external_id, "summary": item.get("summary"),
                    "five_ws": item.get("five_ws"), "mitre": item.get("mitre") or [],
                    "containment_actions": item.get("containment_actions") or [],
                    "investigation_steps": item.get("investigation_steps") or [],
                    "source": source, "grounded": grounded, "unverified": unverified,
                    "raw": item})
    return out


def _checks(data: dict) -> dict[str, bool | None]:
    incidents = [i for i in data["incidents"] if isinstance(i, dict)]
    stats = data["dashboard"].get("stats") or {}
    funnel = stats.get("event_funnel") or {}
    checks: dict[str, bool | None] = {"run_id_consistent": True}
    checks["pipeline_run_incident_count_matches"] = (
        data["pipeline_run"].get("incidents") == len(incidents)
        if "incidents" in data["pipeline_run"] else None)
    checks["event_count_matches_event_ids"] = all(
        i.get("event_count") == len(i.get("event_ids") or []) for i in incidents)
    try:
        checks["funnel_adds_up"] = (
            funnel["flagged_by_model"] + funnel["flagged_by_rules_only"] == funnel["grouped"]
            == funnel["in_incidents"] + funnel["in_watchlist"]
            and funnel["in_incidents"] == sum(i.get("event_count") or 0 for i in incidents)
            == stats.get("anomalous_events"))
    except (KeyError, TypeError):
        checks["funnel_adds_up"] = None
    by_sev = data["dashboard"].get("by_severity")
    checks["severity_matches_dashboard"] = (
        {k: v for k, v in Counter(str(i.get("sev")).lower() for i in incidents).items()}
        == {k: v for k, v in by_sev.items() if v} if isinstance(by_sev, dict) else None)
    detected = stats.get("detected_by")
    checks["detected_by_matches_dashboard"] = (
        dict(Counter(i.get("detected_by") for i in incidents)) == detected
        if isinstance(detected, dict) else None)
    return checks


def parse_outputs(output_dir: Path) -> ParsedOutputs:
    data = read_outputs(output_dir)
    fingerprint = check_consistency(data["pipeline_run"], data["incidents"], data["dashboard"])
    skips = {t: Counter() for t in ("ml_results", "incidents", "incident_events",
                                    "rule_alerts", "reports")}
    ml_rows = parse_ml_results(data["auth"], data["txn"], skips["ml_results"])
    incident_rows, pairs = parse_incidents(data["incidents"], skips["incidents"])
    alerts = parse_rule_alerts(data["alerts"], skips["rule_alerts"])
    reports = parse_reports(data["reports"], fingerprint, {r["external_id"] for r in incident_rows},
                            skips["reports"])
    return ParsedOutputs(
        fingerprint=fingerprint, created_at=data["pipeline_run"].get("created_at"),
        ml_results=ml_rows, incidents=incident_rows, incident_pairs=pairs, rule_alerts=alerts,
        reports=reports, dashboard=data["dashboard"],
        rows_read={"ml_results": len(data["auth"]) + len(data["txn"]),
                   "incidents": len(data["incidents"]),
                   "incident_events": len(pairs),
                   "rule_alerts": len(data["alerts"]),
                   "reports": len(data["reports"] or [])},
        skips=skips, flagged_count=sum(1 for r in ml_rows if r["is_anomalous"]),
        reports_file_present=data["reports"] is not None, checks=_checks(data))


def _table(name: str, rows_read: int, rows_written: int, skips: Counter, seconds: float = 0.0) -> dict:
    return {"table": name, "rows_read": rows_read, "rows_written": rows_written,
            "rejected_count": sum(skips.values()), "rejected_samples": [],
            "skip_reasons": dict(skips), "duration_seconds": round(seconds, 3)}


def dry_parse(output_dir: Path) -> dict:
    """Counts per table, skips, fingerprint and consistency checks. No database."""
    p = parse_outputs(output_dir)
    skip = {t: dict(c) for t, c in p.skips.items() if c}
    tables = [_table("pipeline_runs", 1, 0, Counter())]
    for name in ("ml_results", "incidents", "incident_events", "rule_alerts", "reports"):
        tables.append(_table(name, p.rows_read[name], 0, p.skips[name]))
    tables.append(_table("dashboard_snapshots", 1, 0, Counter()))
    ready = {"ml_results": len(p.ml_results), "incidents": len(p.incidents),
             "incident_events": len(p.incident_pairs), "rule_alerts": len(p.rule_alerts),
             "reports": len(p.reports), "dashboard_snapshots": 1, "pipeline_runs": 1}
    return {"outcome": "dry_run", "fingerprint": p.fingerprint, "tables": tables, "ready": ready,
            "skips": skip, "flagged_count": p.flagged_count,
            "stale_reports": p.skips["reports"].get("stale_run_id", 0),
            "reports_file_present": p.reports_file_present, "checks": p.checks,
            "source_created_at": p.created_at}


# ---------------------------------------------------------------------------
# Part B: database
# ---------------------------------------------------------------------------
def _db():
    return database.get_admin_client()


def _paged_select(table: str, columns: str, order_col: str, **eq) -> list[dict]:
    out, start = [], 0
    while True:
        query = _db().table(table).select(columns)
        for key, value in eq.items():
            query = query.eq(key, value)
        data = query.order(order_col).range(start, start + PAGE_SIZE - 1).execute().data or []
        out.extend(data)
        if len(data) < PAGE_SIZE:
            return out
        start += PAGE_SIZE


def fetch_existing_event_ids() -> set[str]:
    return {r["event_id"] for r in _paged_select("events", "event_id", "event_id")}


def find_completed_run(fingerprint: str) -> dict | None:
    res = (_db().table("pipeline_runs").select("id,is_current")
           .eq("source_fingerprint", fingerprint).eq("status", "completed").limit(1).execute())
    return res.data[0] if res.data else None


def _count(table: str, **eq) -> int:
    query = _db().table(table).select("*", count="exact")
    for key, value in eq.items():
        query = query.eq(key, value)
    return query.limit(1).execute().count or 0


def _count_by_incident(table: str, incident_ids: list[str]) -> int:
    """incident_events and reports have no run column; count them through the run's incident uuids."""
    total = 0
    for i in range(0, len(incident_ids), IN_CHUNK):
        res = (_db().table(table).select("*", count="exact")
               .in_("incident_id", incident_ids[i:i + IN_CHUNK]).limit(1).execute())
        total += res.count or 0
    return total


def _upsert_chunks(table: str, rows: list[dict], on_conflict: str, size: int) -> int:
    written = 0
    for i in range(0, len(rows), size):
        written += ingestion._upsert_with_retry(table, rows[i:i + size], on_conflict)
    return written


def _is_missing_function(exc: Exception) -> bool:
    text = str(exc)
    return (str(getattr(exc, "code", "")) == "PGRST202" or "PGRST202" in text
            or "Could not find the function" in text)


def _fail_run(run_id: str | None, message: str) -> None:
    if not run_id:
        return
    try:
        (_db().table("pipeline_runs")
         .update({"status": "failed", "finished_at": datetime.now(timezone.utc).isoformat(),
                  "error_message": message}).eq("id", run_id).execute())
    except Exception as exc:  # noqa: BLE001
        log.error("could not mark run failed (%s)", type(exc).__name__)


def load(output_dir: Path, force: bool = False) -> dict:
    started = time.perf_counter()
    parsed = parse_outputs(output_dir)             # Missing/Inconsistent: raised before any write
    fingerprint = parsed.fingerprint

    step = "find_run"
    try:
        existing = find_completed_run(fingerprint)
    except Exception as exc:  # noqa: BLE001
        raise LoadError(f"{type(exc).__name__} at step {step}") from None

    if existing and not force:
        tables = [_table(t, parsed.rows_read.get(t, 1), 0, parsed.skips.get(t, Counter()))
                  for t in ("ml_results", "incidents", "incident_events", "rule_alerts", "reports")]
        return {"outcome": "already_loaded", "run_id": existing["id"], "fingerprint": fingerprint,
                "stale_reports": parsed.skips["reports"].get("stale_run_id", 0), "tables": tables,
                "duration_seconds": round(time.perf_counter() - started, 3)}

    created_new = existing is None
    run_id: str | None = None
    try:
        step = "create_run"
        if created_new:
            notes = f"source_created_at={parsed.created_at}" if parsed.created_at else None
            res = _db().table("pipeline_runs").insert(
                {"status": "running", "trigger": "api", "source_fingerprint": fingerprint,
                 "notes": notes}).execute()          # not retried: not idempotent
            run_id = str(res.data[0]["id"])
        else:
            run_id = str(existing["id"])

        step = "lookup_events"
        known = fetch_existing_event_ids()
        skips = {t: Counter(c) for t, c in parsed.skips.items()}

        ml_rows = []
        for r in parsed.ml_results:
            if r["event_id"] in known:
                ml_rows.append({**r, "pipeline_run_id": run_id})
            else:
                skips["ml_results"]["unknown_event_id"] += 1
        pairs = []
        for external_id, event_id in parsed.incident_pairs:
            if event_id in known:
                pairs.append((external_id, event_id))
            else:
                skips["incident_events"]["unknown_event_id"] += 1
        alerts = []
        for a in parsed.rule_alerts:
            if a["event_id"] in known:
                alerts.append(a)
            else:
                skips["rule_alerts"]["unknown_event_id"] += 1

        written: dict[str, int] = {}
        seconds: dict[str, float] = {}

        def timed(table: str, fn):
            t0 = time.perf_counter()
            written[table] = fn()
            seconds[table] = time.perf_counter() - t0

        step = "ml_results"
        timed("ml_results", lambda: _upsert_chunks(
            "ml_results", ml_rows, "pipeline_run_id,event_id", ML_CHUNK))

        step = "incidents"
        # Force into an existing run: incidents that already exist keep the status and analyst
        # people set in the app; the file only supplies them for incidents that are new.
        carried = {}
        if not created_new:
            carried = {r["external_id"]: r for r in _paged_select(
                "incidents", "external_id,status,analyst", "external_id", pipeline_run_id=run_id)}
        incident_rows = []
        for r in parsed.incidents:
            row = {**r, "pipeline_run_id": run_id}
            old = carried.get(r["external_id"])
            if old and old.get("status") in STATUSES:
                row["status"] = old["status"]
            if old and old.get("analyst"):
                row["analyst"] = old["analyst"]
            incident_rows.append(row)
        timed("incidents", lambda: _upsert_chunks(
            "incidents", incident_rows, "pipeline_run_id,external_id", INCIDENT_CHUNK))

        step = "incident_uuids"
        id_map = {r["external_id"]: r["id"]
                  for r in _paged_select("incidents", "id,external_id", "external_id",
                                         pipeline_run_id=run_id)}

        step = "incident_events"
        pair_rows = []
        for external_id, event_id in pairs:
            if external_id not in id_map:
                raise KeyError("incident uuid missing")
            pair_rows.append({"incident_id": id_map[external_id], "event_id": event_id})
        timed("incident_events", lambda: _upsert_chunks(
            "incident_events", pair_rows, "incident_id,event_id", ML_CHUNK))

        step = "rule_alerts"
        timed("rule_alerts", lambda: _upsert_chunks(
            "rule_alerts", alerts, "event_id,rule_id", ML_CHUNK))

        step = "reports"
        report_rows = []
        for r in parsed.reports:
            row = {k: v for k, v in r.items() if k != "external_id"}
            report_rows.append({**row, "incident_id": id_map[r["external_id"]]})
        timed("reports", lambda: _upsert_chunks("reports", report_rows, "incident_id", ML_CHUNK))

        step = "dashboard_snapshots"
        timed("dashboard_snapshots", lambda: _upsert_chunks(
            "dashboard_snapshots", [{"pipeline_run_id": run_id, "payload": parsed.dashboard}],
            "pipeline_run_id", 1))

        step = "verify"
        expected = {"ml_results": len(ml_rows), "incidents": len(incident_rows),
                    "incident_events": len(pair_rows), "rule_alerts": len(alerts),
                    "reports": len(report_rows), "dashboard_snapshots": 1}
        for table, want in expected.items():
            if written[table] != want:
                raise ValueError("written count mismatch")
        for table in ("ml_results", "incidents", "dashboard_snapshots"):
            if _count(table, pipeline_run_id=run_id) != expected[table]:
                raise ValueError("database count mismatch")
        for table in ("incident_events", "reports"):
            if _count_by_incident(table, list(id_map.values())) != expected[table]:
                raise ValueError("database count mismatch")

        if created_new:
            step = "complete_run"
            (_db().table("pipeline_runs")
             .update({"status": "completed",
                      "finished_at": datetime.now(timezone.utc).isoformat(),
                      "events_scored": parsed.rows_read["ml_results"],
                      "incident_count": len(incident_rows)})
             .eq("id", run_id).execute())
            step = "set_current_run"
            try:
                _db().rpc("set_current_run", {"run_id": run_id}).execute()   # not retried
            except Exception as exc:  # noqa: BLE001
                if _is_missing_function(exc):
                    raise LoadError("set_current_run missing: run migration 004", run_id) from None
                raise
    except LoadError as exc:
        _fail_run(run_id if created_new else None, exc.public_message)
        raise
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__} at step {step}"
        log.error("pipeline load failed: %s", message)
        _fail_run(run_id if created_new else None, message)
        raise LoadError(message, run_id) from None

    tables = [_table("pipeline_runs", 1, 1 if created_new else 0, Counter())]
    for name in ("ml_results", "incidents", "incident_events", "rule_alerts", "reports"):
        tables.append(_table(name, parsed.rows_read[name], written[name], skips[name], seconds[name]))
    tables.append(_table("dashboard_snapshots", 1, written["dashboard_snapshots"], Counter(),
                         seconds["dashboard_snapshots"]))
    return {"outcome": "loaded" if created_new else "reloaded", "run_id": run_id,
            "fingerprint": fingerprint, "stale_reports": skips["reports"].get("stale_run_id", 0),
            "tables": tables, "duration_seconds": round(time.perf_counter() - started, 3)}
