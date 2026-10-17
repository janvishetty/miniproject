from fastapi import APIRouter, Depends

from app.security import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def admin_ping(user: CurrentUser = Depends(require_role("admin"))):
    """Proves role-based authorization works. Reused as the model for Step 2 routes."""
    return {"status": "ok", "role": user.role}
