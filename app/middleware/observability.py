"""
observability.py — Structured Logging & Request Tracing for QUASAR

Implements:
  1. Correlation ID injection (X-Request-ID) for distributed tracing
  2. Structured JSON logging for all HTTP requests
  3. Performance monitoring (response time tracking)
  4. Quantum pipeline execution time logging

Every request gets a unique correlation ID that propagates through the
entire async pipeline — from API receipt through quantum execution to
DB write — enabling full end-to-end trace reconstruction.

Author: Trịnh Hoàng Tú (System Architecture & Security Hardening)
"""

import os
import time
import uuid
import logging
import json
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ---------------------------------------------------------------------------
# Context Variable — correlation ID available across async boundaries
# ---------------------------------------------------------------------------
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Retrieve the current request's correlation ID from async context."""
    return _correlation_id.get()


# ---------------------------------------------------------------------------
# Structured Logger Configuration
# ---------------------------------------------------------------------------
ENVIRONMENT = os.environ.get("QUASAR_ENV", "production")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class StructuredJsonFormatter(logging.Formatter):
    """
    Outputs log records as single-line JSON for machine parsing.
    Includes correlation_id, timestamp, level, module, and message.

    Designed for consumption by log aggregation tools (ELK, CloudWatch, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": _correlation_id.get() or None,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Include extra fields if attached
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        return json.dumps(log_entry, default=str)


def setup_structured_logging():
    """
    Configure the root logger with structured JSON output.
    Call this once at application startup.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Remove existing handlers to avoid duplicate output
    root_logger.handlers.clear()

    handler = logging.StreamHandler()

    if ENVIRONMENT == "development":
        # Human-readable format for local development
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s | %(name)-25s | "
            "cid=%(correlation_id)s | %(message)s",
            datefmt="%H:%M:%S",
        )

        # Inject correlation_id into all log records via a filter
        class CorrelationFilter(logging.Filter):
            def filter(self, record):
                record.correlation_id = _correlation_id.get() or "-"
                return True

        handler.addFilter(CorrelationFilter())
        handler.setFormatter(formatter)
    else:
        # Structured JSON for production
        handler.setFormatter(StructuredJsonFormatter())

    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Application Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("quasar.api")


# ---------------------------------------------------------------------------
# Request Tracing Middleware
# ---------------------------------------------------------------------------
class RequestTracingMiddleware(BaseHTTPMiddleware):
    """
    Injects a unique correlation ID into every request lifecycle:

    1. Checks for incoming X-Request-ID header (from upstream proxy/gateway)
    2. Generates a new UUID4 if not present
    3. Sets it in ContextVar for downstream async access
    4. Attaches it to the response headers for client-side tracing
    5. Logs request metadata (method, path, status, duration)

    Performance metrics are logged as structured data for alerting/dashboards.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID
        correlation_id = (
            request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id")
            or str(uuid.uuid4())
        )
        _correlation_id.set(correlation_id)

        # Record start time
        start_time = time.perf_counter()

        # Extract client info
        client_ip = self._get_client_ip(request)
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else None

        # Log incoming request
        logger.info(
            "Request received: %s %s",
            method,
            path,
            extra={"extra_data": {
                "client_ip": client_ip,
                "query": query,
                "user_agent": request.headers.get("user-agent", "unknown"),
            }},
        )

        # Execute request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Attach correlation ID to response
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        # Log response with performance metrics
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "Response: %s %s → %d (%.2fms)",
            method,
            path,
            response.status_code,
            duration_ms,
            extra={"extra_data": {
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
            }},
        )

        # Performance alert: log slow requests
        if duration_ms > 5000:  # > 5 seconds
            logger.warning(
                "SLOW REQUEST detected: %s %s took %.2fms",
                method,
                path,
                duration_ms,
            )

        return response

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Extract real client IP respecting X-Forwarded-For."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Pipeline Performance Logger (used by quantum_driver)
# ---------------------------------------------------------------------------
class PipelineMetrics:
    """
    Lightweight performance tracker for the optimization pipeline stages.
    Logs timing for each stage and total pipeline execution.

    Usage in quantum_driver:
        metrics = PipelineMetrics(run_id)
        metrics.stage_start("distance_matrix")
        ...
        metrics.stage_end("distance_matrix")
        metrics.finalize()
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.pipeline_start = time.perf_counter()
        self._stages: dict[str, dict] = {}
        self._current_stage: Optional[str] = None
        self._logger = logging.getLogger("quasar.pipeline")

    def stage_start(self, stage_name: str):
        """Mark the start of a pipeline stage."""
        self._current_stage = stage_name
        self._stages[stage_name] = {"start": time.perf_counter(), "end": None}
        self._logger.info(
            "[%s] Stage started: %s",
            self.run_id[:8],
            stage_name,
        )

    def stage_end(self, stage_name: str):
        """Mark the end of a pipeline stage and log duration."""
        if stage_name in self._stages:
            self._stages[stage_name]["end"] = time.perf_counter()
            duration = (
                self._stages[stage_name]["end"] - self._stages[stage_name]["start"]
            ) * 1000.0
            self._stages[stage_name]["duration_ms"] = duration
            self._logger.info(
                "[%s] Stage completed: %s (%.2fms)",
                self.run_id[:8],
                stage_name,
                duration,
            )

    def finalize(self):
        """Log total pipeline execution summary."""
        total_ms = (time.perf_counter() - self.pipeline_start) * 1000.0
        stage_summary = {
            name: f"{data.get('duration_ms', 0):.1f}ms"
            for name, data in self._stages.items()
        }
        self._logger.info(
            "[%s] Pipeline COMPLETED — Total: %.2fms | Stages: %s",
            self.run_id[:8],
            total_ms,
            json.dumps(stage_summary),
        )

    def fail(self, error: str):
        """Log pipeline failure."""
        total_ms = (time.perf_counter() - self.pipeline_start) * 1000.0
        self._logger.error(
            "[%s] Pipeline FAILED after %.2fms — Error: %s",
            self.run_id[:8],
            total_ms,
            error,
        )
