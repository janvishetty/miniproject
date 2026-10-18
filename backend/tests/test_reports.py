"""Reports: list/get, report job (own lock, verified-only storage, error codes, visibility)."""
import pytest

from app import jobs, report_jobs
from app.services import ai_bridge
from soc_seed import FP, make_user, seed_run

ID0 = "INC-2026-9001"


@pytest.fixture(autouse=True)
def _reset_report_jobs():
    report_jobs.reset()
    yield
    report_jobs.reset()


@pytest.fixture
def ctx(client, fake):
    rows = seed_run(fake, 4)
    headers, uid, name = make_user(client, fake, "analyst", 1)
    return type("Ctx", (), {"c": client, "fake": fake, "rows": rows, "h": headers, "uid": uid})


def result(source="llm", grounded=True, run_id=FP, **over):
    out = {"id": ID0, "source": source, "pipeline_run_id": run_id, "summary": "Verified summary.",
           "five_ws": {"who": "U9001"}, "mitre": ["T1110 Brute Force"], "containment_actions": ["Lock"],
           "investigation_steps": ["Check"], "grounding": {"grounded": grounded, "unverified": [] if grounded else ["x"]},
           "attempts": [], "model": "m", "generation_seconds": 1.0}
    out.update(over)
    return out


def fake_bridge(monkeypatch, outcome):
    calls = []

    def run(mode, payload):
        calls.append((mode, payload))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(ai_bridge, "run_bridge", run)
    return calls


def post(ctx, headers=None, ext=ID0):
    return ctx.c.post(f"/incidents/{ext}/report", headers=headers or ctx.h)


def job(ctx, job_id, headers=None):
    return ctx.c.get(f"/reports/jobs/{job_id}", headers=headers or ctx.h)


# ------------------------------ auth / 409 / empty ------------------------------
ROUTES = [("GET", "/reports"), ("GET", f"/reports/{ID0}"), ("POST", f"/incidents/{ID0}/report"),
          ("GET", "/reports/jobs/abc")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_requires_login(ctx, method, path):
    assert ctx.c.request(method, path).status_code == 401
    assert ctx.c.request(method, path, headers={"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_every_role_can_use_reports(client, fake, role, monkeypatch):
    seed_run(fake)
    h, _, _ = make_user(client, fake, role, 1)
    fake_bridge(monkeypatch, result())
    assert client.get("/reports", headers=h).status_code == 200
    assert client.get(f"/reports/{ID0}", headers=h).status_code == 404       # allowed, just no report yet
    r = client.post(f"/incidents/{ID0}/report", headers=h)
    assert r.status_code == 202
    assert client.get(f"/reports/jobs/{r.json()['job_id']}", headers=h).status_code == 200


@pytest.mark.parametrize("method,path", [("GET", "/reports"), ("GET", f"/reports/{ID0}"),
                                         ("POST", f"/incidents/{ID0}/report")])
def test_no_current_run_is_409(client, fake, method, path):
    h, _, _ = make_user(client, fake, "admin", 1)
    assert client.request(method, path, headers=h).status_code == 409


def test_empty_list_is_200(ctx):
    r = ctx.c.get("/reports", headers=ctx.h)
    assert r.status_code == 200 and r.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_list_and_get(ctx):
    ctx.fake.tables["reports"] = [
        {"incident_id": ctx.rows[0]["id"], "summary": "A", "source": "llm", "grounded": True,
         "created_at": "2026-10-18T10:00:00+00:00", "mitre": [], "unverified": []},
        {"incident_id": ctx.rows[1]["id"], "summary": "B", "source": "template", "grounded": False,
         "created_at": "2026-10-18T11:00:00+00:00", "mitre": [], "unverified": ["x"]},
        {"incident_id": "someone-elses", "summary": "Z", "created_at": "2026-10-19T00:00:00+00:00"}]
    body = ctx.c.get("/reports?page_size=1", headers=ctx.h).json()
    assert body["total"] == 2 and [i["summary"] for i in body["items"]] == ["B"]       # newest first
    assert ctx.c.get("/reports?page=2&page_size=1", headers=ctx.h).json()["items"][0]["id"] == ID0
    one = ctx.c.get(f"/reports/{ID0}", headers=ctx.h).json()
    assert one["id"] == ID0 and one["summary"] == "A" and one["title"] == ctx.rows[0]["title"]
    miss = ctx.c.get("/reports/INC-2026-9002x", headers=ctx.h)
    assert miss.status_code == 422
    gone = ctx.c.get("/reports/INC-2026-0000", headers=ctx.h)
    assert gone.status_code == 404
    none = ctx.c.get("/reports/INC-2026-9003", headers=ctx.h)
    assert none.status_code == 404 and none.json()["error"]["message"] == "No report for this incident yet"


# ------------------------------------ the job ------------------------------------
def test_verified_llm_report_is_stored(ctx, monkeypatch):
    calls = fake_bridge(monkeypatch, result())
    r = post(ctx)
    assert r.status_code == 202 and r.json()["status"] in ("running", "completed")
    body = job(ctx, r.json()["job_id"]).json()
    assert body["status"] == "completed" and body["error"] is None
    assert calls[0][0] == "summarize" and calls[0][1] == {"incident": ctx.rows[0]["raw"]}
    stored = ctx.fake.tables["reports"][0]
    assert stored["incident_id"] == ctx.rows[0]["id"] and stored["source"] == "llm"
    assert stored["grounded"] is True and stored["unverified"] == [] and stored["summary"] == "Verified summary."
    assert stored["mitre"] == ["T1110 Brute Force"] and stored["raw"]["id"] == ID0
    assert ctx.c.get(f"/reports/{ID0}", headers=ctx.h).status_code == 200
    again = post(ctx)                                     # regenerating replaces, never duplicates
    assert again.status_code == 202 and len(ctx.fake.tables["reports"]) == 1


def test_llm_corrected_is_stored(ctx, monkeypatch):
    fake_bridge(monkeypatch, result(source="llm_corrected"))
    assert job(ctx, post(ctx).json()["job_id"]).json()["status"] == "completed"
    assert ctx.fake.tables["reports"][0]["source"] == "llm_corrected"


def test_grounded_template_is_stored_as_template(ctx, monkeypatch):
    fake_bridge(monkeypatch, result(source="template"))
    assert job(ctx, post(ctx).json()["job_id"]).json()["status"] == "completed"
    stored = ctx.fake.tables["reports"][0]
    assert stored["source"] == "template" and stored["grounded"] is True


@pytest.mark.parametrize("outcome", [
    result(source="template", grounded=False),              # an unverified template is never stored
    result(source="llm", grounded=False),
    result(source="bogus"),
    result(grounding=None),
    result(grounding={"grounded": "yes", "unverified": []}),
    result(grounding={"unverified": []})])
def test_unverified_is_not_stored(ctx, monkeypatch, outcome):
    fake_bridge(monkeypatch, outcome)
    body = job(ctx, post(ctx).json()["job_id"]).json()
    assert body["status"] == "failed"
    assert body["error"] == {"code": "unverified", "message": "report could not be verified"}
    assert ctx.fake.tables["reports"] == []


def test_stale_result_run_id_is_not_stored(ctx, monkeypatch):
    fake_bridge(monkeypatch, result(run_id="otherrunid00"))
    body = job(ctx, post(ctx).json()["job_id"]).json()
    assert body["status"] == "failed" and body["error"]["code"] == "stale_run"
    assert ctx.fake.tables["reports"] == []


def test_stale_incident_raw_never_calls_the_bridge(ctx, monkeypatch):
    ctx.rows[0]["raw"] = {**ctx.rows[0]["raw"], "pipeline_run_id": "oldrunid0000"}
    calls = fake_bridge(monkeypatch, result())
    body = job(ctx, post(ctx).json()["job_id"]).json()
    assert body["error"]["code"] == "stale_run" and calls == []


def test_run_switched_during_generation(ctx, monkeypatch):
    def run(mode, payload):
        ctx.fake.tables["pipeline_runs"][0]["is_current"] = False
        return result()
    monkeypatch.setattr(ai_bridge, "run_bridge", run)
    body = job(ctx, post(ctx).json()["job_id"]).json()
    assert body["error"]["code"] == "stale_run" and ctx.fake.tables["reports"] == []


@pytest.mark.parametrize("error,code,message", [
    ("ai_unavailable", "ai_unavailable", "AI service unavailable - start Ollama"),
    ("timeout", "timeout", "AI service timed out"),
    ("bad_output", "error", "report generation failed")])
def test_bridge_errors_become_job_errors_with_200(ctx, monkeypatch, error, code, message):
    fake_bridge(monkeypatch, ai_bridge.BridgeError(error))
    r = job(ctx, post(ctx).json()["job_id"])
    assert r.status_code == 200                              # the poll is always 200
    assert r.json()["status"] == "failed" and r.json()["error"] == {"code": code, "message": message}
    assert ctx.fake.tables["reports"] == []


def test_unexpected_exception_is_generic(ctx, monkeypatch):
    fake_bridge(monkeypatch, RuntimeError("secret row value"))
    body = job(ctx, post(ctx).json()["job_id"]).json()
    assert body["error"] == {"code": "error", "message": "report generation failed"}
    assert "secret" not in str(body)


def test_second_request_while_busy_is_429(ctx, monkeypatch):
    fake_bridge(monkeypatch, result())
    report_jobs._jobs["busy"] = report_jobs.ReportJob(id="busy", external_id=ID0, actor_id="x")
    report_jobs._active = "busy"
    r = post(ctx)
    assert r.status_code == 429 and r.json()["error"]["message"] == "report generation busy"
    report_jobs._jobs["busy"].status = "completed"
    assert post(ctx).status_code == 202                      # free again


def test_report_lock_is_separate_from_the_pipeline_lock(ctx, monkeypatch):
    fake_bridge(monkeypatch, result())
    jobs._jobs["in-flight"] = jobs.JobRecord(id="in-flight", kind="pipeline_run", params={}, actor_id="x")
    jobs._active_job_id = "in-flight"
    assert post(ctx).status_code == 202


def test_unknown_or_bad_incident(ctx, monkeypatch):
    calls = fake_bridge(monkeypatch, result())
    assert post(ctx, ext="INC-2026-0000").status_code == 404
    assert post(ctx, ext="nope").status_code == 422
    assert calls == []


def test_job_visibility(ctx, monkeypatch):
    fake_bridge(monkeypatch, result())
    job_id = post(ctx).json()["job_id"]
    other, _, _ = make_user(ctx.c, ctx.fake, "analyst", 2)
    manager, _, _ = make_user(ctx.c, ctx.fake, "manager", 3)
    admin, _, _ = make_user(ctx.c, ctx.fake, "admin", 4)
    assert job(ctx, job_id).status_code == 200
    assert job(ctx, job_id, other).status_code == 404
    assert job(ctx, job_id, manager).status_code == 200 and job(ctx, job_id, admin).status_code == 200
    assert job(ctx, "does-not-exist").status_code == 404


def test_job_audit_has_no_report_text(ctx, monkeypatch):
    fake_bridge(monkeypatch, result())
    post(ctx)
    rows = [r for r in ctx.fake.tables["audit_log"] if r["action"] == "report.job_finished"]
    assert len(rows) == 1 and rows[0]["details"]["status"] == "completed"
    assert "Verified summary" not in str(rows)
