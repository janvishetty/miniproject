"""Runs ONE Copilot / report call in the ML interpreter. Stdlib + backend/ml only.

This file runs under ML_PYTHON (the ML venv, which has no fastapi or supabase), so it must
never import anything from `app`. It is started by app/services/ai_bridge.py as

    <ML_PYTHON> -I bridge_cli.py <copilot | welcome | summarize>

Input : ONE JSON object on stdin
          copilot   {"question": str, "incidents": [raw incident, ...], "reports": {id: report}}
          welcome   {"incidents": [...], "reports": {...}}
          summarize {"incident": raw incident}
Output: exactly ONE JSON line on stdout
          {"ok": true, "result": {...}}
          {"ok": false, "error": "ollama_unavailable" | "bad_input" | "bridge_error"}
The question never appears on the command line. backend/ml modules are imported read-only;
copilot.load() is replaced by the data that arrived on stdin (the database is the source of
truth for status and analyst, not backend/ml/output).
"""
import contextlib
import json
import sys
import urllib.error
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[2] / "ml"
MODES = ("copilot", "welcome", "summarize")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run(mode: str, data: dict) -> dict:
    if mode not in MODES:
        return {"ok": False, "error": "bad_input"}
    if str(ML_DIR) not in sys.path:
        sys.path.insert(0, str(ML_DIR))
    # Anything the ML modules print goes to stderr so stdout stays one JSON line.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            if mode == "summarize":
                import summarize
                incident = data.get("incident")
                if not isinstance(incident, dict):
                    return {"ok": False, "error": "bad_input"}
                return {"ok": True, "result": summarize.summarize(incident)}
            import copilot
            incidents, reports = data.get("incidents"), data.get("reports")
            if not isinstance(incidents, list) or not isinstance(reports, dict):
                return {"ok": False, "error": "bad_input"}
            copilot.load = lambda: (incidents, reports)
            if mode == "welcome":
                return {"ok": True, "result": copilot.welcome()}
            question = data.get("question")
            if not isinstance(question, str) or not question.strip():
                return {"ok": False, "error": "bad_input"}
            return {"ok": True, "result": copilot.answer(question)}
        except (urllib.error.URLError, ConnectionError):
            return {"ok": False, "error": "ollama_unavailable"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "bridge_error", "error_type": type(exc).__name__}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        _emit({"ok": False, "error": "bad_input"})
        return 2
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except ValueError:
        _emit({"ok": False, "error": "bad_input"})
        return 2
    outcome = run(argv[1], data)
    try:
        _emit(outcome)
    except (TypeError, ValueError):
        _emit({"ok": False, "error": "bridge_error", "error_type": "UnserializableResult"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
