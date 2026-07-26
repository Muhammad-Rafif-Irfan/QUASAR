import os
import uuid
import json
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# App Modules
from app.database import engine, get_db
import app.models as models
import app.schemas as schemas
from app.services.quantum_driver import run_optimization_pipeline, run_benchmark_suite

# Create database tables automatically
models.Base.metadata.create_all(bind=engine)

# Create static directory to serve Folium maps
os.makedirs("static/maps", exist_ok=True)

app = FastAPI(
    title="QUASAR API",
    description="Quantum-Accelerated Supply-chain And Routing API",
    version="1.0.0"
)

# CORS — allow frontend dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static maps folder to serve HTML maps
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", status_code=status.HTTP_200_OK)
def read_root():
    return {
        "message": "Welcome to QUASAR (Quantum-Accelerated Supply-chain And Routing) API 🚀",
        "docs_url": "/docs",
        "status": "Healthy"
    }


@app.post("/api/v1/optimize", response_model=schemas.OptimizeResponse, status_code=status.HTTP_202_ACCEPTED)
def optimize_route(request: schemas.OptimizeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run_id = str(uuid.uuid4())
    
    # Save pending run in the DB
    try:
        new_run = models.BenchmarkRun(
            id=run_id,
            status="PENDING",
            depot_name=request.depot.name,
            depot_lat=request.depot.lat,
            depot_lon=request.depot.lon,
            stops_count=len(request.stops),
            stops_data=json.dumps([s.dict() for s in request.stops])
        )
        db.add(new_run)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create optimization run: {str(e)}"
        )
        
    # Trigger non-blocking quantum-classical optimization pipeline in a background task
    background_tasks.add_task(
        run_optimization_pipeline,
        run_id=run_id,
        depot=request.depot.dict(),
        stops=[s.dict() for s in request.stops]
    )
    
    return schemas.OptimizeResponse(
        run_id=run_id,
        status="PENDING",
        message="Optimization pipeline triggered successfully on IBM Quantum (with simulator fallback)."
    )


@app.get("/api/v1/optimize/{run_id}", response_model=schemas.RunStatusResponse, status_code=status.HTTP_200_OK)
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.BenchmarkRun).filter(models.BenchmarkRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization run with ID {run_id} not found."
        )
        
    # Serialize results to match schema requirements
    results_schema = []
    for r in run.results:
        results_schema.append(
            schemas.BenchmarkResultSchema(
                algorithm=r.algorithm,
                tour=json.loads(r.tour),
                distance_meters=r.distance_meters,
                is_valid=r.is_valid,
                validation_error=r.validation_error,
                approximation_ratio=r.approximation_ratio,
                execution_time_ms=r.execution_time_ms,
                created_at=r.created_at
            )
        )
        
    jobs_schema = []
    for j in run.quantum_jobs:
        jobs_schema.append(
            schemas.QuantumJobSchema(
                job_id=j.job_id,
                algorithm=j.algorithm,
                backend_name=j.backend_name,
                status=j.status,
                qpu_time_seconds=j.qpu_time_seconds,
                created_at=j.created_at
            )
        )
        
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
        quantum_jobs=jobs_schema
    )


# ═══════════════════════════════════════════════════════════════════════════
#  BENCHMARK SUITE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/benchmark", status_code=status.HTTP_202_ACCEPTED)
def start_benchmark(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Launch a full benchmark suite comparing OR-Tools and QAOA across N=4→8."""
    suite_id = str(uuid.uuid4())

    suite = models.BenchmarkSuite(
        id=suite_id,
        status="PENDING",
    )
    db.add(suite)
    db.commit()

    background_tasks.add_task(run_benchmark_suite, suite_id=suite_id)

    return {"suite_id": suite_id, "status": "PENDING", "message": "Benchmark suite started."}


@app.get("/api/v1/benchmark/latest", status_code=status.HTTP_200_OK)
def get_latest_benchmark(db: Session = Depends(get_db)):
    """Return the most recent completed benchmark suite, or empty response if none exist."""
    suite = (
        db.query(models.BenchmarkSuite)
        .filter(models.BenchmarkSuite.status == "COMPLETED")
        .order_by(models.BenchmarkSuite.created_at.desc())
        .first()
    )
    if not suite:
        return {"id": None, "status": "NONE", "backend_name": None, "created_at": None, "entries": [], "sdg_metrics": None, "honest_assessment": ""}

    entries = json.loads(suite.entries_json) if suite.entries_json else []
    sdg_metrics = json.loads(suite.sdg_metrics_json) if suite.sdg_metrics_json else None

    return {
        "id": suite.id,
        "status": suite.status,
        "backend_name": suite.backend_name,
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
        "entries": entries,
        "sdg_metrics": sdg_metrics,
        "honest_assessment": suite.honest_assessment or "",
    }


@app.get("/api/v1/benchmark/{suite_id}", status_code=status.HTTP_200_OK)
def get_benchmark_status(suite_id: str, db: Session = Depends(get_db)):
    """Poll benchmark suite status and results."""
    suite = db.query(models.BenchmarkSuite).filter(models.BenchmarkSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Benchmark suite not found.")

    entries = json.loads(suite.entries_json) if suite.entries_json else []
    sdg_metrics = json.loads(suite.sdg_metrics_json) if suite.sdg_metrics_json else None

    return {
        "id": suite.id,
        "status": suite.status,
        "backend_name": suite.backend_name,
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
        "entries": entries,
        "sdg_metrics": sdg_metrics,
        "honest_assessment": suite.honest_assessment or "",
        "error_message": suite.error_message,
    }
