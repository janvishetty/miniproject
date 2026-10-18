"""Incident list / detail / events / update. Any authenticated role may read; the role rules for
PATCH are enforced in incident_store.update_incident. All reads use the CURRENT pipeline run."""
import uuid
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.security import CurrentUser, get_current_user
from app.services import incident_store as store

router = APIRouter(prefix="/incidents", tags=["incidents"])

ExternalId = Path(pattern=store.EXTERNAL_ID_PATTERN)
Severity = Literal["critical", "high", "medium", "low"]
Status = Literal["OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED"]
Vector = Literal["Account Takeover", "Credential Stuffing", "Brute Force", "Suspicious Login",
                 "Transaction Anomaly"]


class IncidentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    analyst_id: uuid.UUID | None = None


@router.get("")
def list_incidents(
    severity: Severity | None = None,
    status: Status | None = None,
    vector: Vector | None = None,
    search: str | None = Query(None, max_length=100),
    sort: Literal["risk_score", "started_at", "confidence"] = "risk_score",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    run = store.current_run()
    return store.list_incidents(run["id"], severity, status, vector, (search or "").strip() or None,
                                sort, order == "desc", page, page_size)


@router.get("/{external_id}")
def get_incident(external_id: str = ExternalId, user: CurrentUser = Depends(get_current_user)):
    return store.incident_detail(store.current_run()["id"], external_id)


@router.get("/{external_id}/events")
def get_incident_events(
    external_id: str = ExternalId,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    return store.incident_events(store.current_run()["id"], external_id, page, page_size)


@router.patch("/{external_id}")
def patch_incident(external_id: str = ExternalId, body: IncidentPatch = Body(...),
                   user: CurrentUser = Depends(get_current_user)):
    fields = set(body.model_fields_set)
    if not fields:
        raise HTTPException(status_code=422, detail="Send status and/or analyst_id")
    return store.update_incident(store.current_run()["id"], external_id, user, fields,
                                 body.status, body.analyst_id)
