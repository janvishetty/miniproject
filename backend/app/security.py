"""Authentication + authorization dependencies.

get_current_user  -> reads "Authorization: Bearer <token>", asks Supabase if the
                     token is valid, then loads the user's profile (and ROLE)
                     from our own database.
require_role(...) -> 403 unless the user's role is in the allowed list.

401 = "we don't know who you are" (missing / bad / expired token)
403 = "we know who you are, but you may not do this"

Routes are plain `def` (not async) so FastAPI runs them in a thread pool;
the Supabase client is synchronous and would otherwise block the server.
"""
import logging

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app import database
from app.constants import ROLES

log = logging.getLogger("fsia.security")

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    id: str
    email: str | None = None
    name: str | None = None
    username: str | None = None
    position: str | None = None
    role: str


def _unauthorized(message: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=message,
                         headers={"WWW-Authenticate": "Bearer"})


def load_profile(user_id: str) -> dict | None:
    res = (database.get_admin_client().table("profiles")
           .select("id,full_name,username,email,position,role")
           .eq("id", user_id).limit(1).execute())
    return res.data[0] if res.data else None


def profile_to_user(profile: dict) -> CurrentUser:
    return CurrentUser(
        id=str(profile["id"]),
        email=profile.get("email"),
        name=profile.get("full_name"),
        username=profile.get("username"),
        position=profile.get("position"),
        role=profile.get("role") or "analyst",
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise _unauthorized()
    try:
        result = database.get_token_verifier().auth.get_user(creds.credentials)
        auth_user = getattr(result, "user", None)
    except Exception:  # invalid, expired or tampered token
        raise _unauthorized("Invalid or expired token") from None
    if auth_user is None:
        raise _unauthorized("Invalid or expired token")

    profile = load_profile(str(auth_user.id))
    if profile is None:
        raise HTTPException(status_code=403, detail="Account profile not found")
    return profile_to_user(profile)


def require_role(*allowed_roles: str):
    """Usage:  user: CurrentUser = Depends(require_role("admin"))"""
    unknown = set(allowed_roles) - set(ROLES)
    if unknown or not allowed_roles:
        raise ValueError(f"require_role got invalid roles: {sorted(unknown) or 'none given'}")

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403,
                                detail="You do not have permission to perform this action")
        return user

    return dependency
