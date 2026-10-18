"""GET /dashboard: live incident counts + the current run's dashboard snapshot.
Any authenticated role."""
from fastapi import APIRouter, Depends

from app.security import CurrentUser, get_current_user
from app.services import incident_store

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(user: CurrentUser = Depends(get_current_user)):
    return incident_store.dashboard(incident_store.current_run())
