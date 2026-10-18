"""Admin-only CSV ingestion into Supabase. Every route requires the admin role.

Only one job (ingestion or pipeline) may run at a time (409 if one is already running).
Jobs run as FastAPI background tasks; poll GET /admin/ingest/jobs/{job_id}
for status. Row values never appear in logs, audit entries, or error bodies.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app import jobs
from app.security import CurrentUser, require_role
from app.services import ingestion

router = APIRouter(prefix="/admin/ingest", tags=["admin-ingest"])

_VALID_SOURCES = ("auth", "api", "transaction", "all")


@router.post("/reference")
def ingest_reference_route(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    def runner():
        return ingestion.combine_results(ingestion.ingest_reference(dry_run=dry_run))

    record = jobs.start_job("reference", {"dry_run": dry_run}, user.id, runner, background_tasks)
    return jobs.job_public(record)


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

    record = jobs.start_job("events", {"source": source, "dry_run": dry_run}, user.id, runner,
                            background_tasks)
    return jobs.job_public(record)


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

    record = jobs.start_job("all", {"dry_run": dry_run}, user.id, runner, background_tasks)
    return jobs.job_public(record)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser = Depends(require_role("admin"))):
    record = jobs.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs.job_public(record)


@router.get("/summary")
def ingest_summary(user: CurrentUser = Depends(require_role("admin"))):
    return ingestion.summary()
