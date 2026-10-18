"""FastAPI application factory.

Run from the backend/ folder:   uvicorn app.main:app --reload
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.errors import (http_exception_handler, rate_limit_handler,
                        unhandled_exception_handler, validation_exception_handler)
from app.rate_limit import limiter
from app.routers import admin, auth, copilot, dashboard, health, incidents, ingest, pipeline, reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
access_log = logging.getLogger("fsia.access")
# httpx logs every Supabase request URL (they contain user ids): keep them out of the log.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def create_app() -> FastAPI:
    settings = get_settings()          # fails fast with a clear message if .env is wrong
    prod = settings.is_production

    app = FastAPI(
        title="FSIA / CirionSOC API",
        version="0.1.0",
        # API docs are for development only
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )

    app.state.limiter = limiter
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Bearer tokens travel in a header (no cookies), so credentials stay off.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def log_and_harden(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            access_log.error("%s %s -> 500 (unhandled)", request.method, request.url.path)
            raise
        ms = (time.perf_counter() - start) * 1000
        # Log method, path (no query string), status, time. NEVER headers or bodies.
        access_log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                        response.status_code, ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(ingest.router)
    app.include_router(pipeline.router)
    app.include_router(dashboard.router)
    app.include_router(incidents.router)
    app.include_router(reports.router)
    app.include_router(copilot.router)
    return app


app = create_app()
