"""Rate limiter (per client IP). Applied to routes with @limiter.limit("5/minute").

Note: behind a proxy/load balancer every request can look like it comes from the
proxy. Step 5 (deployment) configures trusted proxy headers.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
