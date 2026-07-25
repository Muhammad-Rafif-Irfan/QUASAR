from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Location(BaseModel):
    name: str = Field(..., example="Pelabuhan")
    lat: float = Field(..., example=16.0650)
    lon: float = Field(..., example=108.2200)

class OptimizeRequest(BaseModel):
    depot: Location
    stops: List[Location] = Field(..., min_items=1)

class OptimizeResponse(BaseModel):
    run_id: str
    status: str
    message: str

class BenchmarkResultSchema(BaseModel):
    algorithm: str
    tour: List[int]
    distance_meters: float
    is_valid: bool
    validation_error: Optional[str] = None
    approximation_ratio: Optional[float] = None
    execution_time_ms: float
    created_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True

class QuantumJobSchema(BaseModel):
    job_id: str
    algorithm: str
    backend_name: str
    status: str
    qpu_time_seconds: Optional[float] = None
    created_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True

class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    depot_name: str
    depot_lat: float
    depot_lon: float
    stops_count: int
    results: List[BenchmarkResultSchema] = []
    quantum_jobs: List[QuantumJobSchema] = []

    class Config:
        orm_mode = True
        from_attributes = True


# ── Benchmark Suite Schemas ──────────────────────────────────────────────

class AlgorithmResult(BaseModel):
    """Result for a single algorithm at a given problem size."""
    distance_meters: float
    execution_time_ms: float
    tour: List[int]
    is_valid: bool
    approximation_ratio: float = 1.0


class BenchmarkEntry(BaseModel):
    """Comparison entry for one problem size N."""
    n: int
    or_tools: AlgorithmResult
    qaoa: AlgorithmResult
    qai_hobo: AlgorithmResult


class SDGImpactMetrics(BaseModel):
    """UN SDG 11 — Sustainable Cities impact metrics."""
    total_km_naive: float
    total_km_optimized: float
    km_saved: float
    km_saved_pct: float
    co2_saved_kg: float
    fuel_saved_liters: float
    deliveries_optimized: int


class BenchmarkSuiteResponse(BaseModel):
    """Full benchmark suite result returned to the frontend."""
    id: str
    status: str
    backend_name: str
    created_at: datetime
    entries: List[BenchmarkEntry] = []
    sdg_metrics: Optional[SDGImpactMetrics] = None
    honest_assessment: str = ""

    class Config:
        orm_mode = True
        from_attributes = True
