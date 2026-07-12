"""
main.py — QUASAR FastAPI Application Entry Point

Quantum-Accelerated Supply-chain And Routing API.
Implements the non-blocking async optimization pipeline with full
security hardening, observability, and production-grade middleware stack.

Author: Team 23 (QC4SG Hackathon 2026)
Security & Architecture: Trịnh Hoàng Tú
"""

import os
import uuid
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# App Modules
from app.database import engine, get_db
import app.models as models
import app.schemas as schemas
from app.services.quantum_driver import run_optimization_pipeline

# Middleware — Security, Rate Limiting, Observability
from app.middleware.security import (
    SecurityHeadersMiddleware,
    RequestSizeLimitMiddleware,
    ErrorSanitizationMiddleware,
)
from app.middleware.rate_limiter import RateLimitMiddleware
from app.middleware.observability import (
    RequestTracingMiddleware,
    setup_structured_logging,
    logger,
)


# ---------------------------------------------------------------------------
# Application Lifespan — startup/shutdown events
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager.
    - Startup: Initialize DB schema, configure logging, validate environment.
    - Shutdown: Graceful cleanup.
    """
    # --- Startup ---
    # Initialize structured logging before anything else
    setup_structured_logging()
    logger.info("QUASAR API starting up...")

    # Create database tables
    models.Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized.")

    # Ensure static directory exists for Folium maps
    os.makedirs("static/maps", exist_ok=True)

    # Log environment configuration (without secrets)
    env = os.environ.get("QUASAR_ENV", "production")
    logger.info(
        "Environment: %s | Rate Limit: %s req/%ss | Optimize Burst: %s req/%ss",
        env,
        os.environ.get("RATE_LIMIT_MAX_REQUESTS", "20"),
        os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"),
        os.environ.get("OPTIMIZE_BURST_LIMIT", "5"),
        os.environ.get("OPTIMIZE_BURST_WINDOW", "60"),
    )

    # Check IBM Quantum connectivity
    token = os.environ.get("IBM_QUANTUM_TOKEN") or os.environ.get("QISKIT_IBM_TOKEN")
    if token:
        logger.info("IBM Quantum token detected — hardware QPU pipeline enabled.")
    else:
        logger.warning(
            "No IBM_QUANTUM_TOKEN set — falling back to local StatevectorSampler."
        )

    logger.info("QUASAR API is ready to serve requests.")
    yield

    # --- Shutdown ---
    logger.info("QUASAR API shutting down gracefully...")


# ---------------------------------------------------------------------------
# FastAPI Application Instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="QUASAR API",
    description=(
        "Quantum-Accelerated Supply-chain And Routing API — "
        "A classical-quantum hybrid logistics orchestration system for "
        "NP-hard Vehicle Routing Problems (VRP) and TSP."
    ),
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Middleware Stack (order matters — outermost first, innermost last)
#
# Request flow:
#   Client → ErrorSanitization → SecurityHeaders → RequestSizeLimit
#        → RateLimit → RequestTracing → CORS → Route Handler
# ---------------------------------------------------------------------------

# 1. Error sanitization (outermost — catches all unhandled exceptions)
app.add_middleware(ErrorSanitizationMiddleware)

# 2. Security headers (OWASP hardening on every response)
app.add_middleware(SecurityHeadersMiddleware)

# 3. Request size limit (reject oversized payloads early)
app.add_middleware(RequestSizeLimitMiddleware)

# 4. Rate limiting (protect quantum resources from abuse)
app.add_middleware(RateLimitMiddleware)

# 5. Request tracing (correlation ID + structured logging + perf metrics)
app.add_middleware(RequestTracingMiddleware)

# 6. CORS — configured via environment variable
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-Ms", "X-RateLimit-Remaining"],
)

# Mount static maps folder to serve Folium HTML maps
os.makedirs("static/maps", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ===========================================================================
# API Routes
# ===========================================================================


@app.get("/", status_code=status.HTTP_200_OK)
def read_root():
    """Root endpoint — API welcome message."""
    return {
        "message": "Welcome to QUASAR (Quantum-Accelerated Supply-chain And Routing) API",
        "version": "1.1.0",
        "docs_url": "/docs",
        "health_url": "/health",
        "status": "Healthy",
    }


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Health check endpoint for Docker HEALTHCHECK, load balancers, and monitoring.

    Returns system status including:
      - API server health
      - Database connectivity
      - IBM Quantum backend availability
      - Environment configuration
    """
    # Check database connectivity
    db_healthy = True
    try:
        db = next(get_db())
        db.execute(models.BenchmarkRun.__table__.select().limit(1))
        db.close()
    except Exception:
        db_healthy = False

    # Check quantum backend config
    token = os.environ.get("IBM_QUANTUM_TOKEN") or os.environ.get("QISKIT_IBM_TOKEN")
    quantum_mode = "ibm_hardware" if token else "local_simulator"

    health_status = "healthy" if db_healthy else "degraded"

    return {
        "status": health_status,
        "service": "quasar-api",
        "version": "1.1.0",
        "checks": {
            "database": "connected" if db_healthy else "unreachable",
            "quantum_backend": quantum_mode,
            "environment": os.environ.get("QUASAR_ENV", "production"),
        },
    }


@app.post(
    "/api/v1/optimize",
    response_model=schemas.OptimizeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def optimize_route(
    request: schemas.OptimizeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a route optimization request.

    Triggers the full classical-quantum hybrid pipeline asynchronously:
      1. Distance matrix computation (OSMnx / Haversine fallback)
      2. Classical warm-start (Google OR-Tools)
      3. QAOA optimization (IBM QPU / Simulator)
      4. QAI+HOBO optimization (3-temperature annealing)

    Returns immediately with a run_id for polling.
    """
    run_id = str(uuid.uuid4())

    # Persist the pending run
    try:
        new_run = models.BenchmarkRun(
            id=run_id,
            status="PENDING",
            depot_name=request.depot.name,
            depot_lat=request.depot.lat,
            depot_lon=request.depot.lon,
            stops_count=len(request.stops),
            stops_data=json.dumps([s.dict() for s in request.stops]),
        )
        db.add(new_run)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to create optimization run: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create optimization run. Please try again.",
        )

    # Trigger non-blocking quantum-classical optimization pipeline
    background_tasks.add_task(
        run_optimization_pipeline,
        run_id=run_id,
        depot=request.depot.dict(),
        stops=[s.dict() for s in request.stops],
    )

    logger.info("Optimization run %s submitted with %d stops.", run_id[:8], len(request.stops))

    return schemas.OptimizeResponse(
        run_id=run_id,
        status="PENDING",
        message="Optimization pipeline triggered successfully on IBM Quantum (with simulator fallback).",
    )


@app.get(
    "/api/v1/optimize/{run_id}",
    response_model=schemas.RunStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    """
    Poll the status and results of an optimization run.

    Returns full benchmark results including:
      - Algorithm tours and distances
      - Validation status
      - Approximation ratios relative to OR-Tools baseline
      - Quantum job metadata (job IDs, QPU time, backend info)
    """
    run = db.query(models.BenchmarkRun).filter(models.BenchmarkRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization run with ID {run_id} not found.",
        )

    # Serialize results
    results_schema = [
        schemas.BenchmarkResultSchema(
            algorithm=r.algorithm,
            tour=json.loads(r.tour),
            distance_meters=r.distance_meters,
            is_valid=r.is_valid,
            validation_error=r.validation_error,
            approximation_ratio=r.approximation_ratio,
            execution_time_ms=r.execution_time_ms,
            created_at=r.created_at,
        )
        for r in run.results
    ]

    jobs_schema = [
        schemas.QuantumJobSchema(
            job_id=j.job_id,
            algorithm=j.algorithm,
            backend_name=j.backend_name,
            status=j.status,
            qpu_time_seconds=j.qpu_time_seconds,
            created_at=j.created_at,
        )
        for j in run.quantum_jobs
    ]

    return schemas.RunStatusResponse(
        run_id=run.id,
        status=run.status,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_message=run.error_message,
        depot_name=run.depot_name,
        depot_lat=run.depot_lat,
        depot_lon=run.depot_lon,
        stops_count=run.stops_count,
        results=results_schema,
        quantum_jobs=jobs_schema,
    )
