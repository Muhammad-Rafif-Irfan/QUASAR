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
