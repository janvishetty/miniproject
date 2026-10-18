"""Shared seed helpers for the Step 4 read-API tests (fake Supabase only)."""
import uuid

RUN_ID = "5b0e3a52-7a4e-4e5e-9a43-0d2d0c1f6a11"
FP = "abc123def456"
SEVS = ["critical", "high", "medium", "low"]
VECTORS = ["Account Takeover", "Brute Force", "Credential Stuffing", "Suspicious Login"]


def ext_id(n: int) -> str:
    return f"INC-2026-{n:04d}"


def make_incident(n: int, **over) -> dict:
    """One DB row for the incidents table, with the matching raw object."""
    sev = over.pop("severity", SEVS[n % 4])
    row = {
        "id": str(uuid.uuid4()), "pipeline_run_id": RUN_ID, "external_id": ext_id(9001 + n),
        "severity": sev, "status": "OPEN", "title": f"Incident number {n}",
        "asset": "payments-api /api/v1/transfer", "source_ip": f"10.0.0.{n % 250}",
        "analyst": "Unassigned", "vector": VECTORS[n % 4], "confidence": 90 - n % 10,
        "impact": 80, "risk_score": float(90 - 10 * (n % 4)),
        "started_at": f"2026-09-01T0{n % 10}:00:00+00:00", "ended_at": "2026-09-01T09:30:00+00:00",
        "event_count": 2, "amount_total": 100.0, "ip_threat_level": None,
        "users": ["U9001"], "ips": ["10.0.0.1"], "ip_details": [], "reasons": [],
        "sequence": {"transfers": []}, "timeline": [{"time": "00:00", "msg": "x"}],
        "detected_by": "ml", "ml_severity": sev, "rule_severity": None, "rule_hits": [],
        "rule_mitre": [], "threat_actor": "Unknown", "threat_intel": None, "ai_summary": "s",
    }
    row.update(over)
    row["raw"] = over.get("raw") or {
        "id": row["external_id"], "sev": sev, "status": "OPEN", "title": row["title"],
        "analyst": "Unassigned", "vector": row["vector"], "created": f"0{n % 10}:15",
        "risk_score": row["risk_score"], "amount_total": 100.0, "event_ids": ["E900001"],
        "pipeline_run_id": FP}
    return row


def seed_run(fake, n: int = 4, current: bool = True, incidents: list[dict] | None = None) -> list[dict]:
    fake.tables["pipeline_runs"] = [{
        "id": RUN_ID, "status": "completed", "is_current": current, "trigger": "api",
        "started_at": "2026-10-18T09:00:00+00:00", "finished_at": "2026-10-18T09:05:00+00:00",
        "source_fingerprint": FP}]
    rows = incidents if incidents is not None else [make_incident(i) for i in range(n)]
    fake.tables["incidents"] = rows
    fake.tables["dashboard_snapshots"] = [{
        "pipeline_run_id": RUN_ID, "payload": {
            "stats": {"events_analysed": 2000, "events_analysed_sub": "sub", "anomalous_events": 12,
                      "event_funnel": {"grouped": 5}, "amount_at_risk": 1234.5},
            "risk_map_title": "API Endpoint Risk Map", "risk_map": [{"id": "Login API"}],
            "live_events": [{"ts": "x"}], "model": {"detector": "iforest"}}}]
    fake.tables["events"] = [
        {"event_id": "E900002", "ts": "2026-09-01T00:00:30+00:00", "event_kind": "login", "user_id": "U9001"},
        {"event_id": "E900001", "ts": "2026-09-01T00:00:10+00:00", "event_kind": "login", "user_id": "U9001"},
        {"event_id": "T900001", "ts": "2026-09-01T00:00:10+00:00", "event_kind": "transaction"}]
    if rows:
        fake.tables["incident_events"] = [{"incident_id": rows[0]["id"], "event_id": e}
                                          for e in ("E900002", "E900001", "T900001")]
    fake.tables.setdefault("reports", [])
    return rows


def make_user(client, fake, role: str, n: int):
    """Registers a user, sets its role, logs in. Returns (headers, user_id, display name)."""
    body = {"name": f"Person {n}", "username": f"person{n}", "email": f"p{n}@example.com",
            "password": "correct-horse-1", "position": "Security Analyst"}
    client.post("/auth/register", json=body)
    profile = next(p for p in fake.tables["profiles"] if p["username"] == f"person{n}")
    profile["role"] = role
    r = client.post("/auth/login", json={"email": body["email"], "password": body["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, profile["id"], f"Person {n}"
