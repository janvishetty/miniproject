"""Copilot limits: 10 questions per minute per user, and one Copilot call at a time.

In-memory (one uvicorn worker). The one-at-a-time lock is separate from the report lock and
from the ingestion/pipeline lock.
"""
import math
import threading
import time
from collections import deque
from contextlib import contextmanager

from fastapi import HTTPException

RATE_LIMIT = 10
WINDOW_SECONDS = 60.0

_hits: dict[str, deque] = {}
_hits_lock = threading.Lock()
_busy = threading.Lock()


def reset() -> None:
    global _busy
    with _hits_lock:
        _hits.clear()
    _busy = threading.Lock()


def check_rate(user_id: str) -> None:
    now = time.monotonic()
    with _hits_lock:
        window = _hits.setdefault(user_id, deque())
        while window and now - window[0] >= WINDOW_SECONDS:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            retry = max(1, math.ceil(WINDOW_SECONDS - (now - window[0])))
            raise HTTPException(status_code=429, detail="Too many Copilot questions. Please wait a moment.",
                                headers={"Retry-After": str(retry)})
        window.append(now)


@contextmanager
def exclusive():
    if not _busy.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="copilot busy")
    try:
        yield
    finally:
        _busy.release()
