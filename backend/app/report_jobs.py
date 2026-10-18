"""In-memory report-generation jobs with their OWN one-at-a-time lock.

Separate from app/jobs.py (the ingestion/pipeline lock) and from the Copilot lock. A second
request while one runs gets 429 "report generation busy". State lives in this process only.
Errors are {code, message} with a fixed set of codes and no row values:
  ai_unavailable | timeout | unverified | stale_run | error
"""
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException

from app import audit

log = logging.getLogger("fsia.reports")

MESSAGES = {
    "ai_unavailable": "AI service unavailable - start Ollama",
    "timeout": "AI service timed out",
    "unverified": "report could not be verified",
    "stale_run": "the pipeline run changed; reload and try again",
    "error": "report generation failed",
}


class ReportFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if code in MESSAGES else "error"


@dataclass
class ReportJob:
    id: str
    external_id: str
    actor_id: str
    status: str = "running"            # running | completed | failed
    error: dict | None = None
    result: dict | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None


_lock = threading.Lock()
_jobs: dict[str, ReportJob] = {}
_active: str | None = None


def reset() -> None:
    global _active
    with _lock:
        _jobs.clear()
        _active = None


def get_job(job_id: str) -> ReportJob | None:
    return _jobs.get(job_id)


def public(job: ReportJob) -> dict:
    return {"job_id": job.id, "incident_id": job.external_id, "status": job.status,
            "error": job.error, "result": job.result, "started_at": job.started_at,
            "finished_at": job.finished_at}


def _run(job_id: str, runner) -> None:
    global _active
    job = _jobs[job_id]
    try:
        job.result = runner()
        job.status = "completed"
    except Exception as exc:  # noqa: BLE001
        code = exc.code if isinstance(exc, ReportFailure) else "error"
        job.status = "failed"
        job.error = {"code": code, "message": MESSAGES[code]}
        log.error("report job %s failed (%s)", job_id, type(exc).__name__)
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
        audit.write(job.actor_id, "report.job_finished", "report_job", job_id,
                    {"incident": job.external_id, "status": job.status,
                     "error_code": (job.error or {}).get("code"),
                     "source": (job.result or {}).get("source")})
        with _lock:
            if _active == job_id:
                _active = None


def start(external_id: str, actor_id: str, runner, background_tasks: BackgroundTasks) -> ReportJob:
    global _active
    with _lock:
        if _active is not None and _jobs[_active].status == "running":
            raise HTTPException(status_code=429, detail="report generation busy")
        job = ReportJob(id=str(uuid.uuid4()), external_id=external_id, actor_id=actor_id)
        _jobs[job.id] = job
        _active = job.id
    background_tasks.add_task(_run, job.id, runner)
    return job
