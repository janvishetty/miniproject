import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.routers import ingest as ingest_router
from app.services import ingestion, normalize

FIXTURES = Path(__file__).parent / "fixtures" / "data"


@pytest.fixture(autouse=True)
def _use_fixture_data_dir(monkeypatch):
    """Ingestion routes/services must never read the real data/ folder in tests."""
    monkeypatch.setattr(ingestion, "get_settings", lambda: SimpleNamespace(DATA_DIR=FIXTURES))
    yield


@pytest.fixture(autouse=True)
def _reset_job_state():
    ingest_router._jobs.clear()
    ingest_router._active_job_id = None
    yield
    ingest_router._jobs.clear()
    ingest_router._active_job_id = None


def _admin_token(client, fake, valid_body):
    client.post("/auth/register", json=valid_body)
    fake.tables["profiles"][0]["role"] = "admin"          # promoted, as in SQL
    r = client.post("/auth/login", json={"email": valid_body["email"], "password": valid_body["password"]})
    return r.json()["access_token"]


def _wait_for_job(client, headers, job_id, timeout=2.0):
    """The background task may finish just after the response, not inside it."""
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(f"/admin/ingest/jobs/{job_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish in time (last status: {body})")


def _analyst_token(client, valid_body):
    client.post("/auth/register", json=valid_body)
    r = client.post("/auth/login", json={"email": valid_body["email"], "password": valid_body["password"]})
    return r.json()["access_token"]


# ------------------------------------ allowlist ------------------------------------
@pytest.mark.parametrize("bad_name", [
    "ground_truth_events.csv",
    "ground_truth_scenarios.csv",
    "README.md",
    "../data/authentication_logs.csv",
    "secrets.csv",
])
def test_csv_path_rejects_anything_not_allowlisted(bad_name):
    with pytest.raises(ValueError):
        ingestion._csv_path(bad_name)


def test_csv_path_accepts_allowlisted_names():
    for name in ingestion.EVENT_FILES:
        assert ingestion._csv_path(name).name == name


# ----------------------------- authorization matrix -----------------------------
def test_ingest_reference_requires_admin(client, fake, valid_body):
    assert client.post("/admin/ingest/reference?dry_run=true").status_code == 401

    analyst_tok = _analyst_token(client, valid_body)
    r = client.post("/admin/ingest/reference?dry_run=true",
                    headers={"Authorization": f"Bearer {analyst_tok}"})
    assert r.status_code == 403


def test_ingest_reference_admin_200(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}
    r = client.post("/admin/ingest/reference?dry_run=true", headers=h)
    assert r.status_code == 200
    body = _wait_for_job(client, h, r.json()["job_id"])
    assert body["status"] == "completed"
    assert body["report"]["rows_written"] == 0           # dry run writes nothing
    assert body["report"]["rows_read"] == 6               # 3 user_devices + 3 threat_indicators


def test_ingest_events_requires_admin(client, fake, valid_body):
    assert client.post("/admin/ingest/events?dry_run=true").status_code == 401
    analyst_tok = _analyst_token(client, valid_body)
    r = client.post("/admin/ingest/events?dry_run=true",
                    headers={"Authorization": f"Bearer {analyst_tok}"})
    assert r.status_code == 403


def test_ingest_summary_requires_admin(client, fake, valid_body):
    assert client.get("/admin/ingest/summary").status_code == 401
    analyst_tok = _analyst_token(client, valid_body)
    r = client.get("/admin/ingest/summary", headers={"Authorization": f"Bearer {analyst_tok}"})
    assert r.status_code == 403


def test_get_job_requires_admin(client, fake, valid_body):
    assert client.get("/admin/ingest/jobs/nope").status_code == 401
    analyst_tok = _analyst_token(client, valid_body)
    r = client.get("/admin/ingest/jobs/nope", headers={"Authorization": f"Bearer {analyst_tok}"})
    assert r.status_code == 403


def test_get_unknown_job_404_for_admin(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    r = client.get("/admin/ingest/jobs/does-not-exist", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 404


# --------------------------------- bad source param ---------------------------------
def test_ingest_events_bad_source_422(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    r = client.post("/admin/ingest/events?source=bogus&dry_run=true",
                    headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 422


# ----------------------------------- one job at a time -----------------------------------
def test_second_job_returns_409_while_one_is_running(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}

    # Simulate a job already in flight (background tasks finish before TestClient
    # returns, so this models the state a real concurrent request would see).
    ingest_router._jobs["job-in-flight"] = ingest_router.JobRecord(
        id="job-in-flight", kind="all", params={}, actor_id="someone")
    ingest_router._active_job_id = "job-in-flight"

    r = client.post("/admin/ingest/reference?dry_run=true", headers=h)
    assert r.status_code == 409


# ------------------------------------- dry run report -------------------------------------
def test_dry_run_reports_rejects_and_counts(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}
    r = client.post("/admin/ingest/events?source=all&dry_run=true", headers=h)
    body = _wait_for_job(client, h, r.json()["job_id"])
    report = body["report"]
    # auth: 4 rows / 1 rejected, api: 2 rows / 1 rejected, transactions: 2 rows / 1 rejected
    assert report["rows_read"] == (4 + 2 + 2) * 2        # counted once for raw_events, once for events
    assert report["rejected_count"] == 3                # bad timestamp, bad status_code, bad amount
    assert report["rows_written"] == 0
    assert fake.tables.get("events", []) == []
    assert fake.tables.get("raw_events", []) == []


# ------------------------------------ idempotent rerun ------------------------------------
def test_full_ingest_rerun_is_idempotent(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}

    r1 = client.post("/admin/ingest/all", headers=h)
    body1 = _wait_for_job(client, h, r1.json()["job_id"])
    assert body1["status"] == "completed"
    counts_1 = {t: len(fake.tables.get(t, [])) for t in
               ("user_devices", "threat_indicators", "raw_events", "events")}
    assert counts_1["user_devices"] == 2                 # 3 rows - 1 bad Y/N value, rejected
    assert counts_1["threat_indicators"] == 2            # 3 rows - 1 bad threat_level, rejected
    assert counts_1["raw_events"] == 8                   # all rows have ids, even the bad ones
    assert counts_1["events"] == 5                       # 8 total rows - 3 rejected

    r2 = client.post("/admin/ingest/all", headers=h)
    body2 = _wait_for_job(client, h, r2.json()["job_id"])
    assert body2["status"] == "completed"
    counts_2 = {t: len(fake.tables.get(t, [])) for t in
               ("user_devices", "threat_indicators", "raw_events", "events")}
    assert counts_2 == counts_1                          # rerun did not duplicate anything


def test_ingest_job_logs_summary_to_audit_without_row_data(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}
    r = client.post("/admin/ingest/reference?dry_run=true", headers=h)
    _wait_for_job(client, h, r.json()["job_id"])
    entries = [a for a in fake.tables["audit_log"] if a["action"] == "ingest.job_finished"]
    assert len(entries) == 1
    assert entries[0]["details"]["status"] == "completed"
    blob = str(entries[0])
    assert "U0001" not in blob and "D00001" not in blob and "3633.85" not in blob


# ----------------------------------- summary endpoint -----------------------------------
def test_summary_reports_csv_and_db_counts(client, fake, valid_body):
    admin_tok = _admin_token(client, fake, valid_body)
    h = {"Authorization": f"Bearer {admin_tok}"}
    started = client.post("/admin/ingest/all", headers=h)
    _wait_for_job(client, h, started.json()["job_id"])
    r = client.get("/admin/ingest/summary", headers=h)
    body = r.json()
    assert body["user_devices"] == {"csv_rows": 3, "db_rows": 2}
    assert body["threat_indicators"] == {"csv_rows": 3, "db_rows": 2}
    assert body["raw_events"] == {"csv_rows": 8, "db_rows": 8}
    assert body["events"] == {"csv_rows": 8, "db_rows": 5}


# ------------------------------------- retry logic -------------------------------------
def test_upsert_retries_transient_failure_then_succeeds(fake, monkeypatch):
    monkeypatch.setattr(ingestion, "RETRY_BASE_DELAY", 0)   # don't actually sleep in tests
    fake.fail_upserts_times["threat_indicators"] = 1
    result = ingestion._ingest_reference_file(
        "threat_indicators.csv", "threat_indicators",
        normalize.normalize_threat_indicator_row, "ip_address", dry_run=False)
    assert result.rows_written == 2                      # 3 rows - 1 bad threat_level
    assert len(fake.tables["threat_indicators"]) == 2


def test_upsert_raises_ingestion_error_after_exhausting_retries(fake, monkeypatch):
    monkeypatch.setattr(ingestion, "RETRY_BASE_DELAY", 0)
    fake.fail_upserts_times["threat_indicators"] = 99
    with pytest.raises(ingestion.IngestionError):
        ingestion._upsert_with_retry("threat_indicators", [{"ip_address": "1.1.1.1"}], "ip_address")
