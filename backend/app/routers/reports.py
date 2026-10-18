"""Incident reports. Any authenticated role.

POST /incidents/{id}/report starts a background job (its own one-at-a-time lock, 429 when
busy); GET /reports/jobs/{job_id} polls it (always 200). Only the user who started a job, or a
manager/admin, can read it; anyone else gets 404."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query

from app import report_jobs
from app.security import CurrentUser, get_current_user
from app.services import incident_store as store
from app.services import reports as report_service

router = APIRouter(tags=["reports"])
ExternalId = Path(pattern=store.EXTERNAL_ID_PATTERN)


@router.get("/reports")
def list_reports(page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
                 user: CurrentUser = Depends(get_current_user)):
    return store.list_reports(store.current_run()["id"], page, page_size)


@router.get("/reports/jobs/{job_id}")
def get_report_job(job_id: str, user: CurrentUser = Depends(get_current_user)):
    job = report_jobs.get_job(job_id)
    if job is None or (job.actor_id != user.id and user.role not in ("manager", "admin")):
        raise HTTPException(status_code=404, detail="Job not found")
    return report_jobs.public(job)


@router.get("/reports/{external_id}")
def get_report(external_id: str = ExternalId, user: CurrentUser = Depends(get_current_user)):
    return store.get_report(store.current_run()["id"], external_id)


@router.post("/incidents/{external_id}/report", status_code=202)
def start_report(background_tasks: BackgroundTasks, external_id: str = ExternalId,
                 user: CurrentUser = Depends(get_current_user)):
    store.get_incident_row(store.current_run()["id"], external_id, "id")      # 409 / 404 first
    job = report_jobs.start(external_id, user.id, lambda: report_service.generate(external_id),
                            background_tasks)
    return report_jobs.public(job)
