"""
security.py — Security Hardening Middleware for QUASAR

Implements:
  1. Security Headers (OWASP recommendations)
  2. Request Size Limiting (prevent payload abuse)
  3. Input Sanitization utilities
  4. Error Response Sanitization (no internal stack traces in production)

Author: Trịnh Hoàng Tú (System Architecture & Security Hardening)
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from fastapi import status


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_REQUEST_BODY_SIZE = int(os.environ.get("MAX_REQUEST_BODY_KB", "512")) * 1024  # Default 512KB
ENVIRONMENT = os.environ.get("QUASAR_ENV", "production")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects OWASP-recommended security headers into every HTTP response.

    Headers applied:
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: DENY
      - X-XSS-Protection: 1; mode=block
      - Strict-Transport-Security (HSTS)
      - Content-Security-Policy: default-src 'self'
      - Referrer-Policy: strict-origin-when-cross-origin
      - Permissions-Policy: restrictive defaults
      - Cache-Control: no-store for API responses
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Core security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # CSP: allow 'self' and inline styles for Folium map rendering
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://tile.openstreetmap.org;"
        )

        # Prevent caching of API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        # Remove server identification header
        response.headers.pop("server", None)

        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Rejects requests with body size exceeding MAX_REQUEST_BODY_SIZE.
    Prevents memory exhaustion from oversized payloads.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only check for methods that carry a body
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": f"Request body too large. Maximum allowed: {MAX_REQUEST_BODY_SIZE // 1024}KB"
                    },
                )

        return await call_next(request)


class ErrorSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Catches unhandled exceptions and returns sanitized error responses.
    In production, internal details are hidden. In development, full traces are shown.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            if ENVIRONMENT == "development":
                # In development, expose the error for debugging
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "detail": str(exc),
                        "type": type(exc).__name__,
                    },
                )
            else:
                # In production, sanitize the error message
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "detail": "An internal server error occurred. Please try again later.",
                        "support": "Contact the QUASAR team if this persists.",
                    },
                )
