import os
import uuid
import json
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

# App Modules
from app.database import engine, get_db
import app.models as models
import app.schemas as schemas
from app.services.quantum_driver import run_optimization_pipeline

# Create database tables automatically
models.Base.metadata.create_all(bind=engine)

# Create static directory to serve Folium maps
os.makedirs("static/maps", exist_ok=True)

app = FastAPI(
    title="QUASAR API",
    description="Quantum-Accelerated Supply-chain And Routing API",
    version="1.0.0"
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
