import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

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


class DeliveryStop(Location):
    """A delivery location with an integer load for the CVRP path."""

    demand: int = Field(default=1, ge=0, le=10_000)


class Vehicle(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    capacity: int = Field(..., gt=0, le=100_000)

    @field_validator("id", "name")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    model_config = ConfigDict(extra="forbid")


class OptimizeRequest(BaseModel):
    depot: Location
    stops: List[DeliveryStop] = Field(..., min_length=1, max_length=MAX_OPTIMIZATION_STOPS)
    vehicles: Optional[List[Vehicle]] = Field(default=None, min_length=1, max_length=12)
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
        if self.vehicles:
            vehicle_ids = [vehicle.id for vehicle in self.vehicles]
            if len(set(vehicle_ids)) != len(vehicle_ids):
                raise ValueError("vehicles must not contain duplicate ids")
            if sum(stop.demand for stop in self.stops) > sum(vehicle.capacity for vehicle in self.vehicles):
                raise ValueError("total vehicle capacity is below total delivery demand")
            if any(stop.demand > max(vehicle.capacity for vehicle in self.vehicles) for stop in self.stops):
                raise ValueError("a delivery demand exceeds every vehicle capacity")
            if self.algorithms and "qaoa" in self.algorithms:
                raise ValueError("qaoa is currently verified for single-vehicle TSP only; use OR-Tools CVRP for fleet runs")
        return self

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


class FleetRouteSchema(BaseModel):
    vehicle_id: str
    vehicle_name: str
    capacity: int
    load: int
    route: List[int]
    distance_meters: float


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
    # Persisted request inputs allow the UI to restore a completed route after
    # an API/browser restart instead of displaying a stale mock dashboard.
    stops: List[DeliveryStop] = Field(default_factory=list)
    distance_metric: Optional[str] = None
    fleet_routes: List[FleetRouteSchema] = Field(default_factory=list)
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


class WarmStartDeliveryAssignment(BaseModel):
    """One position-aware delivery for the experimental SDVRP warm-start."""

    vehicle_id: int = Field(..., ge=0, le=3)
    route_position: int = Field(..., ge=1, le=16)
    customer_id: int = Field(..., ge=0, le=15)
    quantity: float = Field(..., gt=0, le=100_000)

    model_config = ConfigDict(extra="forbid")


class QuantumWarmStartRequest(BaseModel):
    """Bounded input for the experimental QAOA+ local-improvement sandbox.

    The caller supplies a validated classical seed.  This endpoint deliberately
    supports only local simulation or a deterministic classical control run;
    it never submits an IBM job from a dashboard action.
    """

    matrix: List[List[float]] = Field(..., min_length=2, max_length=16)
    demands: List[float] = Field(..., min_length=2, max_length=16)
    capacities: List[float] = Field(..., min_length=1, max_length=4)
    starting_nodes: List[int] = Field(..., min_length=1, max_length=4)
    routes: Dict[str, List[int]] = Field(..., min_length=1, max_length=4)
    deliveries: List[WarmStartDeliveryAssignment] = Field(default_factory=list, max_length=64)
    problem_type: Literal["cvrp", "sdvrp"] = "cvrp"
    executor: Literal["classical", "local", "qudora"] = "local"
    reps: int = Field(default=1, ge=1, le=2)
    maxiter: int = Field(default=20, ge=1, le=40)
    shots: int = Field(default=512, ge=16, le=2048)
    max_candidates: int = Field(default=8, ge=2, le=10)
    neighborhood_size: int = Field(default=6, ge=1, le=8)
    polishing_iterations: int = Field(default=10, ge=0, le=20)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    initialization: Literal["no-op", "w-state"] = "w-state"
    xy_topology: Literal["ring", "full", "star"] = "ring"
    qudora_backend: Literal["Qamelion", "QVLS-Q1 Emulator"] = "Qamelion"
    qudora_timeout_seconds: int = Field(default=60, ge=1, le=90)
    measurement_error_probability: Optional[float] = Field(default=None, ge=0, le=1)
    two_qubit_gate_noise_strength: Optional[float] = Field(default=None, ge=0, le=1)
    single_qubit_gate_noise_strength: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def warm_start_shape_must_be_small_and_consistent(self):
        node_count = len(self.matrix)
        if any(len(row) != node_count for row in self.matrix):
            raise ValueError("matrix must be square")
        if len(self.demands) != node_count:
            raise ValueError("demands must have one value per matrix node")
        if len(self.capacities) != len(self.starting_nodes):
            raise ValueError("capacities and starting_nodes must have the same length")
        expected_routes = {str(index) for index in range(len(self.capacities))}
        if set(self.routes) != expected_routes:
            raise ValueError("routes must contain exactly one route for every vehicle ID")
        return self

    model_config = ConfigDict(extra="forbid")


class QuantumWarmStartResponse(BaseModel):
    """Execution evidence for the bounded QAOA+ warm-start experiment."""

    mode: Literal["experimental_quantum_warm_start"] = "experimental_quantum_warm_start"
    result: Dict[str, Any]


class QudoraConnectionResponse(BaseModel):
    status: str
    env_file_present: bool
    token_configured: bool
    worker_configured: bool
    message: str
    backends: List[Dict[str, Optional[str]]] = Field(default_factory=list)
