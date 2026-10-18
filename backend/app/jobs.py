"""In-memory job store and the ONE lock shared by ingestion and pipeline jobs.

Only one job (of any kind) runs at a time: a second request gets 409. State lives
in this process only, so it is lost on restart and only holds with one uvicorn
worker. Row values never go into logs, audit entries or error text.
"""
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException

from app import audit

log = logging.getLogger("fsia.jobs")


class JobFailure(Exception):
    """Raised by a runner to fail its job with a safe, readable message
    (and optionally a partial report). The message must hold no row values."""

    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.public_message = message
        self.report = report


@dataclass
class JobRecord:
    id: str
    kind: str
    params: dict
    actor_id: str | None
    status: str = "running"  # running | completed | failed
    report: dict | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None


_lock = threading.Lock()
_jobs: dict[str, JobRecord] = {}
_active_job_id: str | None = None


def reset() -> None:
    global _active_job_id
    with _lock:
        _jobs.clear()
        _active_job_id = None


def get_job(job_id: str) -> JobRecord | None:
    return _jobs.get(job_id)


def job_public(record: JobRecord) -> dict:
    return {
        "job_id": record.id,
        "kind": record.kind,
        "params": record.params,
        "status": record.status,
        "report": record.report,
        "error": record.error,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
    }


def audit_details(record: JobRecord) -> dict:
    """Numbers and names only: kind, status, params, per-table counts, outcome, step exit codes."""
    details = {"kind": record.kind, "status": record.status, "params": record.params}
    report = record.report or {}
    if report.get("tables"):
        details["tables"] = [
            {"table": t["table"], "rows_read": t["rows_read"],
             "rows_written": t["rows_written"], "rejected_count": t["rejected_count"]}
            for t in report["tables"]
        ]
    if report.get("outcome"):
        details["outcome"] = report["outcome"]
    if report.get("steps"):
        details["steps"] = [{"step": s["name"], "exit_code": s["exit_code"]} for s in report["steps"]]
    return details


def _run_job(job_id: str, runner, audit_prefix: str, failure_label: str) -> None:
    global _active_job_id
    record = _jobs[job_id]
    try:
        record.report = runner()
        record.status = "completed"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        if isinstance(exc, JobFailure):
            record.error = exc.public_message
            record.report = exc.report
        else:
            record.error = f"{type(exc).__name__}: {failure_label}"
        log.error("%s job %s (%s) failed: %s", audit_prefix, job_id, record.kind, type(exc).__name__)
    finally:
        record.finished_at = datetime.now(timezone.utc).isoformat()
        audit.write(record.actor_id, f"{audit_prefix}.job_finished", f"{audit_prefix}_job", job_id,
                    audit_details(record))
        with _lock:
            if _active_job_id == job_id:
                _active_job_id = None


def start_job(kind: str, params: dict, actor_id: str, runner, background_tasks: BackgroundTasks,
              audit_prefix: str = "ingest", failure_label: str = "ingestion failed",
              audit_start: bool = False) -> JobRecord:
    global _active_job_id
    with _lock:
        if _active_job_id is not None and _jobs[_active_job_id].status == "running":
            raise HTTPException(status_code=409,
                                detail="Another ingestion or pipeline job is already running")
        job_id = str(uuid.uuid4())
        record = JobRecord(id=job_id, kind=kind, params=params, actor_id=actor_id)
        _jobs[job_id] = record
        _active_job_id = job_id
    if audit_start:
        audit.write(actor_id, f"{audit_prefix}.job_started", f"{audit_prefix}_job", job_id,
                    {"kind": kind, "params": params})
    background_tasks.add_task(_run_job, job_id, runner, audit_prefix, failure_label)
    return record
