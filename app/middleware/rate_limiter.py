"""
rate_limiter.py — Sliding Window Rate Limiter for QUASAR

Implements an in-memory sliding window rate limiter to protect the
quantum optimization endpoints from abuse and resource exhaustion.

The quantum pipeline is computationally expensive (QPU queue time, circuit
transpilation, etc.), so aggressive rate limiting is essential.

Author: Trịnh Hoàng Tú (System Architecture & Security Hardening)
"""

import os
import time
import threading
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi import status

# ---------------------------------------------------------------------------
# Configuration — tunable via environment variables
# ---------------------------------------------------------------------------
# Max requests per window per client IP
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "20"))
# Window size in seconds
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
# Burst limit for optimization endpoint (expensive operations)
OPTIMIZE_BURST_LIMIT = int(os.environ.get("OPTIMIZE_BURST_LIMIT", "5"))
OPTIMIZE_BURST_WINDOW = int(os.environ.get("OPTIMIZE_BURST_WINDOW", "60"))
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true"


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding window rate limiter using in-memory storage.

    For production horizontal scaling, replace with Redis-backed implementation.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    def is_allowed(self, client_id: str) -> tuple[bool, dict]:
        """
        Check if a request from client_id is allowed.

        Returns:
            (allowed: bool, metadata: dict with remaining/reset info)
        """
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            if now - self._last_cleanup >= self.window_seconds:
                stale_keys = [
                    key for key, timestamps in self._requests.items()
                    if not timestamps or timestamps[-1] < window_start
                ]
                for key in stale_keys:
                    del self._requests[key]
                self._last_cleanup = now
            self._requests[client_id] = [
                ts for ts in self._requests[client_id] if ts > window_start
            ]
            current_count = len(self._requests[client_id])

            if current_count >= self.max_requests:
                oldest_in_window = self._requests[client_id][0] if self._requests[client_id] else now
                reset_after = int(oldest_in_window + self.window_seconds - now) + 1
                return False, {
                    "remaining": 0,
                    "reset_after_seconds": reset_after,
                    "limit": self.max_requests,
                }

            self._requests[client_id].append(now)
            return True, {
                "remaining": self.max_requests - current_count - 1,
                "reset_after_seconds": self.window_seconds,
                "limit": self.max_requests,
            }

    def cleanup(self):
        """Remove stale entries to prevent memory leaks in long-running processes."""
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            stale_keys = [
                k for k, v in self._requests.items()
                if not v or v[-1] < window_start
            ]
            for k in stale_keys:
                del self._requests[k]


# ---------------------------------------------------------------------------
# Global limiter instances
# ---------------------------------------------------------------------------
_global_limiter = SlidingWindowRateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
_optimize_limiter = SlidingWindowRateLimiter(OPTIMIZE_BURST_LIMIT, OPTIMIZE_BURST_WINDOW)


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP, respecting X-Forwarded-For behind reverse proxies.
    """
    forwarded = request.headers.get("x-forwarded-for") if TRUST_PROXY_HEADERS else None
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Applies rate limiting to state-changing API endpoints, with a stricter
    limit on the expensive /api/v1/optimize POST endpoint. Read-only status
    polling is deliberately exempt so a client cannot rate-limit its own run.

    Response headers include rate limit metadata for client awareness:
      - X-RateLimit-Limit
      - X-RateLimit-Remaining
      - X-RateLimit-Reset
    """

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and static assets
        if request.url.path in ("/", "/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        if request.url.path.startswith("/static"):
            return await call_next(request)

        client_ip = _get_client_ip(request)
        global_meta = None

        # Stricter rate limit for optimization endpoint
        if request.url.path == "/api/v1/optimize" and request.method == "POST":
            allowed, meta = _optimize_limiter.is_allowed(f"optimize:{client_ip}")
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded for optimization endpoint. "
                                  "Quantum resources are limited — please wait before retrying.",
                        "retry_after_seconds": meta["reset_after_seconds"],
                    },
                    headers={
                        "Retry-After": str(meta["reset_after_seconds"]),
                        "X-RateLimit-Limit": str(meta["limit"]),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        # Global limit protects state-changing requests. GET status polling is
        # read-only and can occur frequently while a long optimization runs.
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            allowed, global_meta = _global_limiter.is_allowed(client_ip)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Too many requests. Please slow down.",
                        "retry_after_seconds": global_meta["reset_after_seconds"],
                    },
                    headers={
                        "Retry-After": str(global_meta["reset_after_seconds"]),
                        "X-RateLimit-Limit": str(global_meta["limit"]),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        # Proceed with the request
        response = await call_next(request)

        # Attach global rate-limit headers when a state-changing request was
        # admitted. Read-only endpoints do not consume this shared budget.
        if request.url.path.startswith("/api/") and global_meta is not None:
            response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_MAX_REQUESTS)
            response.headers["X-RateLimit-Remaining"] = str((global_meta or {}).get("remaining", 0))

        return response
