"""Admin-only ML pipeline routes. Every route requires the admin role.

Jobs share ONE lock with CSV ingestion (409 if any job is running). Generated files in
backend/ml/output/ are read-only input; nothing here edits or deletes them.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app import jobs
from app.security import CurrentUser, require_role
from app.services import ml_loader, pipeline

router = APIRouter(prefix="/admin/pipeline", tags=["admin-pipeline"])

_START = dict(audit_prefix="pipeline", failure_label="pipeline failed", audit_start=True)


@router.post("/run")
def run_pipeline_route(
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    record = jobs.start_job("pipeline_run", {"force": force, "dry_run": dry_run}, user.id,
                            lambda: pipeline.run_and_load(force=force, dry_run=dry_run),
                            background_tasks, **_START)
    return jobs.job_public(record)


@router.post("/load-existing")
def load_existing_route(
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    dry_run: bool = Query(False),
    user: CurrentUser = Depends(require_role("admin")),
):
    try:
        pipeline.preflight()
    except (ml_loader.MissingOutputError, ml_loader.InconsistentOutputError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    record = jobs.start_job("pipeline_load", {"force": force, "dry_run": dry_run}, user.id,
                            lambda: pipeline.load_existing(force=force, dry_run=dry_run),
                            background_tasks, **_START)
    return jobs.job_public(record)


@router.get("/runs")
def list_runs_route(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_role("admin")),
):
    return pipeline.list_runs(limit, offset)


@router.get("/runs/{run_id}")
def get_run_route(run_id: uuid.UUID, user: CurrentUser = Depends(require_role("admin"))):
    row = pipeline.get_run(str(run_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/jobs/{job_id}")
def get_job_route(job_id: str, user: CurrentUser = Depends(require_role("admin"))):
    record = jobs.get_job(job_id)
    if record is None or not record.kind.startswith("pipeline"):
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs.job_public(record)
