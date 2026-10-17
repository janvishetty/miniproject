"""Register / login / me / logout, backed by Supabase Auth.

Supabase Auth stores the email + password hash. Our `profiles` table stores the
rest (name, username, position, ROLE). The role is always decided on the server.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app import audit, database
from app.config import get_settings
from app.constants import DEFAULT_ROLE, POSITIONS
from app.rate_limit import limiter
from app.security import CurrentUser, bearer_scheme, get_current_user, load_profile, profile_to_user

log = logging.getLogger("fsia.auth")

# The Supabase client library renamed its error module between versions.
# AUTH_ERRORS = "the library says these credentials are wrong".
try:  # newer versions
    from supabase_auth.errors import AuthApiError  # type: ignore
    AUTH_ERRORS: tuple = (AuthApiError,)
except ImportError:
    try:  # older versions
        from gotrue.errors import AuthApiError  # type: ignore
        AUTH_ERRORS = (AuthApiError,)
    except ImportError:  # cannot tell errors apart -> treat every failure as bad credentials
        AUTH_ERRORS = (Exception,)

router = APIRouter(prefix="/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")


# ----------------------------- request / response models -----------------------------
class RegisterRequest(BaseModel):
    # extra="ignore": unknown fields such as "role" are silently dropped.
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    position: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-30 characters: letters, digits, _ . -")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("position")
    @classmethod
    def _position(cls, v: str) -> str:
        if v not in POSITIONS:
            raise ValueError("position must be one of: " + ", ".join(POSITIONS))
        return v


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        # same normalisation as RegisterRequest, so "Test@Example.com" can log in
        return v.strip().lower()


class ProfileOut(BaseModel):
    id: str
    name: str | None = None
    username: str | None = None
    email: str | None = None
    position: str | None = None
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    profile: ProfileOut


# ----------------------------------- helpers -----------------------------------
def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _is_duplicate_email(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "").lower()
    msg = str(exc).lower()
    return code == "email_exists" or ("already" in msg and "regist" in msg)


def _is_unique_violation(exc: Exception) -> bool:
    return str(getattr(exc, "code", "")) == "23505" or "duplicate key" in str(exc).lower()


def _profile_out(user: CurrentUser) -> ProfileOut:
    return ProfileOut(id=user.id, name=user.name, username=user.username,
                      email=user.email, position=user.position, role=user.role)


# ------------------------------------ routes ------------------------------------
@router.post("/register", status_code=201, response_model=ProfileOut)
@limiter.limit("10/minute")
def register(request: Request, body: RegisterRequest):
    db = database.get_admin_client()

    taken = db.table("profiles").select("id").eq("username", body.username).limit(1).execute()
    if taken.data:
        raise HTTPException(status_code=409, detail="Username is already taken")

    # 1) create the Supabase Auth user
    try:
        created = db.auth.admin.create_user({
            "email": body.email,
            "password": body.password,
            "email_confirm": get_settings().AUTO_CONFIRM_EMAIL,
            "user_metadata": {"full_name": body.name},
        })
    except Exception as exc:  # noqa: BLE001
        if _is_duplicate_email(exc):
            raise HTTPException(status_code=409, detail="An account with this email already exists") from None
        log.warning("create_user failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Could not create the account right now") from None

    user_id = str(created.user.id)

    # 2) create our profile. Role is FORCED here; the request body cannot change it.
    try:
        db.table("profiles").insert({
            "id": user_id,
            "full_name": body.name,
            "username": body.username,
            "email": body.email,
            "position": body.position,
            "role": DEFAULT_ROLE,
        }).execute()
    except Exception as exc:  # noqa: BLE001
        # roll back the auth user so we never leave an account without a profile
        try:
            db.auth.admin.delete_user(user_id)
        except Exception as cleanup_exc:  # noqa: BLE001
            log.error("cleanup of auth user failed (%s)", type(cleanup_exc).__name__)
        if _is_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Username is already taken") from None
        log.error("profile insert failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Could not create the account right now") from None

    audit.write(user_id, "auth.register", "profile", user_id, {"ip": _client_ip(request)})
    return ProfileOut(id=user_id, name=body.name, username=body.username,
                      email=body.email, position=body.position, role=DEFAULT_ROLE)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest):
    generic = HTTPException(status_code=401, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        # fresh anon client: signing in must not touch the admin client's session
        result = database.new_anon_client().auth.sign_in_with_password(
            {"email": body.email, "password": body.password})
    except AUTH_ERRORS as exc:
        status = getattr(exc, "status", None)
        if isinstance(status, int) and status >= 500:       # Supabase itself is failing
            log.error("sign-in service error (status %s)", status)
            raise HTTPException(status_code=503, detail="Authentication service unavailable") from None
        audit.write(None, "auth.login_failed", details={"ip": _client_ip(request)})
        raise generic from None
    except Exception as exc:  # noqa: BLE001  (network problem etc.)
        log.error("sign-in service error (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from None

    session = getattr(result, "session", None)
    auth_user = getattr(result, "user", None)
    if session is None or auth_user is None:
        audit.write(None, "auth.login_failed", details={"ip": _client_ip(request)})
        raise generic

    profile = load_profile(str(auth_user.id))
    if profile is None:
        raise HTTPException(status_code=403, detail="Account profile not found. Contact an administrator.")

    user = profile_to_user(profile)
    audit.write(user.id, "auth.login", "profile", user.id, {"ip": _client_ip(request)})
    return LoginResponse(access_token=session.access_token,
                         expires_in=getattr(session, "expires_in", None),
                         profile=_profile_out(user))


@router.get("/me", response_model=ProfileOut)
def me(user: CurrentUser = Depends(get_current_user)):
    return _profile_out(user)


@router.post("/logout")
def logout(request: Request,
           user: CurrentUser = Depends(get_current_user),
           creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    """Best-effort: ask Supabase to end the session, then drop the token client-side."""
    try:
        if creds is not None:
            database.get_admin_client().auth.admin.sign_out(creds.credentials)
    except Exception as exc:  # noqa: BLE001
        log.warning("remote sign-out failed (%s)", type(exc).__name__)
    audit.write(user.id, "auth.logout", "profile", user.id, {"ip": _client_ip(request)})
    return {"status": "logged_out"}
