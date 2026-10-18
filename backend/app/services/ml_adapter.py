"""Runs Janvi's pipeline scripts (backend/ml/) as separate processes.

Safety rules, all enforced here:
* only the five allowlisted script names, in a fixed order, with a fixed argv
  (no user input ever reaches the command line);
* the interpreter must be an absolute path to an existing executable (ML_PYTHON);
* shell=False, no stdin, a timeout per step;
* the child gets an environment built from an EMPTY dict (no SUPABASE_* keys);
* stdout is DISCARDED (the scripts print user ids, IPs and amounts); only the last
  20 stderr lines (200 characters each) are kept, and only for the result object.
summarize.py, copilot.py, evaluate.py, inject_test.py, review_sheet.py and
export_samples.py are never run.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

STEPS = ("preprocess.py", "features.py", "model.py", "incidents.py", "frontend_data.py")
ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
STDERR_LINES = 20
STDERR_LINE_CHARS = 200


class AdapterError(RuntimeError):
    """Configuration problem (bad interpreter, missing script). Never carries paths' contents."""


@dataclass
class StepResult:
    name: str
    exit_code: int | None          # None = timed out
    duration_seconds: float
    timed_out: bool = False
    stderr_tail: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {"name": self.name, "exit_code": self.exit_code, "timed_out": self.timed_out,
                "duration_seconds": round(self.duration_seconds, 3),
                "stderr_tail": self.stderr_tail}


def resolve_interpreter(value: str | None) -> str:
    message = "ML_PYTHON must be an absolute path to an existing executable"
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(message)
    path = Path(value.strip())
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise AdapterError(message)
    return str(path)


def build_env(environ: dict | None = None) -> dict:
    source = os.environ if environ is None else environ
    env = {key: source[key] for key in ENV_KEYS if key in source}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _tail(data) -> list[str]:
    if not data:
        return []
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    return [line[:STDERR_LINE_CHARS] for line in text.splitlines()[-STDERR_LINES:]]


def run_step(name: str, interpreter: str, ml_dir: Path, cwd: Path, timeout: float) -> StepResult:
    if name not in STEPS:
        raise ValueError(f"{name!r} is not an allowed pipeline step")
    script = Path(ml_dir) / name
    if not script.is_file():
        raise AdapterError(f"pipeline script missing: {name}")
    start = time.perf_counter()
    try:
        done = subprocess.run(
            [interpreter, str(script)], shell=False, cwd=str(cwd), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=build_env(),
            timeout=timeout, check=False)
        return StepResult(name, done.returncode, time.perf_counter() - start,
                          stderr_tail=_tail(done.stderr))
    except subprocess.TimeoutExpired as exc:
        return StepResult(name, None, time.perf_counter() - start, timed_out=True,
                          stderr_tail=_tail(exc.stderr))


def run_pipeline(interpreter: str, ml_dir: Path, cwd: Path, timeout: float) -> list[StepResult]:
    """Runs the steps in order and stops at the first failure."""
    results: list[StepResult] = []
    for name in STEPS:
        result = run_step(name, interpreter, ml_dir, cwd, timeout)
        results.append(result)
        if not result.ok:
            break
    return results
