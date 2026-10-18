"""ml_adapter: allowlist, interpreter check, clean environment, stdout discarded, timeout, stop-on-failure.
Only tiny fake scripts are run; Janvi's real scripts are never touched."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from app.services import ml_adapter

SECRET_STDOUT = "SECRET-STDOUT-VALUE-U0001-10.0.0.1"


def make_scripts(directory: Path, overrides: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ml_adapter.STEPS:
        code = (overrides or {}).get(name, "pass\n")
        (directory / name).write_text(code)
    return directory


def test_step_order_and_allowlist_are_exact():
    assert ml_adapter.STEPS == ("preprocess.py", "features.py", "model.py", "incidents.py",
                                "frontend_data.py")


@pytest.mark.parametrize("name", ["summarize.py", "copilot.py", "evaluate.py", "inject_test.py",
                                  "review_sheet.py", "export_samples.py", "../evil.py",
                                  "preprocess.py; ls", "/bin/sh"])
def test_anything_outside_the_allowlist_raises_value_error(tmp_path, name):
    scripts = make_scripts(tmp_path / "ml")
    with pytest.raises(ValueError):
        ml_adapter.run_step(name, sys.executable, scripts, tmp_path, 5)


def test_relative_interpreter_is_rejected():
    for bad in ("python3", "./python3", "bin/python3", "", None, "   "):
        with pytest.raises(ml_adapter.AdapterError):
            ml_adapter.resolve_interpreter(bad)


def test_missing_or_non_executable_interpreter_is_rejected(tmp_path):
    with pytest.raises(ml_adapter.AdapterError):
        ml_adapter.resolve_interpreter(str(tmp_path / "nope"))
    plain = tmp_path / "plain"
    plain.write_text("x")
    plain.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(ml_adapter.AdapterError):
        ml_adapter.resolve_interpreter(str(plain))
    with pytest.raises(ml_adapter.AdapterError):
        ml_adapter.resolve_interpreter(str(tmp_path))          # a directory


def test_absolute_executable_is_accepted():
    assert ml_adapter.resolve_interpreter(sys.executable) == sys.executable


def test_build_env_keeps_only_the_allowed_keys():
    env = ml_adapter.build_env({"PATH": "/bin", "HOME": "/h", "SUPABASE_SERVICE_ROLE_KEY": "s",
                                "LANG": "en_US.UTF-8", "OTHER": "x"})
    assert env == {"PATH": "/bin", "HOME": "/h", "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1"}


def test_child_process_sees_no_supabase_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-service-key-xyz")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SOME_OTHER_SECRET", "other-xyz")
    scripts = make_scripts(tmp_path / "ml", {
        "preprocess.py": "import os, json\njson.dump(dict(os.environ), open('env.json', 'w'))\n"})
    result = ml_adapter.run_step("preprocess.py", sys.executable, scripts, tmp_path, 20)
    assert result.ok
    child_env = json.loads((tmp_path / "env.json").read_text())
    assert not any(k.startswith("SUPABASE") for k in child_env)
    assert "SOME_OTHER_SECRET" not in child_env
    blob = json.dumps(child_env)
    assert "secret-service-key-xyz" not in blob and "other-xyz" not in blob
    assert child_env["PYTHONUNBUFFERED"] == "1" and child_env["PATH"] == os.environ["PATH"]


def test_stdout_is_discarded_and_never_appears_in_the_result(tmp_path):
    scripts = make_scripts(tmp_path / "ml", {
        "preprocess.py": f"import sys\nprint('{SECRET_STDOUT}')\nsys.stderr.write('warn: something\\n')\n"})
    result = ml_adapter.run_step("preprocess.py", sys.executable, scripts, tmp_path, 20)
    assert result.ok and result.stderr_tail == ["warn: something"]
    assert SECRET_STDOUT not in repr(result) and SECRET_STDOUT not in json.dumps(result.to_dict())
    results = ml_adapter.run_pipeline(sys.executable, scripts, tmp_path, 20)
    assert SECRET_STDOUT not in json.dumps([r.to_dict() for r in results])


def test_timeout_is_reported_and_stops_the_chain(tmp_path):
    scripts = make_scripts(tmp_path / "ml", {"preprocess.py": "import time\ntime.sleep(30)\n"})
    results = ml_adapter.run_pipeline(sys.executable, scripts, tmp_path, 0.5)
    assert len(results) == 1
    assert results[0].timed_out and results[0].exit_code is None and not results[0].ok
    assert results[0].duration_seconds < 15


def test_non_zero_exit_stops_chain_and_truncates_stderr(tmp_path):
    marker = tmp_path / "model_ran"
    scripts = make_scripts(tmp_path / "ml", {
        "features.py": ("import sys\n"
                        "for i in range(30):\n"
                        "    sys.stderr.write('line%02d ' % i + 'x' * 300 + '\\n')\n"
                        "sys.exit(3)\n"),
        "model.py": f"open({str(marker)!r}, 'w').write('ran')\n"})
    results = ml_adapter.run_pipeline(sys.executable, scripts, tmp_path, 20)
    assert [r.name for r in results] == ["preprocess.py", "features.py"]
    failed = results[-1]
    assert failed.exit_code == 3 and not failed.ok
    assert len(failed.stderr_tail) == 20
    assert all(len(line) <= 200 for line in failed.stderr_tail)
    assert failed.stderr_tail[0].startswith("line10") and failed.stderr_tail[-1].startswith("line29")
    assert not marker.exists()                                     # later steps never ran


def test_all_five_steps_run_in_order_when_everything_succeeds(tmp_path):
    log = tmp_path / "order.txt"
    code = f"open({str(log)!r}, 'a').write(__file__.split('/')[-1] + '\\n')\n"
    scripts = make_scripts(tmp_path / "ml", {n: code for n in ml_adapter.STEPS})
    results = ml_adapter.run_pipeline(sys.executable, scripts, tmp_path, 20)
    assert all(r.ok for r in results)
    assert log.read_text().split() == list(ml_adapter.STEPS)


def test_missing_script_is_an_adapter_error(tmp_path):
    with pytest.raises(ml_adapter.AdapterError):
        ml_adapter.run_step("preprocess.py", sys.executable, tmp_path / "empty", tmp_path, 5)
