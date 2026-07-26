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

from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

# App Modules
from app.database import engine, get_db
import app.models as models
import app.schemas as schemas
from app.services.quantum_driver import run_optimization_pipeline
from app.services.quantum_hybrid.warm_start import run_quasar_qaoa_xy_hybrid
from app.services.quantum_hybrid.qudora import check_connection as check_qudora_connection

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
    # ``create_all`` does not add columns to existing SQLite demo databases.
    # Keep this additive migration local, idempotent, and safe for old runs.
    if engine.dialect.name == "sqlite":
        columns = {column["name"] for column in inspect(engine).get_columns("benchmark_runs")}
        with engine.begin() as connection:
            if "distance_metric" not in columns:
                connection.execute(text("ALTER TABLE benchmark_runs ADD COLUMN distance_metric VARCHAR"))
            if "fleet_routes" not in columns:
                connection.execute(text("ALTER TABLE benchmark_runs ADD COLUMN fleet_routes TEXT"))
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
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
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
    "/api/v1/quantum/connection-check",
    response_model=schemas.QuantumConnectionResponse,
    status_code=status.HTTP_200_OK,
)
def check_quantum_connection():
    """Verify IBM Quantum credentials without returning or logging a token.

    This intentionally performs a small read-only IBM Runtime request. It does
    not submit a circuit or consume QPU time; a real QPU run still happens only
    through the bounded QAOA optimization endpoint.
    """
    env_file_present = os.path.isfile(".env")
    token_variable = next(
        (
            name
            for name in ("IBM_QUANTUM_TOKEN", "QISKIT_IBM_TOKEN")
            if os.environ.get(name)
        ),
        None,
    )
    if token_variable is None:
        return schemas.QuantumConnectionResponse(
            status="not_configured",
            env_file_present=env_file_present,
            token_configured=False,
            message=(
                "No IBM Quantum token is available to this API process. "
                "Copy .env.example to .env, configure one token, then restart the API."
            ),
        )

    try:
        from qiskit_ibm_runtime import QiskitRuntimeService

        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ[token_variable],
        )
        backends = service.backends(operational=True, simulator=False)
        if not backends:
            return schemas.QuantumConnectionResponse(
                status="connected_no_backend",
                env_file_present=env_file_present,
                token_configured=True,
                token_variable=token_variable,
                message="IBM Quantum accepted the token, but no operational hardware backend is currently available.",
            )

        backend = min(backends, key=lambda candidate: candidate.status().pending_jobs)
        return schemas.QuantumConnectionResponse(
            status="connected",
            env_file_present=env_file_present,
            token_configured=True,
            token_variable=token_variable,
            backend_name=backend.name,
            backend_qubits=backend.num_qubits,
            message="IBM Quantum connection verified. No circuit was submitted.",
        )
    except Exception:
        logger.warning("IBM Quantum connection check failed", exc_info=True)
        return schemas.QuantumConnectionResponse(
            status="connection_failed",
            env_file_present=env_file_present,
            token_configured=True,
            token_variable=token_variable,
            message="IBM Quantum could not verify this token or fetch an operational backend. Check the token and account access.",
        )


@app.post(
    "/api/v1/quantum/qudora/connection-check",
    response_model=schemas.QudoraConnectionResponse,
    status_code=status.HTTP_200_OK,
)
def check_qudora_cloud_connection():
    """Read-only QUDORA backend discovery through the isolated SDK worker."""
    return schemas.QudoraConnectionResponse(**check_qudora_connection())


@app.get(
    "/api/v1/inspect",
    response_model=schemas.InspectResponse,
    status_code=status.HTTP_200_OK,
)
def inspect_runtime(db: Session = Depends(get_db)):
    """
    Runtime inspection — how the live app is wired and what it recently did.

    Use this (or ``scripts/inspect.ps1``) to understand the request pipeline
    without reading the whole codebase.
    """
    token = os.environ.get("IBM_QUANTUM_TOKEN") or os.environ.get("QISKIT_IBM_TOKEN")
    quantum_mode = "ibm_hardware" if token else "local_simulator"

    db_status = "connected"
    recent: list[schemas.InspectRecentRun] = []
    try:
        rows = (
            db.query(models.BenchmarkRun)
            .order_by(models.BenchmarkRun.created_at.desc())
            .limit(5)
            .all()
        )
        recent = [
            schemas.InspectRecentRun(
                run_id=r.id,
                status=r.status,
                depot_name=r.depot_name,
                stops_count=r.stops_count,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    except Exception:
        db_status = "unreachable"

    research_present = os.path.isdir("research/ibm_sdvrp")

    return schemas.InspectResponse(
        service="quasar-api",
        version="1.1.0",
        environment=os.environ.get("QUASAR_ENV", "production"),
        quantum_backend=quantum_mode,
        database=db_status,
        pipeline=[
            schemas.InspectPipelineStage(
                step=1,
                name="Accept request",
                module="app.main:/api/v1/optimize",
                description="Validate JSON, create BenchmarkRun, return run_id immediately (202).",
            ),
            schemas.InspectPipelineStage(
                step=2,
                name="Distance matrix",
                module="app.services.routing",
                description="OSMnx road network with a bounded deadline; Haversine fallback if OSM fails.",
            ),
            schemas.InspectPipelineStage(
                step=3,
                name="Classical warm-start",
                module="services.classical_solver.ORToolsSolver",
                description="OR-Tools baseline tour used for approximation ratio.",
            ),
            schemas.InspectPipelineStage(
                step=4,
                name="Quantum solvers",
                module="app.services.quantum_driver + core.small_tsp_qaoa",
                description="Cost-Hamiltonian QAOA for a verified small TSP (up to three stops), on IBM QPU when token set or local simulator.",
            ),
            schemas.InspectPipelineStage(
                step=5,
                name="Persist + map",
                module="app.models + app.services.routing.render_map",
                description="Write results/jobs to SQLite; Folium HTML under /static/maps.",
            ),
        ],
        endpoints=[
            "GET /",
            "GET /health",
            "GET /api/v1/inspect",
            "POST /api/v1/quantum/connection-check",
            "POST /api/v1/quantum/qudora/connection-check",
            "POST /api/v1/quantum/warm-start",
            "POST /api/v1/optimize",
            "GET /api/v1/optimize/latest",
            "GET /api/v1/optimize/history",
            "GET /api/v1/optimize/{run_id}",
            "DELETE /api/v1/app-data",
            "GET /docs",
            "GET /static/maps/{file}.html",
        ],
        recent_runs=recent,
        notes=[
            "Frontend (Vite) proxies /api and /health to this API on local demos.",
            "Experimental IBM SDVRP runners live under research/ibm_sdvrp and are NOT in this pipeline."
            if research_present
            else "research/ibm_sdvrp package not found in working directory.",
            "POST /api/v1/optimize accepts optional algorithms=[nearest_neighbor,or_tools,qaoa]; qaoa supports at most three stops.",
            "Poll GET /api/v1/optimize/{run_id} until status is COMPLETED or FAILED.",
        ],
    )


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
      3. Cost-Hamiltonian QAOA optimization for a verified small TSP (IBM QPU / Simulator)

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
        vehicles=[vehicle.dict() for vehicle in request.vehicles] if request.vehicles else None,
        algorithms=request.algorithms,
    )

    logger.info("Optimization run %s submitted with %d stops.", run_id[:8], len(request.stops))

    return schemas.OptimizeResponse(
        run_id=run_id,
        status="PENDING",
        message="Optimization pipeline accepted. Poll the run endpoint for verified results; QAOA uses IBM hardware only when a token is configured.",
    )


@app.post(
    "/api/v1/quantum/warm-start",
    response_model=schemas.QuantumWarmStartResponse,
    status_code=status.HTTP_200_OK,
)
def run_quantum_warm_start(
    request: schemas.QuantumWarmStartRequest,
):
    """Evaluate Aga's bounded QAOA+ move-selection experiment safely.

    This endpoint refines a caller-provided classical CVRP/SDVRP seed.  It is
    intentionally separate from delivery operations: IBM execution is refused,
    inputs are tightly bounded, and the solver returns the original seed unless
    an independently validated strict improvement is found.
    """
    payload = request.model_dump()
    payload["deliveries"] = [item.model_dump() for item in request.deliveries]
    if request.executor == "qudora":
        payload["runtime_options"] = {
            "backend_name": request.qudora_backend,
            "timeout_seconds": request.qudora_timeout_seconds,
            **{
                key: value
                for key, value in {
                    "measurement_error_probability": request.measurement_error_probability,
                    "two_qubit_gate_noise_strength": request.two_qubit_gate_noise_strength,
                    "single_qubit_gate_noise_strength": request.single_qubit_gate_noise_strength,
                }.items()
                if value is not None
            },
        }
    try:
        result = run_quasar_qaoa_xy_hybrid(payload)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        logger.warning("Quantum warm-start failed safely: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The experimental warm-start is temporarily unavailable.",
        ) from error

    return schemas.QuantumWarmStartResponse(result=result)


@app.get(
    "/api/v1/optimize/history",
    response_model=list[schemas.RunHistoryItem],
    status_code=status.HTTP_200_OK,
)
def get_completed_run_history(limit: int = 12, db: Session = Depends(get_db)):
    """Return compact metadata for recent completed runs.

    The per-run endpoint remains the source of full solver and quantum traces,
    avoiding an unnecessarily large dashboard response.
    """
    safe_limit = max(1, min(limit, 50))
    runs = (
        db.query(models.BenchmarkRun)
        .filter(models.BenchmarkRun.status == "COMPLETED")
        .order_by(models.BenchmarkRun.updated_at.desc())
        .limit(safe_limit)
        .all()
    )
    return [
        schemas.RunHistoryItem(
            run_id=run.id,
            stops_count=run.stops_count,
            depot_name=run.depot_name,
            distance_metric=run.distance_metric,
            updated_at=run.updated_at,
            results_count=len(run.results),
            quantum_jobs_count=len(run.quantum_jobs),
        )
        for run in runs
    ]


@app.get(
    "/api/v1/optimize/latest",
    response_model=schemas.RunStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_latest_completed_run(db: Session = Depends(get_db)):
    """Return the newest completed persisted run for dashboard restoration.

    The web client keeps only transient UI state, while SQLite survives an API
    restart.  This endpoint lets it re-hydrate evidence without treating an
    old run as a newly executed live request.
    """
    run = (
        db.query(models.BenchmarkRun)
        .filter(models.BenchmarkRun.status == "COMPLETED")
        .order_by(models.BenchmarkRun.updated_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed optimization run has been persisted yet.",
        )
    return get_run_status(run.id, db)


@app.delete(
    "/api/v1/app-data",
    response_model=schemas.AppDataResetResponse,
    status_code=status.HTTP_200_OK,
)
def clear_persisted_app_data(
    confirmation: str = Header(default="", alias="X-Confirm-Reset"),
    db: Session = Depends(get_db),
):
    """Permanently delete persisted benchmark runs and their result/job traces.

    The dashboard must opt in with an explicit confirmation header.  Deleting
    run ORM objects (rather than issuing a bulk SQL delete) preserves the
    declared result/job cascade on every supported database backend.
    """
    if confirmation != "DELETE_ALL_APP_DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit reset confirmation is required.",
        )
    try:
        runs = db.query(models.BenchmarkRun).all()
        for run in runs:
            db.delete(run)
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Failed to clear persisted app data")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not clear persisted app data.",
        ) from error
    return schemas.AppDataResetResponse(
        deleted_runs=len(runs),
        message="Persisted benchmark runs, results, and quantum job traces were deleted.",
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
        stops=[schemas.DeliveryStop(**item) for item in json.loads(run.stops_data or "[]")],
        distance_metric=run.distance_metric,
        fleet_routes=json.loads(run.fleet_routes) if run.fleet_routes else [],
        results=results_schema,
        quantum_jobs=jobs_schema,
    )
