"""One JSON error shape for the whole API:

    {"error": {"code": "...", "message": "...", "details": [...]}}

Never contains stack traces, SQL, or the values the user sent.
"""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

import logging

log = logging.getLogger("fsia.errors")

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def error_response(status: int, message: str, details=None, headers=None) -> JSONResponse:
    body = {"error": {"code": _CODES.get(status, "server_error" if status >= 500 else "error"),
                      "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return error_response(exc.status_code, str(exc.detail), headers=getattr(exc, "headers", None))


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Only field name + message. We deliberately drop "input" so a rejected
    # password is never echoed back or logged.
    details = [
        {
            "field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
            "message": e["msg"],
        }
        for e in exc.errors()
    ]
    return error_response(422, "Request validation failed", details=details)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return error_response(429, "Too many requests. Please wait a moment and try again.",
                          headers={"Retry-After": "60"})


async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log only the exception TYPE and path (messages can contain user data).
    log.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
    return error_response(500, "Internal server error")
