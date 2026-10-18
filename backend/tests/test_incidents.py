"""/incidents routes: auth matrix, 409, list (filters, sort, paging, search), detail, events, PATCH."""
import pytest

from app.services import incident_store
from soc_seed import make_incident, make_user, seed_run

ID0 = "INC-2026-9001"


@pytest.fixture
def ctx(client, fake):
    rows = seed_run(fake, 4)
    headers, uid, name = make_user(client, fake, "analyst", 1)
    return type("Ctx", (), {"c": client, "fake": fake, "rows": rows, "h": headers, "uid": uid, "name": name})


# ------------------------------ 401 / 403 / 200 / 409 ------------------------------
ROUTES = [("GET", "/incidents"), ("GET", f"/incidents/{ID0}"), ("GET", f"/incidents/{ID0}/events"),
          ("PATCH", f"/incidents/{ID0}")]


@pytest.mark.parametrize("method,path", ROUTES)
def test_requires_login(ctx, method, path):
    assert ctx.c.request(method, path, json={"status": "OPEN"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert ctx.c.request(method, path, headers=bad, json={"status": "OPEN"}).status_code == 401


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_every_role_can_read(client, fake, role):
    seed_run(fake)
    h, _, _ = make_user(client, fake, role, 1)
    for path in ("/incidents", f"/incidents/{ID0}", f"/incidents/{ID0}/events"):
        assert client.get(path, headers=h).status_code == 200


@pytest.mark.parametrize("method,path", ROUTES)
def test_no_current_run_is_409(client, fake, method, path):
    h, _, _ = make_user(client, fake, "admin", 1)
    r = client.request(method, path, headers=h, json={"status": "OPEN"})
    assert r.status_code == 409 and r.json()["error"]["message"] == "no pipeline run loaded yet"


def test_other_runs_incidents_are_never_shown(ctx):
    ctx.rows.append(make_incident(50, pipeline_run_id="old-run", title="OLD RUN"))
    ctx.fake.tables["incidents"] = ctx.rows
    body = ctx.c.get("/incidents", headers=ctx.h).json()
    assert body["total"] == 4 and all(i["title"] != "OLD RUN" for i in body["items"])
    assert ctx.c.get("/incidents/INC-2026-9050", headers=ctx.h).status_code == 404


# ------------------------------------- list -------------------------------------
def test_item_keys_and_defaults(ctx):
    body = ctx.c.get("/incidents", headers=ctx.h).json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 4 and body["page"] == 1 and body["page_size"] == 20
    item = body["items"][0]
    assert set(item) == {"id", "sev", "status", "title", "asset", "ip", "analyst", "vector", "created",
                         "confidence", "impact", "started_at", "risk_score"}
    assert item["id"] == ID0 and item["sev"] == "critical" and item["created"] == "00:15"
    assert [i["risk_score"] for i in body["items"]] == [90.0, 80.0, 70.0, 60.0]       # default risk desc


def test_created_falls_back_to_started_at_utc(ctx):
    row = ctx.rows[0]
    row["raw"] = {**row["raw"]}
    row["raw"].pop("created")
    row["started_at"] = "2026-09-01T05:07:00+05:30"
    item = next(i for i in ctx.c.get("/incidents", headers=ctx.h).json()["items"] if i["id"] == ID0)
    assert item["created"] == "23:37"


def test_sort_and_order(ctx):
    asc = ctx.c.get("/incidents?sort=risk_score&order=asc", headers=ctx.h).json()["items"]
    assert [i["risk_score"] for i in asc] == [60.0, 70.0, 80.0, 90.0]
    by_start = ctx.c.get("/incidents?sort=started_at", headers=ctx.h).json()["items"]
    assert [i["started_at"] for i in by_start] == sorted((i["started_at"] for i in by_start), reverse=True)
    conf = ctx.c.get("/incidents?sort=confidence", headers=ctx.h).json()["items"]
    assert [i["confidence"] for i in conf] == sorted((i["confidence"] for i in conf), reverse=True)


def test_null_sort_values_go_last(ctx):
    ctx.rows[0]["risk_score"] = None
    ids = [i["id"] for i in ctx.c.get("/incidents", headers=ctx.h).json()["items"]]
    assert ids[-1] == ID0


def test_paging(ctx):
    p1 = ctx.c.get("/incidents?page_size=3", headers=ctx.h).json()
    p2 = ctx.c.get("/incidents?page_size=3&page=2", headers=ctx.h).json()
    p3 = ctx.c.get("/incidents?page_size=3&page=3", headers=ctx.h).json()
    assert [len(p["items"]) for p in (p1, p2, p3)] == [3, 1, 0] and p1["total"] == 4 == p2["total"]
    assert not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}


@pytest.mark.parametrize("query", [
    "page=0", "page=-1", "page=abc", "page_size=0", "page_size=101", "sort=title", "sort=risk_score;drop",
    "order=sideways", "severity=urgent", "status=open", "status=DONE", "vector=Phishing",
    "search=" + "x" * 101])
def test_bad_query_values_are_422(ctx, query):
    r = ctx.c.get(f"/incidents?{query}", headers=ctx.h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_filters(ctx):
    ctx.rows[1]["status"] = "CONTAINED"
    get = lambda q: ctx.c.get(f"/incidents?{q}", headers=ctx.h).json()
    assert {i["sev"] for i in get("severity=high")["items"]} == {"high"}
    assert [i["status"] for i in get("status=CONTAINED")["items"]] == ["CONTAINED"]
    assert get("vector=Brute%20Force")["total"] == 1
    assert get("severity=high&status=OPEN")["total"] == 0


# ------------------------------------- search -------------------------------------
@pytest.fixture
def search_ctx(client, fake):
    titles = ["plain title", "100% match", "a_b underscore", "axb underscore", "it's quoted",
              "dash -- dash", "comma, here", "paren (open) x", "star * here", "starz here",
              "unicode ünï 日本語", 'say "hi"', "back\\slash"]
    rows = [make_incident(i, title=t, external_id=f"INC-2026-{9100 + i}") for i, t in enumerate(titles)]
    seed_run(fake, incidents=rows)
    h, _, _ = make_user(client, fake, "analyst", 1)
    return lambda q: [i["title"] for i in client.get("/incidents", params={"search": q}, headers=h).json()["items"]]


@pytest.mark.parametrize("term,expected", [
    ("%", ["100% match"]), ("_", ["a_b underscore"]), ("*", ["star * here"]),
    ("'", ["it's quoted"]), ("--", ["dash -- dash"]), (",", ["comma, here"]),
    ("(", ["paren (open) x"]), (")", ["paren (open) x"]), ("(open)", ["paren (open) x"]),
    ("日本", ["unicode ünï 日本語"]), ("ÜNÏ", ["unicode ünï 日本語"]), ('"hi"', ['say "hi"']),
    ("\\", ["back\\slash"]), ("a_b", ["a_b underscore"]), ("PLAIN", ["plain title"]),
    ("nothing matches this", [])])
def test_search_treats_every_character_literally(search_ctx, term, expected):
    assert search_ctx(term) == expected


def test_search_matches_other_columns_and_respects_filters(client, fake):
    seed_run(fake, 4)
    h, _, _ = make_user(client, fake, "analyst", 1)
    by_ip = client.get("/incidents", params={"search": "10.0.0.2"}, headers=h).json()
    assert [i["ip"] for i in by_ip["items"]] == ["10.0.0.2"]
    by_id = client.get("/incidents", params={"search": "9003"}, headers=h).json()
    assert [i["id"] for i in by_id["items"]] == ["INC-2026-9003"]
    both = client.get("/incidents", params={"search": "Incident", "severity": "low"}, headers=h).json()
    assert both["total"] == 1 and both["items"][0]["sev"] == "low"


def test_search_pages_and_sorts(client, fake):
    seed_run(fake, 4)
    h, _, _ = make_user(client, fake, "analyst", 1)
    r = client.get("/incidents", params={"search": "Incident", "page_size": 2, "page": 2}, headers=h).json()
    assert r["total"] == 4 and [i["risk_score"] for i in r["items"]] == [70.0, 60.0]


def test_search_cap_is_422_not_truncation(client, fake):
    rows = [make_incident(i, title="common words", external_id=f"INC-2026-{i:04d}",
                          severity="low" if i < 100 else "high") for i in range(301)]
    seed_run(fake, incidents=rows)
    h, _, _ = make_user(client, fake, "analyst", 1)
    r = client.get("/incidents", params={"search": "common"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["message"] == "search too broad, add a filter"
    ok = client.get("/incidents", params={"search": "common", "severity": "low", "page_size": 100}, headers=h)
    assert ok.status_code == 200 and ok.json()["total"] == 100
    rows.pop()                                           # exactly 300 matches is allowed
    assert client.get("/incidents", params={"search": "common"}, headers=h).json()["total"] == 300


def test_escape_like():
    assert incident_store.escape_like('a%b_c*d,e(f)g"h\\i') == 'a\\%b\\_c\\*d\\,e\\(f\\)g\\"h\\\\i'


def test_search_never_builds_or_filters():
    import inspect
    assert ".or_(" not in inspect.getsource(incident_store)


# ------------------------------------- detail -------------------------------------
def test_detail(ctx):
    ctx.fake.tables["reports"] = [{"incident_id": ctx.rows[0]["id"], "summary": "Rep", "source": "llm",
                                   "grounded": True, "created_at": "2026-10-18T10:00:00+00:00"}]
    body = ctx.c.get(f"/incidents/{ID0}", headers=ctx.h).json()
    for key in ("timeline", "reasons", "sequence", "ip_details", "threat_actor", "ai_summary", "rule_hits",
                "rule_mitre", "detected_by", "event_ids", "id", "sev", "report"):
        assert key in body
    assert body["event_ids"] == ["E900001", "E900002", "T900001"]
    assert body["report"] == {"summary": "Rep", "source": "llm", "grounded": True,
                              "created_at": "2026-10-18T10:00:00+00:00"}
    other = ctx.c.get("/incidents/INC-2026-9002", headers=ctx.h).json()
    assert other["report"] is None and other["event_ids"] == []


def test_detail_404_and_bad_id(ctx):
    r = ctx.c.get("/incidents/INC-2026-0000", headers=ctx.h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    for bad in ("abc", "INC-2026-12345", "INC-26-0001", "inc-2026-0001", "INC-2026-000a"):
        r = ctx.c.get(f"/incidents/{bad}", headers=ctx.h)
        assert r.status_code == 422, bad
        assert ctx.c.get(f"/incidents/{bad}/events", headers=ctx.h).status_code == 422


# ------------------------------------- events -------------------------------------
def test_events_ordered_and_paged(ctx):
    body = ctx.c.get(f"/incidents/{ID0}/events", headers=ctx.h).json()
    assert [e["event_id"] for e in body["items"]] == ["E900001", "T900001", "E900002"]      # by ts, then id
    assert body["total"] == 3
    page2 = ctx.c.get(f"/incidents/{ID0}/events?page_size=2&page=2", headers=ctx.h).json()
    assert [e["event_id"] for e in page2["items"]] == ["E900002"] and page2["total"] == 3
    assert ctx.c.get(f"/incidents/{ID0}/events?page_size=101", headers=ctx.h).status_code == 422
    assert ctx.c.get("/incidents/INC-2026-0000/events", headers=ctx.h).status_code == 404


# -------------------------------------- PATCH --------------------------------------
def patch(ctx, body, headers=None, ext=ID0):
    return ctx.c.patch(f"/incidents/{ext}", json=body, headers=headers or ctx.h)


def audit_rows(fake):
    return [r for r in fake.tables.get("audit_log", []) if r["action"] == "incident.updated"]


def test_analyst_may_set_open_investigating_contained(ctx):
    for status in ("INVESTIGATING", "CONTAINED", "OPEN"):
        r = patch(ctx, {"status": status})
        assert r.status_code == 200 and r.json()["status"] == status and r.json()["id"] == ID0
    assert ctx.rows[0]["status"] == "OPEN"


def test_analyst_cannot_resolve(ctx):
    r = patch(ctx, {"status": "RESOLVED"})
    assert r.status_code == 403 and ctx.rows[0]["status"] == "OPEN" and not audit_rows(ctx.fake)


def test_analyst_assigns_only_themselves(ctx):
    r = patch(ctx, {"analyst_id": ctx.uid})
    assert r.status_code == 200 and r.json()["analyst"] == ctx.name and ctx.rows[0]["analyst"] == ctx.name
    _, other_id, _ = make_user(ctx.c, ctx.fake, "analyst", 2)
    assert patch(ctx, {"analyst_id": other_id}).status_code == 403
    assert patch(ctx, {"analyst_id": None}).status_code == 403
    assert ctx.rows[0]["analyst"] == ctx.name


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_manager_and_admin_rules(ctx, role):
    h, _, _ = make_user(ctx.c, ctx.fake, role, 5)
    _, other_id, other_name = make_user(ctx.c, ctx.fake, "analyst", 6)
    r = patch(ctx, {"status": "RESOLVED", "analyst_id": other_id}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED" and r.json()["analyst"] == other_name
    r = patch(ctx, {"analyst_id": None}, headers=h)
    assert r.status_code == 200 and r.json()["analyst"] == "Unassigned"
    unknown = patch(ctx, {"analyst_id": "11111111-1111-4111-8111-111111111111"}, headers=h)
    assert unknown.status_code == 422 and ctx.rows[0]["analyst"] == "Unassigned"


def test_analyst_unknown_self_id_is_still_checked(ctx):
    assert patch(ctx, {"analyst_id": "11111111-1111-4111-8111-111111111111"}).status_code == 403


@pytest.mark.parametrize("body", [
    {}, {"status": None}, {"status": "DONE"}, {"status": "open"}, {"analyst_id": "not-a-uuid"},
    {"analyst": "Mallory"}, {"status": "OPEN", "severity": "low"}, {"title": "x"}, {"risk_score": 1},
    {"analyst_id": 5}])
def test_patch_body_is_strict(ctx, body):
    r = patch(ctx, body)
    assert r.status_code == 422 and ctx.rows[0]["status"] == "OPEN" and not audit_rows(ctx.fake)


def test_patch_404_and_bad_id(ctx):
    assert patch(ctx, {"status": "OPEN"}, ext="INC-2026-0000").status_code == 404
    assert patch(ctx, {"status": "OPEN"}, ext="bad").status_code == 422


def test_patch_audit_content(ctx):
    h, mid, mname = make_user(ctx.c, ctx.fake, "manager", 5)
    assert patch(ctx, {"status": "INVESTIGATING", "analyst_id": ctx.uid}).status_code == 200
    patch(ctx, {"status": "RESOLVED"}, headers=h)
    first, second = audit_rows(ctx.fake)
    assert first["actor_id"] == ctx.uid and first["entity"] == "incident" and first["entity_id"] == ID0
    assert first["details"]["before"] == {"status": "OPEN", "analyst": "Unassigned"}
    assert first["details"]["after"] == {"status": "INVESTIGATING", "analyst": ctx.name}
    assert second["actor_id"] == mid
    assert second["details"]["before"]["status"] == "INVESTIGATING"
    assert second["details"]["after"] == {"status": "RESOLVED", "analyst": ctx.name}


def test_patch_shows_in_dashboard_and_list(ctx):
    h, _, _ = make_user(ctx.c, ctx.fake, "manager", 5)
    patch(ctx, {"status": "RESOLVED"}, headers=h)
    assert ctx.c.get("/dashboard", headers=ctx.h).json()["active_incidents"] == 3
    assert ctx.c.get("/incidents?status=RESOLVED", headers=ctx.h).json()["total"] == 1
