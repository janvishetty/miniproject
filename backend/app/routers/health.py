from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import database

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness: is the server up? Does not touch the database."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db():
    """Can the server reach Supabase? Returns only ok / unavailable (no details)."""
    try:
        database.get_admin_client().table("pipeline_runs").select("id").limit(1).execute()
    except Exception:  # noqa: BLE001  (details intentionally hidden)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}
