"""POST /copilot, GET /copilot/welcome and the subprocess bridge (ai_bridge + bridge_cli)."""
import ast
import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import ai_bridge, copilot_guard
from soc_seed import make_incident, make_user, seed_run

SECRET = "SECRET-QUESTION-zq81 why was U9001 flagged?"
CLI = Path(ai_bridge.BRIDGE_SCRIPT)


@pytest.fixture(autouse=True)
def _reset_guard():
    copilot_guard.reset()
    yield
    copilot_guard.reset()


@pytest.fixture
def ctx(client, fake):
    rows = seed_run(fake, 4)
    headers, uid, _ = make_user(client, fake, "analyst", 1)
    return SimpleNamespace(c=client, fake=fake, rows=rows, h=headers, uid=uid)


def canned(**over):
    out = {"question": SECRET, "answer": "INC-2026-9001 was flagged.", "incidents": ["INC-2026-9001", "junk"],
           "source": "llm", "grounding": {"grounded": True, "unverified": []}, "seconds": 1.5}
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


def ask(ctx, question=SECRET, headers=None):
    return ctx.c.post("/copilot", json={"question": question}, headers=headers or ctx.h)


# ------------------------------- auth / validation -------------------------------
@pytest.mark.parametrize("method,path", [("POST", "/copilot"), ("GET", "/copilot/welcome")])
def test_requires_login(ctx, method, path):
    assert ctx.c.request(method, path, json={"question": "x"}).status_code == 401
    assert ctx.c.request(method, path, json={"question": "x"},
                         headers={"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_every_role_can_use_copilot(client, fake, role, monkeypatch):
    seed_run(fake)
    h, _, _ = make_user(client, fake, role, 1)
    fake_bridge(monkeypatch, canned())
    assert client.post("/copilot", json={"question": "hi"}, headers=h).status_code == 200
    assert client.get("/copilot/welcome", headers=h).status_code == 200


@pytest.mark.parametrize("method,path", [("POST", "/copilot"), ("GET", "/copilot/welcome")])
def test_no_current_run_is_409(client, fake, method, path):
    h, _, _ = make_user(client, fake, "analyst", 1)
    r = client.request(method, path, json={"question": "hi"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["message"] == "no pipeline run loaded yet"


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": "x" * 501},
                                  {"question": 5}, {"question": "ok", "extra": 1}])
def test_question_validation(ctx, monkeypatch, body):
    calls = fake_bridge(monkeypatch, canned())
    r = ctx.c.post("/copilot", json=body, headers=ctx.h)
    assert r.status_code == 422 and calls == []
    assert "x" * 50 not in json.dumps(r.json())


def test_question_of_500_is_accepted(ctx, monkeypatch):
    fake_bridge(monkeypatch, canned())
    assert ask(ctx, "q" * 500).status_code == 200


# ------------------------------------ answers ------------------------------------
def test_answer_response_and_data_sent(ctx, monkeypatch):
    ctx.rows[1]["status"], ctx.rows[1]["analyst"] = "RESOLVED", "Ravi"
    ctx.fake.tables["reports"] = [{"incident_id": ctx.rows[0]["id"], "raw": {"id": "INC-2026-9001", "x": 1}}]
    calls = fake_bridge(monkeypatch, canned())
    body = ask(ctx).json()
    assert set(body) == {"answer", "incidents", "source", "grounding", "seconds"}     # no question echo
    assert body["incidents"] == ["INC-2026-9001"]
    mode, payload = calls[0]
    assert mode == "copilot" and payload["question"] == SECRET
    assert len(payload["incidents"]) == 4                                   # ALL incidents, resolved too
    live = {i["id"]: i for i in payload["incidents"]}
    assert live["INC-2026-9002"]["status"] == "RESOLVED" and live["INC-2026-9002"]["analyst"] == "Ravi"
    assert payload["reports"] == {"INC-2026-9001": {"id": "INC-2026-9001", "x": 1}}


def test_welcome_gets_only_unresolved(ctx, monkeypatch):
    ctx.rows[1]["status"] = "RESOLVED"
    calls = fake_bridge(monkeypatch, canned(source="facts"))
    assert ctx.c.get("/copilot/welcome", headers=ctx.h).status_code == 200
    mode, payload = calls[0]
    assert mode == "welcome" and len(payload["incidents"]) == 3
    assert "INC-2026-9002" not in {i["id"] for i in payload["incidents"]}


@pytest.mark.parametrize("error,status,message", [
    ("ai_unavailable", 503, "AI service unavailable - start Ollama"),
    ("timeout", 504, "AI service timed out"),
    ("bad_output", 502, "AI service returned an unusable response")])
def test_bridge_errors_map_to_http(ctx, monkeypatch, error, status, message):
    fake_bridge(monkeypatch, ai_bridge.BridgeError(error))
    r = ask(ctx)
    assert r.status_code == status and r.json()["error"]["message"] == message
    assert not [a for a in ctx.fake.tables.get("audit_log", []) if a["action"] == "copilot.ask"]


# ----------------------------------- audit + logs -----------------------------------
def test_audit_has_length_source_and_ids_never_the_question(ctx, monkeypatch, caplog):
    fake_bridge(monkeypatch, canned())
    with caplog.at_level(logging.DEBUG):
        assert ask(ctx).status_code == 200
    rows = [a for a in ctx.fake.tables["audit_log"] if a["action"] == "copilot.ask"]
    assert len(rows) == 1 and rows[0]["actor_id"] == ctx.uid
    assert rows[0]["details"] == {"question_length": len(SECRET), "source": "llm",
                                  "incidents": ["INC-2026-9001"]}
    assert "SECRET-QUESTION" not in json.dumps(ctx.fake.tables["audit_log"], default=str)
    assert "SECRET-QUESTION" not in caplog.text


def test_question_never_in_argv_env_logs_or_audit(ctx, monkeypatch, caplog, tmp_path):
    script = tmp_path / "echo_bridge.py"
    script.write_text(textwrap.dedent("""
        import json, sys
        data = json.loads(sys.stdin.read())
        assert data["question"]
        print(json.dumps({"ok": True, "result": {"answer": "fine", "incidents": [], "source": "facts"}}))
    """))
    monkeypatch.setattr(ai_bridge, "BRIDGE_SCRIPT", script)
    monkeypatch.setattr(ai_bridge, "get_settings", lambda: SimpleNamespace(ML_PYTHON=sys.executable))
    seen = []
    real_popen = subprocess.Popen

    def spy(argv, **kwargs):
        seen.append((list(argv), dict(kwargs.get("env") or {}), kwargs.get("shell")))
        return real_popen(argv, **kwargs)
    monkeypatch.setattr(ai_bridge.subprocess, "Popen", spy)
    with caplog.at_level(logging.DEBUG):
        r = ask(ctx)
    assert r.status_code == 200 and r.json()["answer"] == "fine"
    argv, env, shell = seen[0]
    assert argv == [sys.executable, "-I", str(script), "copilot"] and shell is False
    assert "SECRET-QUESTION" not in " ".join(argv) + json.dumps(env)
    assert not [k for k in env if k.startswith("SUPABASE") or "KEY" in k or "TOKEN" in k]
    assert "SECRET-QUESTION" not in caplog.text
    assert "SECRET-QUESTION" not in json.dumps(ctx.fake.tables["audit_log"], default=str)


# --------------------------------- limits (rate, busy) ---------------------------------
def test_rate_limit_is_ten_per_minute_per_user(ctx, monkeypatch):
    fake_bridge(monkeypatch, canned())
    for _ in range(10):
        assert ask(ctx).status_code == 200
    r = ask(ctx)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"
    other, _, _ = make_user(ctx.c, ctx.fake, "analyst", 2)
    assert ask(ctx, headers=other).status_code == 200                    # per user, not global


def test_rate_window_expires(ctx, monkeypatch):
    fake_bridge(monkeypatch, canned())
    clock = [1000.0]
    monkeypatch.setattr(copilot_guard.time, "monotonic", lambda: clock[0])
    for _ in range(10):
        ask(ctx)
    assert ask(ctx).status_code == 429
    clock[0] += 61
    assert ask(ctx).status_code == 200


def test_one_call_at_a_time(ctx, monkeypatch):
    calls = fake_bridge(monkeypatch, canned())
    assert copilot_guard._busy.acquire(blocking=False)
    r = ask(ctx)
    assert r.status_code == 429 and r.json()["error"]["message"] == "copilot busy" and calls == []
    copilot_guard._busy.release()
    assert ask(ctx).status_code == 200
    assert copilot_guard._busy.acquire(blocking=False)                    # lock released after a call
    copilot_guard._busy.release()


def test_lock_released_after_a_failure(ctx, monkeypatch):
    fake_bridge(monkeypatch, ai_bridge.BridgeError("timeout"))
    assert ask(ctx).status_code == 504
    fake_bridge(monkeypatch, canned())
    assert ask(ctx).status_code == 200


# ------------------------------ ai_bridge: real subprocess ------------------------------
@pytest.fixture
def bridge_script(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_bridge, "get_settings", lambda: SimpleNamespace(ML_PYTHON=sys.executable))

    def make(code: str):
        script = tmp_path / "fake_bridge.py"
        script.write_text(textwrap.dedent(code))
        monkeypatch.setattr(ai_bridge, "BRIDGE_SCRIPT", script)
        return script
    return make


def test_bridge_ollama_down(bridge_script):
    bridge_script("""print('{"ok": false, "error": "ollama_unavailable"}')""")
    with pytest.raises(ai_bridge.BridgeError) as exc:
        ai_bridge.run_bridge("copilot", {"question": "q"})
    assert exc.value.code == "ai_unavailable"


def test_bridge_timeout(bridge_script, monkeypatch):
    bridge_script("import time\ntime.sleep(30)")
    monkeypatch.setitem(ai_bridge.TIMEOUTS, "copilot", 0.5)
    with pytest.raises(ai_bridge.BridgeError) as exc:
        ai_bridge.run_bridge("copilot", {"question": "q"})
    assert exc.value.code == "timeout"


def test_timeouts_are_120_and_600():
    assert ai_bridge.TIMEOUTS["copilot"] == 120 and ai_bridge.TIMEOUTS["summarize"] == 600


def test_timeout_is_504_through_the_route(ctx, bridge_script, monkeypatch):
    bridge_script("import time\ntime.sleep(30)")
    monkeypatch.setitem(ai_bridge.TIMEOUTS, "copilot", 0.5)
    assert ask(ctx).status_code == 504


def test_ollama_down_is_503_through_the_route(ctx, bridge_script):
    bridge_script("""print('{"ok": false, "error": "ollama_unavailable"}')""")
    r = ask(ctx)
    assert r.status_code == 503 and r.json()["error"]["message"] == "AI service unavailable - start Ollama"


@pytest.mark.parametrize("code", [
    "print('x' * 3_000_000)",                                                # over the size cap
    "print('{' + 'a' * 3_000_000)",
    "print('not json')",
    "print('{\"ok\": true, \"result\": {}}'); print('{\"ok\": true, \"result\": {}}')",   # two lines
    "print('[1, 2]')",
    "print('{\"ok\": \"yes\"}')",
    "print('{\"ok\": true, \"result\": \"text\"}')",
    "import sys; sys.stdout.buffer.write(b'\\xff\\xfe\\n')",
    "",                                                                        # no output at all
    "import sys; sys.exit(3)",
    "print('{\"ok\": false, \"error\": \"bridge_error\"}')"])
def test_bridge_bad_output_is_handled(bridge_script, code):
    bridge_script(code)
    with pytest.raises(ai_bridge.BridgeError) as exc:
        ai_bridge.run_bridge("copilot", {"question": "q"})
    assert exc.value.code in ("bad_output", "bridge_error")


def test_oversized_output_is_stopped_early(bridge_script):
    bridge_script("import sys\nwhile True:\n    sys.stdout.write('x' * 100000)\n    sys.stdout.flush()")
    with pytest.raises(ai_bridge.BridgeError) as exc:
        ai_bridge.run_bridge("copilot", {"question": "q"})
    assert exc.value.code == "bad_output"


def test_big_input_does_not_deadlock(bridge_script):
    bridge_script("""
        import json, sys
        data = json.loads(sys.stdin.read())
        print(json.dumps({"ok": True, "result": {"n": len(data["blob"])}}))
    """)
    assert ai_bridge.run_bridge("copilot", {"blob": "y" * 3_000_000}) == {"n": 3_000_000}


def test_bad_interpreter_and_mode(monkeypatch):
    monkeypatch.setattr(ai_bridge, "get_settings", lambda: SimpleNamespace(ML_PYTHON="python3"))
    with pytest.raises(ai_bridge.BridgeError):
        ai_bridge.run_bridge("copilot", {})
    with pytest.raises(ValueError):
        ai_bridge.run_bridge("pipeline", {})


def test_bridge_modes_are_not_pipeline_steps():
    from app.services import ml_adapter
    assert not set(ai_bridge.MODES) & set(ml_adapter.STEPS) and "bridge_cli.py" not in ml_adapter.STEPS
    assert ml_adapter.STEPS == ("preprocess.py", "features.py", "model.py", "incidents.py", "frontend_data.py")


# ------------------------------ bridge_cli itself ------------------------------
def test_real_bridge_welcome_runs_on_stdin_data(monkeypatch):
    """The real bridge_cli + real copilot.welcome(), no Ollama needed."""
    monkeypatch.setattr(ai_bridge, "get_settings", lambda: SimpleNamespace(ML_PYTHON=sys.executable))
    raws = [make_incident(i)["raw"] for i in range(3)]
    result = ai_bridge.run_bridge("welcome", {"incidents": raws, "reports": {}})
    assert result["source"] == "facts" and "3 open incidents" in result["answer"]
    assert result["incidents"][0] == "INC-2026-9001"


def run_cli(*args, stdin=""):
    return subprocess.run([sys.executable, "-I", str(CLI), *args], input=stdin, capture_output=True,
                          text=True, timeout=60)


def test_cli_welcome_as_real_subprocess_with_fake_data():
    """bridge_cli.py run exactly like the app runs it (python -I, mode argv, JSON on stdin)."""
    raws = [make_incident(i)["raw"] for i in range(4)]
    raws[1]["status"] = "RESOLVED"
    stdin = json.dumps({"incidents": [r for r in raws if r["status"] != "RESOLVED"], "reports": {}})
    done = run_cli("welcome", stdin=stdin)
    assert done.returncode == 0, done.stderr
    assert len(done.stdout.strip().splitlines()) == 1                      # exactly one JSON line
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["result"]["source"] == "facts"
    assert "3 open incidents" in out["result"]["answer"]
    assert out["result"]["incidents"][0] == "INC-2026-9001"


def test_cli_bad_usage_and_input():
    for args, stdin in [((), "{}"), (("nope",), "{}"), (("copilot",), "not json"), (("copilot",), "[1]"),
                        (("copilot", "extra"), "{}")]:
        done = run_cli(*args, stdin=stdin)
        assert done.returncode == 2 and json.loads(done.stdout) == {"ok": False, "error": "bad_input"}
    for mode, data in [("copilot", {"incidents": [], "reports": {}}), ("copilot", {"question": "q"}),
                       ("summarize", {}), ("welcome", {"incidents": {}, "reports": {}})]:
        out = json.loads(run_cli(mode, stdin=json.dumps(data)).stdout)
        assert out == {"ok": False, "error": "bad_input"}


def load_cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bridge_cli_under_test", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_maps_urlerror_to_ollama_unavailable(monkeypatch):
    import urllib.error
    cli = load_cli_module()

    class Boom:
        def answer(self, q):
            raise urllib.error.URLError("refused")

        def summarize(self, i):
            raise urllib.error.URLError("refused")
        load = None
    monkeypatch.setitem(sys.modules, "copilot", Boom())
    monkeypatch.setitem(sys.modules, "summarize", Boom())
    assert cli.run("copilot", {"question": "q", "incidents": [], "reports": {}}) == {
        "ok": False, "error": "ollama_unavailable"}
    assert cli.run("summarize", {"incident": {}}) == {"ok": False, "error": "ollama_unavailable"}


def test_cli_replaces_load_and_hides_other_errors(monkeypatch):
    cli = load_cli_module()
    seen = {}

    class Fake:
        def answer(self, q):
            seen["loaded"] = self.load()
            raise KeyError("SECRET-ROW-VALUE")
    monkeypatch.setitem(sys.modules, "copilot", Fake())
    out = cli.run("copilot", {"question": "q", "incidents": [{"id": "a"}], "reports": {"a": {}}})
    assert seen["loaded"] == ([{"id": "a"}], {"a": {}})
    assert out == {"ok": False, "error": "bridge_error", "error_type": "KeyError"}
    assert "SECRET" not in json.dumps(out)


def test_bridge_cli_imports_without_app_on_sys_path():
    code = textwrap.dedent(f"""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("bridge_cli", {str(CLI)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bad = sorted(m for m in sys.modules
                     if m.split('.')[0] in ("app", "fastapi", "supabase", "pydantic", "starlette", "httpx"))
        assert not bad, bad
        assert callable(mod.main) and callable(mod.run)
        print("ok")
    """)
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                          cwd=str(CLI.parent.parent.parent.parent), timeout=60)     # repo root, not backend/
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_bridge_cli_source_imports_only_stdlib():
    tree = ast.parse(CLI.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            names.add((node.module or "").split(".")[0])
    ml_modules = {"copilot", "summarize"}
    assert names - ml_modules <= set(sys.stdlib_module_names), names
    assert "app" not in names
