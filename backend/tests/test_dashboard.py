"""GET /dashboard: auth matrix, 409, live counts, snapshot passthrough."""
import pytest

from soc_seed import make_incident, make_user, seed_run


def test_requires_login(client, fake):
    seed_run(fake)
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard", headers={"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_every_role_can_read(client, fake, role):
    seed_run(fake)
    headers, _, _ = make_user(client, fake, role, 1)
    assert client.get("/dashboard", headers=headers).status_code == 200


def test_no_current_run_is_409(client, fake):
    headers, _, _ = make_user(client, fake, "analyst", 1)
    r = client.get("/dashboard", headers=headers)
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "conflict", "message": "no pipeline run loaded yet"}}
    seed_run(fake, current=False)
    assert client.get("/dashboard", headers=headers).status_code == 409


def test_live_counts_and_snapshot(client, fake):
    rows = seed_run(fake, 4)           # critical 90, high 80, medium 70, low 60
    headers, _, _ = make_user(client, fake, "analyst", 1)
    body = client.get("/dashboard", headers=headers).json()
    assert body["active_incidents"] == 4 and body["critical_open"] == 1
    assert body["platform_risk_score"] == 80          # (90*4+80*3+70*2+60*1)/10
    assert body["by_severity"] == {"critical": 1, "high": 1, "medium": 1, "low": 1}
    assert body["by_status"] == {"OPEN": 4, "INVESTIGATING": 0, "CONTAINED": 0, "RESOLVED": 0}
    assert sum(body["by_type"].values()) == 4
    assert body["run"]["fingerprint"] == "abc123def456"
    assert body["events_analysed"] == 2000 and body["amount_at_risk"] == 1234.5
    assert body["risk_map_title"] == "API Endpoint Risk Map" and body["risk_map"] == [{"id": "Login API"}]
    assert body["live_events"] == [{"ts": "x"}] and body["model"] == {"detector": "iforest"}
    assert body["avg_response_time"] is None
    assert not any("trend" in k or "pts" in k for k in body)
    rows[0]["status"] = "RESOLVED"                    # resolved drops out of the open numbers
    body = client.get("/dashboard", headers=headers).json()
    assert body["active_incidents"] == 3 and body["critical_open"] == 0
    assert body["platform_risk_score"] == 73          # (80*3+70*2+60)/6 = 73.3
    assert body["by_status"]["RESOLVED"] == 1 and body["by_severity"]["critical"] == 0
    rows[1]["severity"], rows[1]["status"] = "critical", "CONTAINED"
    assert client.get("/dashboard", headers=headers).json()["critical_open"] == 0


def test_recent_is_ten_newest_with_live_status(client, fake):
    rows = [make_incident(i, started_at=f"2026-09-01T{i:02d}:00:00+00:00") for i in range(12)]
    seed_run(fake, incidents=rows)
    rows[11]["status"] = "INVESTIGATING"
    headers, _, _ = make_user(client, fake, "analyst", 1)
    recent = client.get("/dashboard", headers=headers).json()["recent"]
    assert len(recent) == 10 and recent[0]["id"] == rows[11]["external_id"]
    assert recent[0]["status"] == "INVESTIGATING"
    assert [r["started_at"] for r in recent] == sorted((r["started_at"] for r in recent), reverse=True)


def test_missing_snapshot_still_answers(client, fake):
    seed_run(fake, 2)
    fake.tables["dashboard_snapshots"] = []
    headers, _, _ = make_user(client, fake, "analyst", 1)
    body = client.get("/dashboard", headers=headers).json()
    assert body["active_incidents"] == 2 and body["risk_map"] is None
