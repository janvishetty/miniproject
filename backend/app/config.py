"""Application settings, read from environment variables / backend/.env.

The app refuses to start (with a clear message) if something required is
missing or still a placeholder. Secret VALUES are never printed.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]   # .../backend
REPO_ROOT = BACKEND_DIR.parent                       # .../miniproject


def _looks_like_placeholder(value: str) -> bool:
    v = value.strip().upper()
    return v.startswith(("PASTE", "YOUR_", "YOUR-", "CHANGE")) or "<" in v


class Settings(BaseSettings):
    # backend/.env is found via an absolute path, so it works from any folder.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: SecretStr
    SUPABASE_ANON_KEY: SecretStr

    APP_ENV: Literal["development", "production", "test"] = "development"
    CORS_ORIGINS: str = "http://localhost:5173"
    AUTO_CONFIRM_EMAIL: bool = True

    # Used from Step 2 onwards.
    DATA_DIR: Path = REPO_ROOT / "data"
    ML_OUTPUT_DIR: Path = REPO_ROOT / "backend" / "ml" / "output"
    ML_PYTHON: str = "python3"
    ML_STEP_TIMEOUT_SECONDS: int = Field(default=600, ge=10, le=3600)

    @field_validator("SUPABASE_URL")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if _looks_like_placeholder(v) or not v.startswith(("http://", "https://")):
            raise ValueError("must be your real Supabase project URL (starts with https://)")
        parts = urlsplit(v)
        if not parts.hostname or parts.path or parts.query or parts.fragment:
            # e.g. https://xyz.supabase.co/rest/v1/ -> the client adds /rest/v1 itself
            raise ValueError("must be the bare project URL like https://xyz.supabase.co "
                             "(no path such as /rest/v1, no query string)")
        return v

    @field_validator("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY")
    @classmethod
    def _check_key(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip()
        if not raw or _looks_like_placeholder(raw):
            raise ValueError("is empty or still a placeholder")
        return SecretStr(raw)

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _check_cors(cls, v: str) -> str:
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if not origins:
            raise ValueError("needs at least one origin")
        if "*" in origins:
            raise ValueError('"*" is not allowed; list the exact frontend origins')
        return ",".join(origins)

    @property
    def cors_origin_list(self) -> list[str]:
        return self.CORS_ORIGINS.split(",")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


def describe_errors(exc: ValidationError) -> str:
    """Readable list of problems: variable name + reason, never the value."""
    parts = []
    for err in exc.errors():
        name = ".".join(str(p) for p in err["loc"]) or "settings"
        parts.append(f"{name}: {err['msg']}")
    return "; ".join(parts)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError(
            "Invalid or missing configuration -> "
            + describe_errors(exc)
            + ". Copy backend/.env.example to backend/.env and fill it in."
        ) from None   # 'from None' stops pydantic from printing the bad values
