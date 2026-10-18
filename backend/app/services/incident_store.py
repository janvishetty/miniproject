"""Read/update queries for the dashboard, incidents, reports and Copilot data.

Everything reads the CURRENT pipeline run (pipeline_runs.is_current); with no current run the
routes get 409 "no pipeline run loaded yet". All filters go through the Supabase client's
typed methods (eq / in_ / ilike): no PostgREST filter string is ever built from user input.
Search runs one ilike per column and unions the ids in Python (no or_()).
Logs and errors carry nothing but codes; row values never reach them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app import audit, database
from app.security import load_profile

PAGE = 1000
IN_CHUNK = 50
SEARCH_CAP = 300
SEARCH_COLUMNS = ("title", "asset", "source_ip", "external_id", "analyst", "vector")
SORT_COLUMNS = ("risk_score", "started_at", "confidence")
SEVERITIES = ("critical", "high", "medium", "low")
STATUSES = ("OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED")
ANALYST_STATUSES = ("OPEN", "INVESTIGATING", "CONTAINED")
VECTORS = ("Account Takeover", "Credential Stuffing", "Brute Force", "Suspicious Login",
           "Transaction Anomaly")
EXTERNAL_ID_PATTERN = r"^INC-\d{4}-\d{4}$"
SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}

LIST_COLUMNS = ("id,external_id,severity,status,title,asset,source_ip,analyst,vector,confidence,"
                "impact,risk_score,started_at,created:raw->>created")
DETAIL_COLUMNS = (LIST_COLUMNS + ",ended_at,event_count,amount_total,ip_threat_level,users,ips,"
                  "ip_details,reasons,sequence,timeline,detected_by,ml_severity,rule_severity,"
                  "rule_hits,rule_mitre,threat_actor,threat_intel,ai_summary")
EVENT_COLUMNS = ("event_id,event_kind,source_type,ts,user_id,ip_address,device_id,location,status,"
                 "mfa_status,endpoint,http_method,status_code,amount,merchant")
REPORT_COLUMNS = ("incident_id,summary,five_ws,mitre,containment_actions,investigation_steps,"
                  "source,grounded,unverified,created_at")

_LIKE_ESCAPE = str.maketrans({c: "\\" + c for c in '\\%_*,()"'})


def _db():
    return database.get_admin_client()


# ------------------------------- run + generic helpers -------------------------------
def current_run() -> dict:
    res = (_db().table("pipeline_runs")
           .select("id,source_fingerprint,started_at,finished_at,status")
           .eq("is_current", True).limit(1).execute())
    if not res.data:
        raise HTTPException(status_code=409, detail="no pipeline run loaded yet")
    return res.data[0]


def paged(table: str, columns: str, order_col: str, **eq) -> list[dict]:
    out, start = [], 0
    while True:
        query = _db().table(table).select(columns)
        for key, value in eq.items():
            query = query.eq(key, value)
        data = query.order(order_col).range(start, start + PAGE - 1).execute().data or []
        out.extend(data)
        if len(data) < PAGE:
            return out
        start += PAGE


def _in_chunks(table: str, columns: str, column: str, values: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(values), IN_CHUNK):
        out.extend(_db().table(table).select(columns)
                   .in_(column, values[i:i + IN_CHUNK]).execute().data or [])
    return out


def escape_like(text: str) -> str:
    """Backslash-escape \\ % _ * , ( ) " so user text can only ever match itself."""
    return text.translate(_LIKE_ESCAPE)


def _hhmm(value) -> str | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%H:%M")


def to_item(row: dict) -> dict:
    """The frontend mock keys (id, sev, ip, created, ...) plus started_at and risk_score."""
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    created = row.get("created") or raw.get("created") or _hhmm(row.get("started_at"))
    return {"id": row["external_id"], "sev": row["severity"], "status": row["status"],
            "title": row["title"], "asset": row.get("asset"), "ip": row.get("source_ip"),
            "analyst": row.get("analyst"), "vector": row.get("vector"), "created": created,
            "confidence": row.get("confidence"), "impact": row.get("impact"),
            "started_at": row.get("started_at"), "risk_score": row.get("risk_score")}


def _sort_rows(rows: list[dict], sort: str, desc: bool) -> list[dict]:
    rows = sorted(rows, key=lambda r: r["external_id"])
    present = sorted((r for r in rows if r.get(sort) is not None), key=lambda r: r[sort], reverse=desc)
    return present + [r for r in rows if r.get(sort) is None]


# ----------------------------------- dashboard -----------------------------------
def dashboard(run: dict) -> dict:
    rows = paged("incidents", LIST_COLUMNS, "external_id", pipeline_run_id=run["id"])
    active = [r for r in rows if r["status"] != "RESOLVED"]
    weights = sum(SEVERITY_WEIGHT[r["severity"]] for r in active)
    risk = sum(float(r.get("risk_score") or 0) * SEVERITY_WEIGHT[r["severity"]] for r in active)
    by_type: dict[str, int] = {}
    for r in active:
        by_type[r.get("vector") or "Unknown"] = by_type.get(r.get("vector") or "Unknown", 0) + 1
    snap = (_db().table("dashboard_snapshots").select("payload")
            .eq("pipeline_run_id", run["id"]).limit(1).execute().data or [])
    payload = snap[0]["payload"] if snap and isinstance(snap[0].get("payload"), dict) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    recent = _sort_rows(rows, "started_at", True)[:10]
    return {
        "run": {"id": run["id"], "fingerprint": run.get("source_fingerprint"),
                "loaded_at": run.get("finished_at") or run.get("started_at")},
        "active_incidents": len(active),
        "critical_open": sum(1 for r in rows if r["severity"] == "critical"
                             and r["status"] in ("OPEN", "INVESTIGATING")),
        "platform_risk_score": int(round(risk / max(weights, 1))),
        "by_severity": {s: sum(1 for r in active if r["severity"] == s) for s in SEVERITIES},
        "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
        "by_type": by_type,
        "recent": [{"id": r["external_id"], "sev": r["severity"], "title": r["title"],
                    "time": to_item(r)["created"], "status": r["status"],
                    "started_at": r.get("started_at")} for r in recent],
        "events_analysed": stats.get("events_analysed"),
        "events_analysed_sub": stats.get("events_analysed_sub"),
        "anomalous_events": stats.get("anomalous_events"),
        "event_funnel": stats.get("event_funnel"),
        "amount_at_risk": stats.get("amount_at_risk"),
        "risk_map_title": payload.get("risk_map_title"),
        "risk_map": payload.get("risk_map"),
        "live_events": payload.get("live_events"),
        "model": payload.get("model"),
        "avg_response_time": None,
    }


# ----------------------------------- incidents -----------------------------------
def _filtered(query, run_id: str, severity, status, vector):
    query = query.eq("pipeline_run_id", run_id)
    for column, value in (("severity", severity), ("status", status), ("vector", vector)):
        if value is not None:
            query = query.eq(column, value)
    return query


def list_incidents(run_id: str, severity, status, vector, search, sort: str, desc: bool,
                   page: int, page_size: int) -> dict:
    if search:
        pattern = f"%{escape_like(search)}%"
        ids: set[str] = set()
        for column in SEARCH_COLUMNS:
            query = _filtered(_db().table("incidents").select("id"), run_id, severity, status, vector)
            ids |= {r["id"] for r in query.ilike(column, pattern).limit(SEARCH_CAP + 1).execute().data or []}
        if len(ids) > SEARCH_CAP:
            raise HTTPException(status_code=422, detail="search too broad, add a filter")
        rows = _sort_rows(_in_chunks("incidents", LIST_COLUMNS, "id", sorted(ids)), sort, desc)
        total = len(rows)
        rows = rows[(page - 1) * page_size: page * page_size]
    else:
        query = _filtered(_db().table("incidents").select(LIST_COLUMNS, count="exact"),
                          run_id, severity, status, vector)
        start = (page - 1) * page_size
        res = (query.order(sort, desc=desc, nullsfirst=False).order("external_id")
               .range(start, start + page_size - 1).execute())
        rows, total = res.data or [], res.count or 0
    return {"items": [to_item(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def get_incident_row(run_id: str, external_id: str, columns: str = DETAIL_COLUMNS) -> dict:
    res = (_db().table("incidents").select(columns).eq("pipeline_run_id", run_id)
           .eq("external_id", external_id).limit(1).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    return res.data[0]


def incident_event_ids(incident_uuid: str) -> list[str]:
    return [r["event_id"] for r in paged("incident_events", "event_id", "event_id",
                                         incident_id=incident_uuid)]


def report_row(incident_uuid: str) -> dict | None:
    res = (_db().table("reports").select(REPORT_COLUMNS).eq("incident_id", incident_uuid)
           .limit(1).execute())
    return res.data[0] if res.data else None


def incident_detail(run_id: str, external_id: str) -> dict:
    row = get_incident_row(run_id, external_id)
    item = to_item(row)
    for key in ("ended_at", "event_count", "amount_total", "ip_threat_level", "users", "ips",
                "ip_details", "reasons", "sequence", "timeline", "detected_by", "ml_severity",
                "rule_severity", "rule_hits", "rule_mitre", "threat_actor", "threat_intel",
                "ai_summary"):
        item[key] = row.get(key)
    item["event_ids"] = incident_event_ids(row["id"])
    report = report_row(row["id"])
    item["report"] = (None if report is None else
                      {k: report.get(k) for k in ("summary", "source", "grounded", "created_at")})
    return item


def incident_events(run_id: str, external_id: str, page: int, page_size: int) -> dict:
    row = get_incident_row(run_id, external_id, "id,external_id")
    ids = incident_event_ids(row["id"])
    events = sorted(_in_chunks("events", EVENT_COLUMNS, "event_id", ids),
                    key=lambda e: (e.get("ts") or "", e["event_id"]))
    start = (page - 1) * page_size
    return {"items": events[start:start + page_size], "total": len(events),
            "page": page, "page_size": page_size}


def update_incident(run_id: str, external_id: str, user, fields: set[str], status, analyst_id) -> dict:
    """Role rules are enforced here (not in the route) so they cannot be skipped."""
    privileged = user.role in ("manager", "admin")
    if "status" in fields:
        if status is None:
            raise HTTPException(status_code=422, detail="status cannot be null")
        if status == "RESOLVED" and not privileged:
            raise HTTPException(status_code=403, detail="Only a manager or admin can resolve an incident")
    new_analyst = None
    if "analyst_id" in fields:
        if analyst_id is None:
            if not privileged:
                raise HTTPException(status_code=403, detail="Only a manager or admin can unassign an incident")
            new_analyst = "Unassigned"
        else:
            if not privileged and str(analyst_id) != user.id:
                raise HTTPException(status_code=403, detail="You can only assign an incident to yourself")
            profile = load_profile(str(analyst_id))
            if profile is None:
                raise HTTPException(status_code=422, detail="Unknown analyst_id")
            new_analyst = profile.get("full_name") or profile.get("username") or "Unassigned"
    row = get_incident_row(run_id, external_id, "id,external_id,status,analyst")
    before = {"status": row["status"], "analyst": row["analyst"]}      # copy before the update
    changes: dict = {}
    if "status" in fields:
        changes["status"] = status
    if new_analyst is not None:
        changes["analyst"] = new_analyst
    if changes:
        _db().table("incidents").update(changes).eq("id", row["id"]).execute()
    audit.write(user.id, "incident.updated", "incident", external_id,
                {"pipeline_run_id": run_id,
                 "before": before, "after": {**before, **changes}})
    return to_item(get_incident_row(run_id, external_id, LIST_COLUMNS))


# ------------------------------------ reports ------------------------------------
def _run_incidents(run_id: str) -> list[dict]:
    return paged("incidents", "id,external_id,title,severity", "external_id", pipeline_run_id=run_id)


def _report_public(report: dict, incident: dict) -> dict:
    return {"id": incident["external_id"], "title": incident["title"], "sev": incident["severity"],
            **{k: report.get(k) for k in ("summary", "five_ws", "mitre", "containment_actions",
                                          "investigation_steps", "source", "grounded",
                                          "unverified", "created_at")}}


def list_reports(run_id: str, page: int, page_size: int) -> dict:
    by_uuid = {i["id"]: i for i in _run_incidents(run_id)}
    reports = _in_chunks("reports", REPORT_COLUMNS, "incident_id", sorted(by_uuid))
    reports.sort(key=lambda r: (r.get("created_at") or "", r["incident_id"]), reverse=True)
    start = (page - 1) * page_size
    items = [_report_public(r, by_uuid[r["incident_id"]]) for r in reports[start:start + page_size]]
    return {"items": items, "total": len(reports), "page": page, "page_size": page_size}


def get_report(run_id: str, external_id: str) -> dict:
    row = get_incident_row(run_id, external_id, "id,external_id,title,severity")
    report = report_row(row["id"])
    if report is None:
        raise HTTPException(status_code=404, detail="No report for this incident yet")
    return _report_public(report, row)


# ------------------------------------ copilot ------------------------------------
def copilot_data(run_id: str, include_resolved: bool) -> dict:
    """Current-run incidents as Janvi's raw objects overlaid with live status/analyst, plus the
    stored reports ({incident id: report object}). This replaces copilot.load()."""
    rows = paged("incidents", "id,external_id,status,analyst,raw", "external_id", pipeline_run_id=run_id)
    incidents, by_uuid = [], {}
    for r in rows:
        if not isinstance(r.get("raw"), dict) or (not include_resolved and r["status"] == "RESOLVED"):
            continue
        incidents.append({**r["raw"], "status": r["status"], "analyst": r["analyst"]})
        by_uuid[r["id"]] = r["external_id"]
    reports = {}
    for rep in _in_chunks("reports", "incident_id,raw", "incident_id", sorted(by_uuid)):
        if isinstance(rep.get("raw"), dict):
            reports[by_uuid[rep["incident_id"]]] = rep["raw"]
    return {"incidents": incidents, "reports": reports}

