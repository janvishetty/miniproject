"""Auth error mapping (401 / 403 / 503) and the ingestion audit entry's counts."""
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import security
from app.services import ingestion
from conftest import FakeAuthError

FIXTURES = Path(__file__).parent / "fixtures" / "data"


def _headers(client, valid_body):
    client.post("/auth/register", json=valid_body)
    r = client.post("/auth/login", json={"email": valid_body["email"],
                                         "password": valid_body["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _raise_on_get_user(fake, exc):
    def boom(_token):
        raise exc
    fake.auth.get_user = boom


# ------------------------------- fake sanity -------------------------------
def test_fake_invalid_token_error_has_4xx_status(fake):
    with pytest.raises(FakeAuthError) as info:
        fake.auth.get_user("not-a-real-token")
    assert 400 <= info.value.status < 500


# ------------------------------------ 401 ------------------------------------
def test_missing_header_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_wrong_scheme_is_401(client):
    assert client.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_empty_bearer_token_is_401(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer "}).status_code == 401


def test_invalid_token_is_401(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_expired_token_4xx_from_supabase_is_401(client, fake):
    class Expired(FakeAuthError):
        status = 403
    _raise_on_get_user(fake, Expired("token is expired"))
    assert client.get("/auth/me", headers={"Authorization": "Bearer x"}).status_code == 401


def test_invalid_token_is_401_even_when_database_is_down(client, fake):
    fake.fail_tables["profiles"] = True
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# ------------------------------------ 503 ------------------------------------
def test_valid_token_but_profile_lookup_down_is_503(client, fake, valid_body):
    h = _headers(client, valid_body)
    fake.fail_tables["profiles"] = True
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 503
    assert r.json()["error"]["message"] == "Service temporarily unavailable"
    assert "simulated" not in r.text


def test_token_check_network_error_is_503(client, fake):
    _raise_on_get_user(fake, ConnectionError("network unreachable"))
    assert client.get("/auth/me", headers={"Authorization": "Bearer x"}).status_code == 503


def test_token_check_supabase_5xx_is_503(client, fake):
    class Upstream(FakeAuthError):
        status = 502
    _raise_on_get_user(fake, Upstream("bad gateway"))
    assert client.get("/auth/me", headers={"Authorization": "Bearer x"}).status_code == 503


def test_token_check_supabase_429_is_503_not_401(client, fake):
    class RateLimited(FakeAuthError):
        status = 429
    _raise_on_get_user(fake, RateLimited("rate limit exceeded"))
    r = client.get("/auth/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "unavailable"


def test_login_supabase_429_is_503_not_401(client, fake, valid_body):
    class RateLimited(FakeAuthError):
        status = 429

    def boom(_creds):
        raise RateLimited("rate limit exceeded")

    fake.auth.sign_in_with_password = boom
    r = client.post("/auth/login", json={"email": "a@example.com", "password": "whatever-1"})
    assert r.status_code == 503


# ------------------------------------ 403 ------------------------------------
def test_missing_profile_is_still_403(client, fake, valid_body):
    h = _headers(client, valid_body)
    fake.tables["profiles"].clear()
    assert client.get("/auth/me", headers=h).status_code == 403


def test_non_admin_is_still_403(client, valid_body):
    h = _headers(client, valid_body)
    assert client.get("/admin/ping", headers=h).status_code == 403


# ------------------------------------ logging ------------------------------------
def test_outage_logs_neither_token_nor_exception_message(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    token = "tok-super-secret-token-value"
    _raise_on_get_user(fake, ConnectionError("detail-with-sensitive-info"))
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503
    assert token not in caplog.text
    assert "detail-with-sensitive-info" not in caplog.text
    assert "ConnectionError" in caplog.text            # type only


def test_profile_outage_logs_no_exception_message(client, fake, valid_body, caplog):
    h = _headers(client, valid_body)
    caplog.set_level(logging.DEBUG)
    fake.fail_tables["profiles"] = True
    client.get("/auth/me", headers=h)
    assert "simulated database outage" not in caplog.text
    assert h["Authorization"].split()[1] not in caplog.text


# --------------------- ingestion audit entry carries counts ---------------------
def test_ingest_audit_entry_has_per_table_counts_only(client, fake, valid_body, monkeypatch):
    monkeypatch.setattr(ingestion, "get_settings", lambda: SimpleNamespace(DATA_DIR=FIXTURES))
    client.post("/auth/register", json=valid_body)
    fake.tables["profiles"][0]["role"] = "admin"
    tok = client.post("/auth/login", json={"email": valid_body["email"],
                                           "password": valid_body["password"]}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    job_id = client.post("/admin/ingest/all", headers=h).json()["job_id"]
    deadline = time.time() + 2
    while time.time() < deadline:
        if client.get(f"/admin/ingest/jobs/{job_id}", headers=h).json()["status"] != "running":
            break
        time.sleep(0.01)

    entry = next(a for a in fake.tables["audit_log"] if a["action"] == "ingest.job_finished")
    tables = {t["table"]: t for t in entry["details"]["tables"]}
    assert tables["user_devices"] == {"table": "user_devices", "rows_read": 3,
                                      "rows_written": 2, "rejected_count": 1}
    assert tables["raw_events"] == {"table": "raw_events", "rows_read": 8,
                                    "rows_written": 8, "rejected_count": 0}
    assert tables["events"] == {"table": "events", "rows_read": 8,
                                "rows_written": 5, "rejected_count": 3}
    for t in entry["details"]["tables"]:
        assert set(t) == {"table", "rows_read", "rows_written", "rejected_count"}
    blob = str(entry)
    assert "U0001" not in blob and "D00001" not in blob and "3633.85" not in blob
    assert "rejected_samples" not in blob
