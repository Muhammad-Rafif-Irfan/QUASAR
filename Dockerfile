# =============================================================================
# QUASAR — Production Docker Image
# Multi-stage build for minimal attack surface and optimized image size.
#
# Author: Trịnh Hoàng Tú (System Architecture & DevSecOps)
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — Install dependencies in an isolated layer
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system-level build dependencies for scipy, numpy, ortools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime — Minimal production image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Security: Run as non-root user
RUN groupadd -r quasar && useradd --no-log-init -r -g quasar quasar

WORKDIR /app

# Install minimal runtime system dependencies (GDAL/spatial libs for OSMnx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY core/ ./core/
COPY services/ ./services/
COPY requirements.txt .

# Create necessary directories with correct ownership
RUN mkdir -p /app/static/maps /app/cache && \
    chown -R quasar:quasar /app

# Switch to non-root user
USER quasar

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QUASAR_ENV=production \
    RATE_LIMIT_MAX_REQUESTS=20 \
    RATE_LIMIT_WINDOW_SECONDS=60 \
    OPTIMIZE_BURST_LIMIT=5 \
    MAX_REQUEST_BODY_KB=512

# Health check — verifies the FastAPI server is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose default Uvicorn port
EXPOSE 8000

# Production ASGI server with sensible defaults:
# - 4 workers for multi-core utilization
# - 120s timeout for quantum pipeline execution (QPU queue can be slow)
# - Access log disabled (handled by structured logging middleware)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--timeout-keep-alive", "120", \
     "--no-access-log"]
