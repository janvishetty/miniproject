"""Glue for the /admin/pipeline routes: run the scripts, parse, load, list runs.

Settings used: ML_OUTPUT_DIR, ML_PYTHON, ML_STEP_TIMEOUT_SECONDS (config.py).
Reports use the same {"tables": [...]} shape as ingestion so the audit entry works unchanged.
"""
from __future__ import annotations

from pathlib import Path

from app import database
from app.config import BACKEND_DIR, REPO_ROOT, get_settings
from app.jobs import JobFailure
from app.services import ml_adapter, ml_loader

ML_DIR = BACKEND_DIR / "ml"

_RUN_COLUMNS = ("id,status,is_current,trigger,started_at,finished_at,events_scored,"
                "incident_count,error_message,notes,source_fingerprint")


def _output_dir() -> Path:
    return Path(get_settings().ML_OUTPUT_DIR)


def preflight() -> dict:
    """Parse and check the existing output (no database). Raises MissingOutputError /
    InconsistentOutputError; the routes turn those into 409."""
    return ml_loader.dry_parse(_output_dir())


def load_existing(force: bool = False, dry_run: bool = False) -> dict:
    try:
        if dry_run:
            return ml_loader.dry_parse(_output_dir())
        return ml_loader.load(_output_dir(), force=force)
    except (ml_loader.MissingOutputError, ml_loader.InconsistentOutputError) as exc:
        raise JobFailure(str(exc)) from None
    except ml_loader.LoadError as exc:
        raise JobFailure(exc.public_message, report={"run_id": exc.run_id, "tables": []}) from None


def run_and_load(force: bool = False, dry_run: bool = False) -> dict:
    settings = get_settings()
    try:
        interpreter = ml_adapter.resolve_interpreter(settings.ML_PYTHON)
        results = ml_adapter.run_pipeline(interpreter, ML_DIR, REPO_ROOT,
                                          settings.ML_STEP_TIMEOUT_SECONDS)
    except ml_adapter.AdapterError as exc:
        raise JobFailure(str(exc)) from None
    steps = [r.to_dict() for r in results]
    failed = next((r for r in results if not r.ok), None)
    if failed is not None:
        how = "timed out" if failed.timed_out else f"failed (exit code {failed.exit_code})"
        raise JobFailure(f"pipeline step {failed.name} {how}", report={"steps": steps, "tables": []})
    try:
        report = load_existing(force=force, dry_run=dry_run)
    except JobFailure as exc:
        exc.report = {**(exc.report or {"tables": []}), "steps": steps}
        raise
    report["steps"] = steps
    return report


def list_runs(limit: int, offset: int) -> dict:
    res = (database.get_admin_client().table("pipeline_runs")
           .select(_RUN_COLUMNS, count="exact")
           .order("started_at", desc=True).range(offset, offset + limit - 1).execute())
    return {"items": res.data or [], "total": res.count or 0, "limit": limit, "offset": offset}


def get_run(run_id: str) -> dict | None:
    res = (database.get_admin_client().table("pipeline_runs")
           .select(_RUN_COLUMNS).eq("id", run_id).limit(1).execute())
    return res.data[0] if res.data else None
