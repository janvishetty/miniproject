"""/admin/pipeline/* routes: authorization matrix, 409s, jobs, audit, dry runs, failures.
Settings point at the synthetic fixtures and tiny fake scripts; nothing real is run."""
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import jobs
from app.services import ml_adapter, pipeline

FIX = Path(__file__).parent / "fixtures" / "ml_output"
EVENT_IDS = ["E900001", "E900002", "E900003", "T900001", "T900002"]
RUN_ID = "5b0e3a52-7a4e-4e5e-9a43-0d2d0c1f6a11"


def make_scripts(directory: Path, overrides: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ml_adapter.STEPS:
        (directory / name).write_text((overrides or {}).get(name, "pass\n"))
    return directory


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "out"
    shutil.copytree(FIX, out)
    scripts = make_scripts(tmp_path / "ml")
    settings = SimpleNamespace(ML_OUTPUT_DIR=out, ML_PYTHON=sys.executable, ML_STEP_TIMEOUT_SECONDS=30)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "ML_DIR", scripts)
    return SimpleNamespace(out=out, scripts=scripts, settings=settings, tmp=tmp_path)


def token(client, fake, role, n):
    body = {"name": "T", "username": f"user{n}", "email": f"u{n}@example.com",
            "password": "correct-horse-1", "position": "Security Analyst"}
    client.post("/auth/register", json=body)
    next(p for p in fake.tables["profiles"] if p["username"] == f"user{n}")["role"] = role
    r = client.post("/auth/login", json={"email": body["email"], "password": body["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def admin(client, fake):
    return token(client, fake, "admin", 1)


def wait_job(client, headers, job_id, timeout=10.0):
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(f"/admin/pipeline/jobs/{job_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {body}")


def seed_events(fake):
    fake.tables["events"] = [{"event_id": i} for i in EVENT_IDS]


def seed_run(fake, run_id=RUN_ID, started="2026-10-18T09:00:00+00:00"):
    fake.tables.setdefault("pipeline_runs", []).append(
        {"id": run_id, "status": "completed", "is_current": False, "trigger": "api",
         "started_at": started, "source_fingerprint": run_id[:12]})


def running_job(kind):
    jobs._jobs["in-flight"] = jobs.JobRecord(id="in-flight", kind=kind, params={}, actor_id="x")
    jobs._active_job_id = "in-flight"


# ------------------------------ authorization matrix ------------------------------
ROUTES = [
    ("POST", "/admin/pipeline/run?dry_run=true"),
    ("POST", "/admin/pipeline/load-existing?dry_run=true"),
    ("GET", "/admin/pipeline/runs"),
    ("GET", f"/admin/pipeline/runs/{RUN_ID}"),
    ("GET", "/admin/pipeline/jobs/known-job"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_authorization_matrix(client, fake, env, method, path):
    seed_run(fake)
    jobs._jobs["known-job"] = jobs.JobRecord(id="known-job", kind="pipeline_run", params={},
                                             actor_id="x", status="completed")
    assert client.request(method, path).status_code == 401                          # no token
    assert client.request(method, path, headers=token(client, fake, "analyst", 2)).status_code == 403
    assert client.request(method, path, headers=token(client, fake, "manager", 3)).status_code == 403
    r = client.request(method, path, headers=token(client, fake, "admin", 4))
    assert 200 <= r.status_code < 300, r.text


# --------------------------------------- 409 ---------------------------------------
@pytest.mark.parametrize("kind", ["all", "events", "pipeline_run"])
@pytest.mark.parametrize("path", ["/admin/pipeline/run", "/admin/pipeline/load-existing"])
def test_409_when_any_job_is_running(client, fake, env, kind, path):
    h = admin(client, fake)
    running_job(kind)
    r = client.post(path + "?dry_run=true", headers=h)
    assert r.status_code == 409 and "already running" in r.json()["error"]["message"]


def test_ingestion_is_blocked_while_a_pipeline_job_runs(client, fake, env):
    h = admin(client, fake)
    running_job("pipeline_run")
    assert client.post("/admin/ingest/reference?dry_run=true", headers=h).status_code == 409


def test_load_existing_missing_file_is_409_run_the_pipeline_first(client, fake, env):
    h = admin(client, fake)
    (env.out / "scored_auth.csv").unlink()
    r = client.post("/admin/pipeline/load-existing", headers=h)
    assert r.status_code == 409 and "run the pipeline first" in r.json()["error"]["message"]
    assert not fake.tables.get("pipeline_runs")


def test_load_existing_inconsistent_run_id_is_409_and_writes_nothing(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    data = json.loads((env.out / "dashboard.json").read_text())
    data["pipeline_run_id"] = "ffffffffffff"
    (env.out / "dashboard.json").write_text(json.dumps(data))
    r = client.post("/admin/pipeline/load-existing", headers=h)
    assert r.status_code == 409 and "pipeline_run_id differs" in r.json()["error"]["message"]
    assert not fake.tables.get("pipeline_runs") and not fake.tables.get("ml_results")


# ------------------------------------ load-existing ------------------------------------
def test_load_existing_loads_and_audits_counts_only(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    started = client.post("/admin/pipeline/load-existing", headers=h)
    assert started.status_code == 200 and started.json()["status"] == "running"
    body = wait_job(client, h, started.json()["job_id"])
    assert body["status"] == "completed", body
    report = body["report"]
    assert report["outcome"] == "loaded"
    tables = {t["table"]: t for t in report["tables"]}
    assert set(tables["ml_results"]) >= {"table", "rows_read", "rows_written", "rejected_count"}
    assert tables["ml_results"]["rows_written"] == 5 and tables["incident_events"]["rows_written"] == 3
    assert fake.tables["pipeline_runs"][0]["is_current"] is True

    actions = [a["action"] for a in fake.tables["audit_log"] if a["action"].startswith("pipeline.")]
    assert actions == ["pipeline.job_started", "pipeline.job_finished"]
    finished = next(a for a in fake.tables["audit_log"] if a["action"] == "pipeline.job_finished")
    assert finished["details"]["status"] == "completed" and finished["details"]["outcome"] == "loaded"
    counts = {t["table"]: t for t in finished["details"]["tables"]}
    assert counts["ml_results"] == {"table": "ml_results", "rows_read": 5, "rows_written": 5,
                                    "rejected_count": 0}
    blob = str(fake.tables["audit_log"])
    for value in ("E900001", "T900001", "U9001", "10.0.0.1", "INC-2026-9001", "Testville"):
        assert value not in blob


def test_second_load_of_same_run_says_already_loaded(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    first = wait_job(client, h, client.post("/admin/pipeline/load-existing", headers=h).json()["job_id"])
    second = wait_job(client, h, client.post("/admin/pipeline/load-existing", headers=h).json()["job_id"])
    assert second["report"]["outcome"] == "already_loaded"
    assert second["report"]["run_id"] == first["report"]["run_id"]
    assert len(fake.tables["pipeline_runs"]) == 1


def test_force_reloads_into_the_same_run(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    first = wait_job(client, h, client.post("/admin/pipeline/load-existing", headers=h).json()["job_id"])
    forced = wait_job(client, h, client.post("/admin/pipeline/load-existing?force=true",
                                             headers=h).json()["job_id"])
    assert forced["report"]["outcome"] == "reloaded"
    assert forced["report"]["run_id"] == first["report"]["run_id"]
    assert len(fake.tables["pipeline_runs"]) == 1 and len(fake.rpc_calls) == 1


def test_load_existing_dry_run_writes_nothing(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    body = wait_job(client, h, client.post("/admin/pipeline/load-existing?dry_run=true",
                                           headers=h).json()["job_id"])
    assert body["status"] == "completed" and body["report"]["outcome"] == "dry_run"
    assert body["report"]["fingerprint"] == "abc123def456" and body["report"]["flagged_count"] == 4
    assert all(t["rows_written"] == 0 for t in body["report"]["tables"])
    assert not fake.tables.get("pipeline_runs") and not fake.tables.get("ml_results")
    assert fake.rpc_calls == []


def test_failed_load_marks_job_failed_with_safe_message(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    fake.fail_rpc = "missing"
    body = wait_job(client, h, client.post("/admin/pipeline/load-existing", headers=h).json()["job_id"])
    assert body["status"] == "failed" and body["error"] == "set_current_run missing: run migration 004"
    finished = next(a for a in fake.tables["audit_log"] if a["action"] == "pipeline.job_finished")
    assert finished["details"]["status"] == "failed"


# ------------------------------------------- run -------------------------------------------
def test_run_dry_run_executes_scripts_and_dry_parses_only(client, fake, env):
    h = admin(client, fake)
    body = wait_job(client, h, client.post("/admin/pipeline/run?dry_run=true", headers=h).json()["job_id"])
    assert body["status"] == "completed", body
    assert [s["name"] for s in body["report"]["steps"]] == list(ml_adapter.STEPS)
    assert all(s["exit_code"] == 0 for s in body["report"]["steps"])
    assert body["report"]["outcome"] == "dry_run"
    assert not fake.tables.get("pipeline_runs")


def test_run_loads_after_scripts_succeed(client, fake, env):
    h = admin(client, fake)
    seed_events(fake)
    body = wait_job(client, h, client.post("/admin/pipeline/run", headers=h).json()["job_id"])
    assert body["status"] == "completed" and body["report"]["outcome"] == "loaded"
    assert len(body["report"]["steps"]) == 5
    finished = next(a for a in fake.tables["audit_log"] if a["action"] == "pipeline.job_finished")
    assert [s["exit_code"] for s in finished["details"]["steps"]] == [0] * 5
    assert "stderr_tail" not in str(finished)


def test_run_failing_script_stops_chain_and_loads_nothing(client, fake, env):
    h = admin(client, fake)
    make_scripts(env.scripts, {"features.py": "import sys\nsys.stderr.write('boom\\n')\nsys.exit(1)\n"})
    body = wait_job(client, h, client.post("/admin/pipeline/run", headers=h).json()["job_id"])
    assert body["status"] == "failed"
    assert body["error"] == "pipeline step features.py failed (exit code 1)"
    assert [s["name"] for s in body["report"]["steps"]] == ["preprocess.py", "features.py"]
    assert body["report"]["steps"][-1]["stderr_tail"] == ["boom"]
    assert not fake.tables.get("pipeline_runs")


def test_run_with_relative_interpreter_fails_without_running_anything(client, fake, env):
    h = admin(client, fake)
    env.settings.ML_PYTHON = "python3"
    body = wait_job(client, h, client.post("/admin/pipeline/run", headers=h).json()["job_id"])
    assert body["status"] == "failed" and "absolute path" in body["error"]
    assert not fake.tables.get("pipeline_runs")


def test_script_stdout_never_reaches_job_record_or_audit(client, fake, env):
    h = admin(client, fake)
    secret = "STDOUT-SECRET-U0001-10.0.0.9"
    make_scripts(env.scripts, {"model.py": f"print('{secret}')\n"})
    body = wait_job(client, h, client.post("/admin/pipeline/run?dry_run=true",
                                           headers=h).json()["job_id"])
    assert body["status"] == "completed"
    assert secret not in json.dumps(body) and secret not in str(fake.tables["audit_log"])


# ------------------------------------------- runs -------------------------------------------
def test_runs_are_paginated_newest_first(client, fake, env):
    h = admin(client, fake)
    for i, ts in enumerate(["2026-10-16", "2026-10-18", "2026-10-17"]):
        seed_run(fake, run_id=f"00000000-0000-4000-8000-00000000000{i}", started=ts)
    page1 = client.get("/admin/pipeline/runs?limit=2", headers=h).json()
    assert page1["total"] == 3 and page1["limit"] == 2 and page1["offset"] == 0
    assert [r["started_at"] for r in page1["items"]] == ["2026-10-18", "2026-10-17"]
    page2 = client.get("/admin/pipeline/runs?limit=2&offset=2", headers=h).json()
    assert [r["started_at"] for r in page2["items"]] == ["2026-10-16"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_runs_pagination_bounds(client, fake, env, query):
    h = admin(client, fake)
    assert client.get(f"/admin/pipeline/runs?{query}", headers=h).status_code == 422


def test_get_run_validates_uuid_and_404s(client, fake, env):
    h = admin(client, fake)
    seed_run(fake)
    assert client.get("/admin/pipeline/runs/not-a-uuid", headers=h).status_code == 422
    assert client.get("/admin/pipeline/runs/00000000-0000-4000-8000-000000000099",
                      headers=h).status_code == 404
    ok = client.get(f"/admin/pipeline/runs/{RUN_ID}", headers=h)
    assert ok.status_code == 200 and ok.json()["id"] == RUN_ID and ok.json()["status"] == "completed"


def test_job_route_404s_for_unknown_and_non_pipeline_jobs(client, fake, env):
    h = admin(client, fake)
    assert client.get("/admin/pipeline/jobs/nope", headers=h).status_code == 404
    jobs._jobs["ing"] = jobs.JobRecord(id="ing", kind="all", params={}, actor_id="x")
    assert client.get("/admin/pipeline/jobs/ing", headers=h).status_code == 404
