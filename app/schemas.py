import os
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Classical OR-Tools runs remain useful on a small real-geography demo set.
# Quantum validation is intentionally governed by the separate, much smaller
# MAX_QAOA_STOPS limit below.
MAX_OPTIMIZATION_STOPS = max(1, int(os.environ.get("MAX_OPTIMIZATION_STOPS", "15")))
MAX_QAOA_STOPS = min(
    MAX_OPTIMIZATION_STOPS,
    max(1, int(os.environ.get("MAX_QAOA_STOPS", "3"))),
)
ALLOWED_ALGORITHMS = {"nearest_neighbor", "or_tools", "qaoa"}


class Location(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, example="Pelabuhan")
    lat: float = Field(..., ge=-90, le=90, example=16.0650)
    lon: float = Field(..., ge=-180, le=180, example=108.2200)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    model_config = ConfigDict(extra="forbid")


class OptimizeRequest(BaseModel):
    depot: Location
    stops: List[Location] = Field(..., min_length=1, max_length=MAX_OPTIMIZATION_STOPS)
    # Optional solver selection for comparison runs.
    # Allowed: nearest_neighbor, or_tools, qaoa.
    # QAOA is restricted to MAX_QAOA_STOPS small-TSP instances.
    algorithms: Optional[List[str]] = Field(
        default=None,
        max_length=len(ALLOWED_ALGORITHMS),
        example=["nearest_neighbor", "or_tools", "qaoa"],
    )

    @field_validator("algorithms")
    @classmethod
    def algorithms_must_be_known_and_unique(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return values
        normalized = [value.strip().lower() for value in values]
        unknown = set(normalized) - ALLOWED_ALGORITHMS
        if unknown:
            raise ValueError(f"unsupported algorithms: {', '.join(sorted(unknown))}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("algorithms must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def qaoa_scope_must_fit_the_verified_encoding(self):
        if self.algorithms and "qaoa" in self.algorithms and len(self.stops) > MAX_QAOA_STOPS:
            raise ValueError(
                f"qaoa is validated for at most {MAX_QAOA_STOPS} stops per run"
            )
        return self

    # This endpoint is deliberately a single-depot TSP contract. Rejecting
    # unknown fields prevents a frontend from silently pretending that a
    # vehicles/fleet payload was optimized as a VRP.
    model_config = ConfigDict(extra="forbid")


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

    model_config = ConfigDict(from_attributes=True)


class QuantumJobSchema(BaseModel):
    job_id: str
    algorithm: str
    backend_name: str
    status: str
    qpu_time_seconds: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    results: List[BenchmarkResultSchema] = Field(default_factory=list)
    quantum_jobs: List[QuantumJobSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class InspectPipelineStage(BaseModel):
    step: int
    name: str
    module: str
    description: str


class InspectRecentRun(BaseModel):
    run_id: str
    status: str
    depot_name: str
    stops_count: int
    created_at: datetime
    updated_at: datetime


class InspectResponse(BaseModel):
    service: str
    version: str
    environment: str
    quantum_backend: str
    database: str
    pipeline: List[InspectPipelineStage]
    endpoints: List[str]
    recent_runs: List[InspectRecentRun]
    notes: List[str]


class QuantumConnectionResponse(BaseModel):
    """Safe, token-free result for the IBM Quantum connectivity check."""

    status: str
    env_file_present: bool
    token_configured: bool
    token_variable: Optional[str] = None
    backend_name: Optional[str] = None
    backend_qubits: Optional[int] = None
    message: str
