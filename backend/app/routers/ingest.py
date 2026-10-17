"""Admin-only CSV ingestion into Supabase. Every route requires the admin role.

Only one ingestion job may run at a time (409 if one is already running).
Jobs run as FastAPI background tasks; poll GET /admin/ingest/jobs/{job_id}
for status. Row values never appear in logs, audit entries, or error bodies.
"""
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app import audit
from app.security import CurrentUser, require_role
from app.services import ingestion

log = logging.getLogger("fsia.ingest")

router = APIRouter(prefix="/admin/ingest", tags=["admin-ingest"])

_VALID_SOURCES = ("auth", "api", "transaction", "all")


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


def _job_public(record: JobRecord) -> dict:
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


def _audit_details(record: JobRecord) -> dict:
    """Numbers only: kind, status, params and per-table counts. No row values."""
    details = {"kind": record.kind, "status": record.status, "params": record.params}
    if record.report:
        details["tables"] = [
            {"table": t["table"], "rows_read": t["rows_read"],
             "rows_written": t["rows_written"], "rejected_count": t["rejected_count"]}
            for t in record.report["tables"]
        ]
    return details


def _run_job(job_id: str, runner) -> None:
    global _active_job_id
    record = _jobs[job_id]
    try:
        record.report = runner()
        record.status = "completed"
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = f"{type(exc).__name__}: ingestion failed"
        log.error("ingest job %s (%s) failed: %s", job_id, record.kind, type(exc).__name__)
    finally:
        record.finished_at = datetime.now(timezone.utc).isoformat()
        audit.write(record.actor_id, "ingest.job_finished", "ingest_job", job_id,
                    _audit_details(record))
        with _lock:
            if _active_job_id == job_id:
                _active_job_id = None


def _start_job(kind: str, params: dict, actor_id: str, runner,
               background_tasks: BackgroundTasks) -> JobRecord:
    global _active_job_id
    with _lock:
        if _active_job_id is not None and _jobs[_active_job_id].status == "running":
            raise HTTPException(status_code=409, detail="An ingestion job is already running")
        job_id = str(uuid.uuid4())
        record = JobRecord(id=job_id, kind=kind, params=params, actor_id=actor_id)
        _jobs[job_id] = record
        _active_job_id = job_id
    background_tasks.add_task(_run_job, job_id, runner)
    return record


@router.post("/reference")
def ingest_reference_route(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    def runner():
        return ingestion.combine_results(ingestion.ingest_reference(dry_run=dry_run))

    record = _start_job("reference", {"dry_run": dry_run}, user.id, runner, background_tasks)
    return _job_public(record)


@router.post("/events")
def ingest_events_route(
    background_tasks: BackgroundTasks,
    source: str = Query("all"),
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    if source not in _VALID_SOURCES:
        raise HTTPException(status_code=422, detail="source must be one of: " + ", ".join(_VALID_SOURCES))

    def runner():
        raw_result = ingestion.ingest_raw_events(source=source, dry_run=dry_run)
        events_result = ingestion.ingest_events(source=source, dry_run=dry_run)
        return ingestion.combine_results([raw_result, events_result])

    record = _start_job("events", {"source": source, "dry_run": dry_run}, user.id, runner, background_tasks)
    return _job_public(record)


@router.post("/all")
def ingest_all_route(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    def runner():
        ref_results = ingestion.ingest_reference(dry_run=dry_run)
        raw_result = ingestion.ingest_raw_events(source="all", dry_run=dry_run)
        events_result = ingestion.ingest_events(source="all", dry_run=dry_run)
        return ingestion.combine_results([*ref_results, raw_result, events_result])

    record = _start_job("all", {"dry_run": dry_run}, user.id, runner, background_tasks)
    return _job_public(record)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser = Depends(require_role("admin"))):
    record = _jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_public(record)


@router.get("/summary")
def ingest_summary(user: CurrentUser = Depends(require_role("admin"))):
    return ingestion.summary()
