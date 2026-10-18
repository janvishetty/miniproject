"""Runs backend/app/ml_bridge/bridge_cli.py with ML_PYTHON for Copilot and report calls.

Same safety rules as ml_adapter: absolute interpreter path, fixed argv (mode only), no shell,
an environment built from an EMPTY dict (no SUPABASE_*), a timeout. On top of that:
* the question / incident data goes in on STDIN only, never argv or env;
* stdout is read through a size cap and must be exactly one JSON line;
* stderr is discarded (it could echo input) and never logged;
* errors carry a code only, never the input.
The pipeline STEPS allowlist in ml_adapter is NOT touched.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from fastapi import HTTPException

from app.config import get_settings
from app.services import ml_adapter

BRIDGE_SCRIPT = Path(__file__).resolve().parents[1] / "ml_bridge" / "bridge_cli.py"
MODES = ("copilot", "welcome", "summarize")
TIMEOUTS = {"copilot": 120.0, "welcome": 120.0, "summarize": 600.0}
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
OLLAMA_DOWN_MESSAGE = "AI service unavailable - start Ollama"


class BridgeError(Exception):
    """code: ai_unavailable | timeout | bad_output | bridge_error. Never carries input."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def to_http(exc: BridgeError) -> HTTPException:
    if exc.code == "ai_unavailable":
        return HTTPException(503, OLLAMA_DOWN_MESSAGE)
    if exc.code == "timeout":
        return HTTPException(504, "AI service timed out")
    return HTTPException(502, "AI service returned an unusable response")


def _read_capped(stream, limit: int, state: dict, proc: subprocess.Popen) -> None:
    chunks, size = [], 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            state["oversized"] = True
            proc.kill()
            break
        chunks.append(chunk)
    state["data"] = b"".join(chunks)


def _write_stdin(stream, payload: bytes) -> None:
    try:
        stream.write(payload)
    except OSError:                      # child exited early (BrokenPipeError)
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_bridge(mode: str, payload: dict) -> dict:
    """Returns the bridge's "result" object, or raises BridgeError."""
    if mode not in MODES:
        raise ValueError(f"{mode!r} is not an allowed bridge mode")
    try:
        interpreter = ml_adapter.resolve_interpreter(get_settings().ML_PYTHON)
    except ml_adapter.AdapterError:
        raise BridgeError("bridge_error") from None
    try:
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError):
        raise BridgeError("bridge_error") from None

    argv = [interpreter, "-I", str(BRIDGE_SCRIPT), mode]
    try:
        proc = subprocess.Popen(argv, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=ml_adapter.build_env())
    except OSError:
        raise BridgeError("bridge_error") from None

    state: dict = {"data": b"", "oversized": False}
    reader = threading.Thread(target=_read_capped,
                              args=(proc.stdout, MAX_OUTPUT_BYTES, state, proc), daemon=True)
    writer = threading.Thread(target=_write_stdin, args=(proc.stdin, body), daemon=True)
    reader.start()
    writer.start()
    try:
        proc.wait(timeout=TIMEOUTS[mode])
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise BridgeError("timeout") from None
    finally:
        reader.join(timeout=5)
        writer.join(timeout=5)
        if proc.poll() is None:
            proc.kill()
    if state["oversized"]:
        raise BridgeError("bad_output")

    try:
        text = state["data"].decode("utf-8")
        lines = text.splitlines()
        if len(lines) != 1:
            raise ValueError("not exactly one line")
        message = json.loads(lines[0])
    except ValueError:                   # includes UnicodeDecodeError and JSONDecodeError
        raise BridgeError("bad_output") from None
    if not isinstance(message, dict) or not isinstance(message.get("ok"), bool):
        raise BridgeError("bad_output")
    if message["ok"]:
        result = message.get("result")
        if not isinstance(result, dict):
            raise BridgeError("bad_output")
        return result
    if message.get("error") == "ollama_unavailable":
        raise BridgeError("ai_unavailable")
    raise BridgeError("bridge_error")
