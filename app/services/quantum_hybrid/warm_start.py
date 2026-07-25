"""Standalone QUASAR Bottleneck-Targeted QAOA+ XY Hybrid algorithm.

The module refines a feasible classical CVRP/SDVRP seed.  It detects a measured
routing bottleneck, extracts a compact neighborhood, encodes feasible candidate
moves into an exact-one QAOA+ register, decodes sampled moves, applies bounded
classical polishing, and returns the seed unchanged unless the final solution is
feasible and strictly cheaper.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from time import perf_counter
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from .hamiltonian import (
    CandidateHamiltonian,
    build_candidate_hamiltonian,
    clean_bitstring,
    decode_one_hot_bitstring,
    evaluate_bitstring_energy,
    normalize_operator,
    pauli_terms,
)

ProblemType = Literal["cvrp", "sdvrp"]
Executor = Literal["classical", "local", "ibm"]
XYTopology = Literal["ring", "full", "star"]
Initialization = Literal["no-op", "w-state"]
SamplePolicy = Literal[
    "best_objective_valid",
    "lowest_energy_valid",
    "most_probable_valid",
]
NeighborhoodMode = Literal["bottleneck_targeted", "global_baseline"]
Routes = dict[str, list[int]]

_EPSILON = 1e-9


@dataclass(frozen=True)
class HybridConfig:
    """Validated standalone algorithm configuration."""

    executor: Executor = "local"
    reps: int = 1
    maxiter: int = 40
    shots: int = 1024
    max_candidates: int = 16
    neighborhood_size: int = 6
    neighborhood_mode: NeighborhoodMode = "bottleneck_targeted"
    move_types: tuple[str, ...] = (
        "swap",
        "relocate",
        "two_opt",
        "inter_route_swap",
        "split_merge",
    )
    initialization: Initialization = "no-op"
    xy_topology: XYTopology = "ring"
    sample_selection_policy: SamplePolicy = "best_objective_valid"
    random_seed: int = 42
    polishing_iterations: int = 20
    acceptance_epsilon: float = 0.0
    one_hot_penalty: float | None = None
    pairwise_interactions: Sequence[Sequence[float]] | None = None
    capacity_pressure_threshold: float = 0.90
    route_imbalance_threshold: float = 0.20
    stagnation_threshold: float = 0.001
    stagnation_window: int = 10
    search_history: tuple[float, ...] = ()
    runtime_options: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DeliveryAssignment:
    """Quantity delivered at one concrete route visit."""

    vehicle_id: int
    route_position: int
    customer_id: int
    quantity: float


@dataclass(frozen=True)
class RouteProblem:
    """CVRP/SDVRP input data."""

    matrix: np.ndarray
    demands: np.ndarray
    capacities: np.ndarray
    starting_nodes: tuple[int, ...]
    problem_type: ProblemType = "cvrp"

    @property
    def split_delivery(self) -> bool:
        """Backward-compatible property; ``problem_type`` is authoritative."""
        return self.problem_type == "sdvrp"

    @classmethod
    def from_data(
        cls,
        matrix: Sequence[Sequence[float]],
        demands: Sequence[float],
        capacities: Sequence[float],
        starting_nodes: Sequence[int],
        *,
        problem_type: ProblemType = "cvrp",
    ) -> "RouteProblem":
        if problem_type not in {"cvrp", "sdvrp"}:
            raise ValueError("problem_type must be 'cvrp' or 'sdvrp'.")

        distance = np.asarray(matrix, dtype=float)
        demand = np.asarray(demands, dtype=float)
        capacity = np.asarray(capacities, dtype=float)
        depots = tuple(int(node) for node in starting_nodes)

        if (
            distance.ndim != 2
            or distance.shape[0] != distance.shape[1]
            or len(distance) < 2
        ):
            raise ValueError(
                "matrix must be a square distance matrix with at least two nodes."
            )
        if len(demand) != len(distance):
            raise ValueError("demands must have one value per matrix node.")
        if len(capacity) == 0 or len(capacity) != len(depots):
            raise ValueError(
                "capacities and starting_nodes must contain one entry per vehicle."
            )
        if not (
            np.isfinite(distance).all()
            and np.isfinite(demand).all()
            and np.isfinite(capacity).all()
        ):
            raise ValueError("Problem values must be finite.")
        if np.any(distance < 0):
            raise ValueError("matrix values must be non-negative.")
        if np.any(demand < 0):
            raise ValueError("demands must be non-negative.")
        if np.any(capacity <= 0):
            raise ValueError("capacities must be positive.")
        if any(node < 0 or node >= len(distance) for node in depots):
            raise ValueError("Every starting node must exist in matrix.")
        if any(abs(float(demand[node])) > _EPSILON for node in set(depots)):
            raise ValueError("Depot nodes must have zero demand.")

        return cls(distance, demand, capacity, depots, problem_type)


@dataclass(frozen=True)
class Solution:
    """Route solution and optional position-aware SDVRP deliveries."""

    routes: Routes
    deliveries: tuple[DeliveryAssignment, ...] = ()


@dataclass(frozen=True)
class EvaluatedSolution:
    solution: Solution
    cost: float
    violations: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class Bottleneck:
    bottleneck_id: str
    bottleneck_type: str
    severity: float
    affected_nodes: tuple[int, ...]
    affected_vehicles: tuple[int, ...]
    critical_edges: tuple[tuple[int, int, int], ...]
    route_positions: tuple[tuple[int, int], ...]
    evidence: Mapping[str, Any]
    explanation: str


@dataclass(frozen=True)
class Neighborhood:
    bottleneck_id: str
    mode: NeighborhoodMode
    vehicles: tuple[int, ...]
    route_positions: tuple[tuple[int, tuple[int, ...]], ...]
    nodes: tuple[int, ...]
    critical_edges: tuple[tuple[int, int, int], ...]

    def positions_for(self, vehicle_id: int) -> tuple[int, ...]:
        return dict(self.route_positions).get(vehicle_id, ())


@dataclass(frozen=True)
class MoveCandidate:
    move_id: str
    move_type: str
    affected_nodes: tuple[int, ...]
    affected_vehicles: tuple[int, ...]
    parameters: tuple[tuple[str, Any], ...]
    estimated_delta_cost: float
    exact_delta_cost: float | None
    feasible_precheck: bool
    rejection_reason: str | None
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class SampleAnalysis:
    bitstring: str
    count: int
    probability: float
    hamming_weight: int
    one_hot_valid: bool
    selected_move: str | None
    energy: float
    route_cost: float | None
    feasible: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class QuantumExecutionResult:
    counts: Mapping[str, int]
    optimizer_parameters: tuple[float, ...]
    optimizer_history: tuple[Mapping[str, float | int], ...]
    optimizer_evaluations: int
    backend: str | None
    job_ids: tuple[str, ...]
    circuit_depth: int | None
    two_qubit_gate_count: int | None


@dataclass(frozen=True)
class PolishingResult:
    solution: Solution
    cost_before: float
    cost_after: float
    operations: tuple[Mapping[str, Any], ...]


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field} must be a boolean.")


def _copy_routes(value: Mapping[str | int, Sequence[int]]) -> Routes:
    return {
        str(vehicle): [int(node) for node in route]
        for vehicle, route in value.items()
    }


def _required_customers(problem: RouteProblem) -> list[int]:
    depots = set(problem.starting_nodes)
    return [node for node in range(len(problem.matrix)) if node not in depots]


def route_cost(solution: Solution, matrix: np.ndarray) -> float:
    return float(
        sum(
            matrix[left][right]
            for route in solution.routes.values()
            for left, right in zip(route, route[1:])
        )
    )


def _route_costs(solution: Solution, matrix: np.ndarray) -> list[float]:
    return [
        float(
            sum(
                matrix[left][right]
                for left, right in zip(route, route[1:])
            )
        )
        for _, route in sorted(
            solution.routes.items(), key=lambda item: int(item[0])
        )
    ]


def _route_shape_errors(
    problem: RouteProblem,
    solution: Solution,
) -> list[str]:
    errors: list[str] = []
    expected_keys = {
        str(vehicle) for vehicle in range(len(problem.capacities))
    }
    if set(solution.routes) != expected_keys:
        return ["Routes must contain exactly one route for every vehicle."]

    depots = set(problem.starting_nodes)
    for vehicle in range(len(problem.capacities)):
        route = solution.routes[str(vehicle)]
        depot = problem.starting_nodes[vehicle]
        if len(route) < 2 or route[0] != depot or route[-1] != depot:
            errors.append(
                f"Vehicle {vehicle} must start and end at depot {depot}."
            )
            continue
        for node in route[1:-1]:
            if node < 0 or node >= len(problem.matrix):
                errors.append(f"Vehicle {vehicle} contains an unknown node.")
                break
            if node in depots:
                errors.append(
                    f"Vehicle {vehicle} contains a depot inside its route."
                )
                break
    return errors


def validate_cvrp_solution(
    problem: RouteProblem,
    solution: Solution,
) -> list[str]:
    """Validate exact-once CVRP semantics."""
    errors = _route_shape_errors(problem, solution)
    if solution.deliveries:
        errors.append("CVRP does not accept delivery assignments.")

    seen: list[int] = []
    for vehicle in range(len(problem.capacities)):
        route = solution.routes.get(str(vehicle), [])
        customers = route[1:-1] if len(route) >= 2 else []
        seen.extend(customers)
        load = float(sum(problem.demands[node] for node in customers))
        if load > float(problem.capacities[vehicle]) + _EPSILON:
            errors.append(f"Vehicle {vehicle} exceeds capacity.")

    if sorted(seen) != sorted(_required_customers(problem)):
        errors.append("Every non-depot customer must appear exactly once.")
    return errors


def validate_sdvrp_solution(
    problem: RouteProblem,
    solution: Solution,
) -> list[str]:
    """Validate position-aware split-delivery semantics."""
    errors = _route_shape_errors(problem, solution)
    required = _required_customers(problem)
    required_set = set(required)
    delivered_by_customer = np.zeros(len(problem.demands), dtype=float)
    delivered_by_vehicle = np.zeros(len(problem.capacities), dtype=float)
    assignment_by_visit: dict[tuple[int, int], DeliveryAssignment] = {}

    for assignment in solution.deliveries:
        if assignment.vehicle_id < 0 or assignment.vehicle_id >= len(
            problem.capacities
        ):
            errors.append("Delivery assignment contains an unknown vehicle.")
            continue
        route = solution.routes.get(str(assignment.vehicle_id), [])
        if (
            assignment.route_position <= 0
            or assignment.route_position >= len(route) - 1
        ):
            errors.append("Delivery assignment has an invalid route position.")
            continue
        if assignment.customer_id not in required_set:
            errors.append("Delivery assignment contains an invalid customer.")
            continue
        if route[assignment.route_position] != assignment.customer_id:
            errors.append("Delivery has no matching route visit.")
            continue
        if not np.isfinite(assignment.quantity) or assignment.quantity <= 0:
            errors.append("Delivery quantities must be finite and positive.")
            continue

        visit_key = (assignment.vehicle_id, assignment.route_position)
        if visit_key in assignment_by_visit:
            errors.append(
                "Each SDVRP route visit must have exactly one delivery assignment."
            )
            continue
        assignment_by_visit[visit_key] = assignment
        delivered_by_customer[assignment.customer_id] += assignment.quantity
        delivered_by_vehicle[assignment.vehicle_id] += assignment.quantity

    for vehicle in range(len(problem.capacities)):
        route = solution.routes.get(str(vehicle), [])
        for position, _node in enumerate(route[1:-1], start=1):
            if (vehicle, position) not in assignment_by_visit:
                errors.append(
                    "Every SDVRP visit must have a positive delivery quantity."
                )
        if (
            delivered_by_vehicle[vehicle]
            > float(problem.capacities[vehicle]) + _EPSILON
        ):
            errors.append(f"Vehicle {vehicle} exceeds capacity.")

    if not np.allclose(
        delivered_by_customer[required],
        problem.demands[required],
        atol=_EPSILON,
        rtol=0.0,
    ):
        errors.append("Delivered quantities must exactly equal customer demands.")
    return errors


def validate_solution(
    problem: RouteProblem,
    solution: Solution,
) -> list[str]:
    return (
        validate_cvrp_solution(problem, solution)
        if problem.problem_type == "cvrp"
        else validate_sdvrp_solution(problem, solution)
    )


def evaluate_solution(
    problem: RouteProblem,
    solution: Solution,
) -> EvaluatedSolution:
    violations = tuple(validate_solution(problem, solution))
    cost = route_cost(solution, problem.matrix) if not violations else float("inf")
    return EvaluatedSolution(solution, cost, violations)


def _solution_signature(solution: Solution) -> tuple[Any, ...]:
    route_key = tuple(
        (vehicle, tuple(route))
        for vehicle, route in sorted(
            solution.routes.items(), key=lambda item: int(item[0])
        )
    )
    delivery_key = tuple(
        sorted(
            (
                assignment.vehicle_id,
                assignment.route_position,
                assignment.customer_id,
                round(float(assignment.quantity), 12),
            )
            for assignment in solution.deliveries
        )
    )
    return route_key, delivery_key


def _delivery_map(
    solution: Solution,
) -> dict[tuple[int, int], DeliveryAssignment]:
    return {
        (assignment.vehicle_id, assignment.route_position): assignment
        for assignment in solution.deliveries
    }


def _solution_to_visits(
    problem: RouteProblem,
    solution: Solution,
) -> dict[int, list[tuple[int, float | None]]]:
    assignment_map = _delivery_map(solution)
    visits: dict[int, list[tuple[int, float | None]]] = {}
    for vehicle in range(len(problem.capacities)):
        route = solution.routes[str(vehicle)]
        entries: list[tuple[int, float | None]] = []
        for position, customer in enumerate(route[1:-1], start=1):
            quantity = None
            if problem.problem_type == "sdvrp":
                assignment = assignment_map.get((vehicle, position))
                quantity = assignment.quantity if assignment is not None else None
            entries.append((customer, quantity))
        visits[vehicle] = entries
    return visits


def _visits_to_solution(
    problem: RouteProblem,
    visits: Mapping[int, Sequence[tuple[int, float | None]]],
) -> Solution:
    routes: Routes = {}
    deliveries: list[DeliveryAssignment] = []
    for vehicle in range(len(problem.capacities)):
        depot = problem.starting_nodes[vehicle]
        vehicle_visits = list(visits.get(vehicle, ()))
        routes[str(vehicle)] = [
            depot,
            *[int(customer) for customer, _quantity in vehicle_visits],
            depot,
        ]
        if problem.problem_type == "sdvrp":
            for position, (customer, quantity) in enumerate(
                vehicle_visits, start=1
            ):
                deliveries.append(
                    DeliveryAssignment(
                        vehicle_id=vehicle,
                        route_position=position,
                        customer_id=int(customer),
                        quantity=float(quantity) if quantity is not None else 0.0,
                    )
                )
    return Solution(routes, tuple(deliveries))


def _vehicle_loads(
    problem: RouteProblem,
    solution: Solution,
) -> list[float]:
    if problem.problem_type == "cvrp":
        return [
            float(
                sum(
                    problem.demands[node]
                    for node in solution.routes[str(vehicle)][1:-1]
                )
            )
            for vehicle in range(len(problem.capacities))
        ]
    return [
        float(
            sum(
                assignment.quantity
                for assignment in solution.deliveries
                if assignment.vehicle_id == vehicle
            )
        )
        for vehicle in range(len(problem.capacities))
    ]


def detect_bottlenecks(
    problem: RouteProblem,
    solution: Solution,
    *,
    capacity_pressure_threshold: float = 0.90,
    route_imbalance_threshold: float = 0.20,
    search_history: Sequence[float] | None = None,
    stagnation_threshold: float = 0.001,
    stagnation_window: int = 10,
) -> list[Bottleneck]:
    """Detect measurable routing bottlenecks with normalized severities."""
    violations = validate_solution(problem, solution)
    if violations:
        raise ValueError(
            "Cannot detect bottlenecks in an invalid solution: "
            + "; ".join(violations)
        )
    if not 0.0 <= capacity_pressure_threshold <= 1.0:
        raise ValueError("capacity_pressure_threshold must be in [0, 1].")
    if route_imbalance_threshold < 0.0:
        raise ValueError("route_imbalance_threshold must be non-negative.")
    if stagnation_window < 1:
        raise ValueError("stagnation_window must be positive.")

    items: list[Bottleneck] = []
    edge_records: list[tuple[int, int, int, int, float]] = []
    for vehicle in range(len(problem.capacities)):
        route = solution.routes[str(vehicle)]
        for position, (left, right) in enumerate(zip(route, route[1:])):
            edge_records.append(
                (
                    vehicle,
                    position,
                    left,
                    right,
                    float(problem.matrix[left][right]),
                )
            )

    max_edge = max((record[4] for record in edge_records), default=0.0)
    mean_edge = float(
        np.mean([record[4] for record in edge_records])
    ) if edge_records else 0.0
    for vehicle, position, left, right, cost in edge_records:
        severity = 0.0 if max_edge <= _EPSILON else min(1.0, cost / max_edge)
        items.append(
            Bottleneck(
                bottleneck_id=f"edge_v{vehicle}_p{position}",
                bottleneck_type="high_cost_edge",
                severity=severity,
                affected_nodes=(left, right),
                affected_vehicles=(vehicle,),
                critical_edges=((vehicle, position, position + 1),),
                route_positions=((vehicle, position), (vehicle, position + 1)),
                evidence={
                    "edge_cost": cost,
                    "mean_edge_cost": mean_edge,
                    "max_edge_cost": max_edge,
                },
                explanation="A route edge contributes a high relative travel cost.",
            )
        )

    loads = _vehicle_loads(problem, solution)
    for vehicle, (load, capacity) in enumerate(
        zip(loads, problem.capacities, strict=True)
    ):
        ratio = min(1.0, float(load / capacity))
        if ratio + _EPSILON < capacity_pressure_threshold:
            continue
        route = solution.routes[str(vehicle)]
        items.append(
            Bottleneck(
                bottleneck_id=f"capacity_v{vehicle}",
                bottleneck_type="capacity_pressure",
                severity=ratio,
                affected_nodes=tuple(route[1:-1]),
                affected_vehicles=(vehicle,),
                critical_edges=(),
                route_positions=tuple(
                    (vehicle, position)
                    for position in range(1, len(route) - 1)
                ),
                evidence={
                    "load": float(load),
                    "capacity": float(capacity),
                    "load_ratio": ratio,
                },
                explanation="A vehicle operates near its capacity limit.",
            )
        )

    route_costs = _route_costs(solution, problem.matrix)
    if route_costs:
        mean_route_cost = float(np.mean(route_costs))
        max_route_cost = max(route_costs)
        imbalance_ratio = (
            0.0
            if mean_route_cost <= _EPSILON
            else (max_route_cost - mean_route_cost) / mean_route_cost
        )
        if imbalance_ratio + _EPSILON >= route_imbalance_threshold:
            affected = tuple(
                index
                for index, value in enumerate(route_costs)
                if abs(value - max_route_cost) <= _EPSILON
            )
            items.append(
                Bottleneck(
                    bottleneck_id="route_cost_imbalance",
                    bottleneck_type="route_cost_imbalance",
                    severity=min(1.0, max(0.0, imbalance_ratio)),
                    affected_nodes=tuple(
                        node
                        for vehicle in affected
                        for node in solution.routes[str(vehicle)][1:-1]
                    ),
                    affected_vehicles=affected,
                    critical_edges=(),
                    route_positions=tuple(
                        (vehicle, position)
                        for vehicle in affected
                        for position in range(
                            1, len(solution.routes[str(vehicle)]) - 1
                        )
                    ),
                    evidence={
                        "mean_route_cost": mean_route_cost,
                        "max_route_cost": max_route_cost,
                        "imbalance_ratio": imbalance_ratio,
                    },
                    explanation="One or more routes are disproportionately expensive.",
                )
            )

    if problem.problem_type == "sdvrp":
        visits_by_customer: dict[int, list[DeliveryAssignment]] = {
            customer: [] for customer in _required_customers(problem)
        }
        for assignment in solution.deliveries:
            visits_by_customer.setdefault(assignment.customer_id, []).append(
                assignment
            )
        split_customers = tuple(
            customer
            for customer, assignments in visits_by_customer.items()
            if len(assignments) > 1
        )
        extra_visits = sum(
            max(0, len(assignments) - 1)
            for assignments in visits_by_customer.values()
        )
        if split_customers:
            customer_component = len(split_customers) / max(
                1, len(visits_by_customer)
            )
            visit_component = extra_visits / max(1, len(solution.deliveries))
            severity = min(1.0, 0.6 * customer_component + 0.4 * visit_component)
            affected_vehicles = tuple(
                sorted(
                    {
                        assignment.vehicle_id
                        for customer in split_customers
                        for assignment in visits_by_customer[customer]
                    }
                )
            )
            positions = tuple(
                sorted(
                    (
                        assignment.vehicle_id,
                        assignment.route_position,
                    )
                    for customer in split_customers
                    for assignment in visits_by_customer[customer]
                )
            )
            items.append(
                Bottleneck(
                    bottleneck_id="split_delivery_overhead",
                    bottleneck_type="split_delivery_overhead",
                    severity=severity,
                    affected_nodes=split_customers,
                    affected_vehicles=affected_vehicles,
                    critical_edges=(),
                    route_positions=positions,
                    evidence={
                        "split_customers": len(split_customers),
                        "extra_visits": extra_visits,
                    },
                    explanation="Split demand creates repeated customer visits.",
                )
            )

    history = tuple(float(value) for value in (search_history or ()))
    if len(history) >= stagnation_window + 1:
        start = history[-stagnation_window - 1]
        end = history[-1]
        relative_improvement = (start - end) / max(abs(start), _EPSILON)
        if relative_improvement <= stagnation_threshold + _EPSILON:
            severity = (
                1.0
                if stagnation_threshold <= _EPSILON
                else min(
                    1.0,
                    max(
                        0.0,
                        1.0 - relative_improvement / stagnation_threshold,
                    ),
                )
            )
            items.append(
                Bottleneck(
                    bottleneck_id="classical_stagnation",
                    bottleneck_type="classical_stagnation",
                    severity=severity,
                    affected_nodes=tuple(_required_customers(problem)),
                    affected_vehicles=tuple(range(len(problem.capacities))),
                    critical_edges=(),
                    route_positions=(),
                    evidence={
                        "window": stagnation_window,
                        "relative_improvement": relative_improvement,
                        "threshold": stagnation_threshold,
                    },
                    explanation="The supplied classical objective history has stagnated.",
                )
            )

    return sorted(
        items,
        key=lambda item: (
            -item.severity,
            _bottleneck_priority(item.bottleneck_type),
            item.bottleneck_id,
        ),
    )


def _bottleneck_priority(bottleneck_type: str) -> int:
    priorities = {
        "split_delivery_overhead": 0,
        "classical_stagnation": 1,
        "capacity_pressure": 2,
        "route_cost_imbalance": 3,
        "high_cost_edge": 4,
    }
    return priorities.get(bottleneck_type, 99)


def select_primary_bottleneck(
    bottlenecks: Sequence[Bottleneck],
) -> Bottleneck | None:
    return min(
        bottlenecks,
        key=lambda item: (
            -item.severity,
            _bottleneck_priority(item.bottleneck_type),
            item.bottleneck_id,
        ),
        default=None,
    )


def extract_difficult_neighborhood(
    problem: RouteProblem,
    solution: Solution,
    bottleneck: Bottleneck,
    *,
    neighborhood_size: int = 6,
    mode: NeighborhoodMode = "bottleneck_targeted",
) -> Neighborhood:
    """Extract route positions around the selected bottleneck."""
    if neighborhood_size < 1:
        raise ValueError("neighborhood_size must be positive.")
    if mode not in {"bottleneck_targeted", "global_baseline"}:
        raise ValueError("Unsupported neighborhood mode.")

    all_vehicles = tuple(range(len(problem.capacities)))
    positions: dict[int, set[int]] = {
        vehicle: set() for vehicle in all_vehicles
    }

    if mode == "global_baseline":
        for vehicle in all_vehicles:
            positions[vehicle].update(
                range(1, len(solution.routes[str(vehicle)]) - 1)
            )
    else:
        affected_vehicles = (
            bottleneck.affected_vehicles or all_vehicles
        )
        for vehicle, position in bottleneck.route_positions:
            route = solution.routes[str(vehicle)]
            for candidate_position in (position - 1, position, position + 1):
                if 0 < candidate_position < len(route) - 1:
                    positions[vehicle].add(candidate_position)

        for vehicle in affected_vehicles:
            route = solution.routes[str(vehicle)]
            if not positions[vehicle]:
                internal_positions = list(range(1, len(route) - 1))
                internal_positions.sort(
                    key=lambda position: (
                        -float(
                            problem.matrix[route[position - 1]][route[position]]
                            + problem.matrix[route[position]][route[position + 1]]
                        ),
                        position,
                    )
                )
                positions[vehicle].update(
                    internal_positions[:neighborhood_size]
                )

    for vehicle in positions:
        if len(positions[vehicle]) > neighborhood_size:
            positions[vehicle] = set(
                sorted(positions[vehicle])[:neighborhood_size]
            )

    active_vehicles = tuple(
        vehicle for vehicle in all_vehicles if positions[vehicle]
    )
    if not active_vehicles:
        active_vehicles = bottleneck.affected_vehicles or all_vehicles

    nodes = tuple(
        sorted(
            {
                solution.routes[str(vehicle)][position]
                for vehicle in active_vehicles
                for position in positions.get(vehicle, set())
            }
        )
    )
    return Neighborhood(
        bottleneck_id=bottleneck.bottleneck_id,
        mode=mode,
        vehicles=active_vehicles,
        route_positions=tuple(
            (vehicle, tuple(sorted(positions[vehicle])))
            for vehicle in active_vehicles
        ),
        nodes=nodes,
        critical_edges=bottleneck.critical_edges,
    )


def apply_move(
    problem: RouteProblem,
    seed: Solution,
    move: MoveCandidate,
) -> Solution:
    """Apply one parameterized move while keeping SDVRP quantities aligned."""
    visits = _solution_to_visits(problem, seed)
    parameters = dict(move.parameters)

    if move.move_type == "no_change":
        return _visits_to_solution(problem, visits)

    if move.move_type in {"swap", "inter_route_swap"}:
        vehicle_a = int(parameters["vehicle_a"])
        vehicle_b = int(parameters["vehicle_b"])
        position_a = int(parameters["position_a"]) - 1
        position_b = int(parameters["position_b"]) - 1
        visits[vehicle_a][position_a], visits[vehicle_b][position_b] = (
            visits[vehicle_b][position_b],
            visits[vehicle_a][position_a],
        )

    elif move.move_type == "two_opt":
        vehicle = int(parameters["vehicle"])
        start = int(parameters["start"]) - 1
        end = int(parameters["end"])
        visits[vehicle][start:end] = reversed(visits[vehicle][start:end])

    elif move.move_type == "relocate":
        source_vehicle = int(parameters["source_vehicle"])
        target_vehicle = int(parameters["target_vehicle"])
        source_index = int(parameters["source_position"]) - 1
        target_index = int(parameters["target_position"]) - 1
        visit = visits[source_vehicle].pop(source_index)
        if source_vehicle == target_vehicle and source_index < target_index:
            target_index -= 1
        visits[target_vehicle].insert(target_index, visit)

    elif move.move_type in {"split_merge", "quantity_reassignment"}:
        if problem.problem_type != "sdvrp":
            raise ValueError(f"{move.move_type} is only valid for SDVRP.")
        source_vehicle = int(parameters["source_vehicle"])
        target_vehicle = int(parameters["target_vehicle"])
        source_index = int(parameters["source_position"]) - 1
        target_index = int(parameters["target_position"]) - 1
        source_customer, source_quantity = visits[source_vehicle][source_index]
        target_customer, target_quantity = visits[target_vehicle][target_index]
        if source_customer != target_customer:
            raise ValueError("Split-merge visits must refer to the same customer.")
        if source_quantity is None or target_quantity is None:
            raise ValueError("Split-merge requires explicit quantities.")
        amount = float(parameters.get("quantity", source_quantity))
        if not np.isfinite(amount) or amount <= 0 or amount > source_quantity + _EPSILON:
            raise ValueError("Invalid split-merge quantity.")

        visits[target_vehicle][target_index] = (
            target_customer,
            target_quantity + amount,
        )
        remaining = source_quantity - amount
        if remaining <= _EPSILON:
            visits[source_vehicle].pop(source_index)
        else:
            visits[source_vehicle][source_index] = (
                source_customer,
                remaining,
            )
    else:
        raise ValueError(f"Unsupported move type: {move.move_type}")

    return _visits_to_solution(problem, visits)


def _candidate_from_parameters(
    problem: RouteProblem,
    seed: Solution,
    *,
    move_id: str,
    move_type: str,
    affected_nodes: tuple[int, ...],
    affected_vehicles: tuple[int, ...],
    parameters: tuple[tuple[str, Any], ...],
) -> tuple[MoveCandidate, Solution | None]:
    provisional = MoveCandidate(
        move_id=move_id,
        move_type=move_type,
        affected_nodes=affected_nodes,
        affected_vehicles=affected_vehicles,
        parameters=parameters,
        estimated_delta_cost=0.0,
        exact_delta_cost=None,
        feasible_precheck=True,
        rejection_reason=None,
    )
    try:
        result = apply_move(problem, seed, provisional)
        violations = validate_solution(problem, result)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        return (
            replace(
                provisional,
                feasible_precheck=False,
                rejection_reason=str(error),
            ),
            None,
        )

    if violations:
        return (
            replace(
                provisional,
                feasible_precheck=False,
                rejection_reason="; ".join(violations),
            ),
            result,
        )

    delta = route_cost(result, problem.matrix) - route_cost(seed, problem.matrix)
    return (
        replace(
            provisional,
            estimated_delta_cost=float(delta),
            exact_delta_cost=float(delta),
        ),
        result,
    )


def generate_candidate_moves(
    problem: RouteProblem,
    seed: Solution,
    neighborhood: Neighborhood,
    *,
    max_candidates: int = 16,
    move_types: Sequence[str] = (
        "swap",
        "relocate",
        "two_opt",
        "inter_route_swap",
        "split_merge",
    ),
) -> tuple[list[MoveCandidate], list[MoveCandidate]]:
    """Generate deterministic, deduplicated moves from a compact neighborhood."""
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive.")
    allowed = set(move_types)
    supported = {
        "swap",
        "relocate",
        "two_opt",
        "inter_route_swap",
        "split_merge",
    }
    unsupported = allowed - supported
    if unsupported:
        raise ValueError(
            "Unsupported move types: " + ", ".join(sorted(unsupported))
        )

    no_change = MoveCandidate(
        move_id="m0_no_change",
        move_type="no_change",
        affected_nodes=(),
        affected_vehicles=(),
        parameters=(),
        estimated_delta_cost=0.0,
        exact_delta_cost=0.0,
        feasible_precheck=True,
        rejection_reason=None,
    )
    feasible: list[MoveCandidate] = [no_change]
    rejected: list[MoveCandidate] = []
    seen_signatures = {_solution_signature(seed)}
    seen_move_ids = {no_change.move_id}

    def add(
        move_id: str,
        move_type: str,
        affected_nodes: tuple[int, ...],
        affected_vehicles: tuple[int, ...],
        parameters: tuple[tuple[str, Any], ...],
    ) -> None:
        if move_id in seen_move_ids:
            return
        seen_move_ids.add(move_id)
        candidate, result = _candidate_from_parameters(
            problem,
            seed,
            move_id=move_id,
            move_type=move_type,
            affected_nodes=affected_nodes,
            affected_vehicles=affected_vehicles,
            parameters=parameters,
        )
        if not candidate.feasible_precheck or result is None:
            rejected.append(candidate)
            return
        signature = _solution_signature(result)
        if signature in seen_signatures:
            rejected.append(
                replace(
                    candidate,
                    feasible_precheck=False,
                    rejection_reason="duplicate_result",
                )
            )
            return
        seen_signatures.add(signature)
        feasible.append(candidate)

    source_positions = {
        vehicle: neighborhood.positions_for(vehicle)
        for vehicle in neighborhood.vehicles
    }
    target_vehicles = tuple(range(len(problem.capacities)))

    for vehicle in neighborhood.vehicles:
        route = seed.routes[str(vehicle)]
        positions = source_positions[vehicle]

        if "swap" in allowed:
            for left_index, left in enumerate(positions):
                for right in positions[left_index + 1 :]:
                    add(
                        f"m_swap_v{vehicle}_{left}_{right}",
                        "swap",
                        (route[left], route[right]),
                        (vehicle,),
                        (
                            ("vehicle_a", vehicle),
                            ("vehicle_b", vehicle),
                            ("position_a", left),
                            ("position_b", right),
                        ),
                    )

        if "two_opt" in allowed:
            for left_index, left in enumerate(positions):
                for right in positions[left_index + 1 :]:
                    add(
                        f"m_two_opt_v{vehicle}_{left}_{right}",
                        "two_opt",
                        (route[left], route[right]),
                        (vehicle,),
                        (
                            ("vehicle", vehicle),
                            ("start", left),
                            ("end", right),
                        ),
                    )

        if "relocate" in allowed:
            for source_position in positions:
                source_customer = route[source_position]
                for target_vehicle in target_vehicles:
                    target_route = seed.routes[str(target_vehicle)]
                    insertion_positions = set(
                        neighborhood.positions_for(target_vehicle)
                    )
                    insertion_positions.update({1, len(target_route) - 1})
                    for target_position in sorted(insertion_positions):
                        if target_position < 1 or target_position >= len(target_route):
                            continue
                        if (
                            vehicle == target_vehicle
                            and target_position in {
                                source_position,
                                source_position + 1,
                            }
                        ):
                            continue
                        add(
                            (
                                f"m_relocate_v{vehicle}_{source_position}_"
                                f"to_v{target_vehicle}_{target_position}"
                            ),
                            "relocate",
                            (source_customer,),
                            tuple(sorted({vehicle, target_vehicle})),
                            (
                                ("source_vehicle", vehicle),
                                ("target_vehicle", target_vehicle),
                                ("source_position", source_position),
                                ("target_position", target_position),
                            ),
                        )

        if "inter_route_swap" in allowed:
            for target_vehicle in target_vehicles:
                if target_vehicle == vehicle:
                    continue
                target_route = seed.routes[str(target_vehicle)]
                target_positions = neighborhood.positions_for(target_vehicle)
                if not target_positions:
                    target_positions = tuple(
                        range(1, len(target_route) - 1)
                    )[: max(1, len(positions))]
                for source_position in positions:
                    for target_position in target_positions:
                        add(
                            (
                                f"m_inter_route_swap_v{vehicle}_{source_position}_"
                                f"v{target_vehicle}_{target_position}"
                            ),
                            "inter_route_swap",
                            (
                                route[source_position],
                                target_route[target_position],
                            ),
                            tuple(sorted({vehicle, target_vehicle})),
                            (
                                ("vehicle_a", vehicle),
                                ("vehicle_b", target_vehicle),
                                ("position_a", source_position),
                                ("position_b", target_position),
                            ),
                        )

    if problem.problem_type == "sdvrp" and "split_merge" in allowed:
        by_customer: dict[int, list[DeliveryAssignment]] = {}
        for assignment in seed.deliveries:
            by_customer.setdefault(assignment.customer_id, []).append(assignment)
        focus_nodes = set(neighborhood.nodes)
        for customer, assignments in sorted(by_customer.items()):
            if len(assignments) < 2:
                continue
            if focus_nodes and customer not in focus_nodes:
                continue
            ordered = sorted(
                assignments,
                key=lambda item: (
                    item.quantity,
                    item.vehicle_id,
                    item.route_position,
                ),
            )
            for source in ordered:
                for target in ordered:
                    if source == target:
                        continue
                    add(
                        (
                            f"m_split_merge_n{customer}_"
                            f"v{source.vehicle_id}p{source.route_position}_"
                            f"to_v{target.vehicle_id}p{target.route_position}"
                        ),
                        "split_merge",
                        (customer,),
                        tuple(
                            sorted({source.vehicle_id, target.vehicle_id})
                        ),
                        (
                            ("source_vehicle", source.vehicle_id),
                            ("source_position", source.route_position),
                            ("target_vehicle", target.vehicle_id),
                            ("target_position", target.route_position),
                            ("quantity", float(source.quantity)),
                        ),
                    )

    ranked = sorted(
        feasible[1:],
        key=lambda move: (
            float(move.exact_delta_cost or 0.0),
            move.move_type,
            move.move_id,
        ),
    )
    return [no_change, *ranked[: max_candidates - 1]], sorted(
        rejected,
        key=lambda move: (move.move_type, move.move_id),
    )


def generate_neighborhood(
    problem: RouteProblem,
    seed: Solution,
    bottleneck: Bottleneck,
    *,
    max_candidates: int = 16,
    global_baseline: bool = False,
) -> list[MoveCandidate]:
    """Backward-compatible wrapper returning feasible candidates only."""
    neighborhood = extract_difficult_neighborhood(
        problem,
        seed,
        bottleneck,
        mode="global_baseline" if global_baseline else "bottleneck_targeted",
    )
    candidates, _rejected = generate_candidate_moves(
        problem,
        seed,
        neighborhood,
        max_candidates=max_candidates,
    )
    return candidates


def _xy_edges(n_qubits: int, topology: XYTopology) -> list[tuple[int, int]]:
    if topology == "full":
        return [
            (left, right)
            for left in range(n_qubits)
            for right in range(left + 1, n_qubits)
        ]
    if topology == "star":
        return [(0, right) for right in range(1, n_qubits)]
    if topology == "ring":
        if n_qubits < 2:
            return []
        if n_qubits == 2:
            return [(0, 1)]
        return [(index, (index + 1) % n_qubits) for index in range(n_qubits)]
    raise ValueError("xy_topology must be 'ring', 'full', or 'star'.")


def _apply_w_state(circuit: Any, n_qubits: int) -> None:
    from qiskit.circuit.library import StatePreparation

    state = np.zeros(2**n_qubits, dtype=complex)
    for index in range(n_qubits):
        state[1 << index] = 1.0 / np.sqrt(n_qubits)
    circuit.compose(
        StatePreparation(state),
        qubits=list(range(n_qubits)),
        inplace=True,
    )


def build_qaoa_xy_circuit(
    operator: Any,
    reps: int,
    *,
    initialization: Initialization = "no-op",
    xy_topology: XYTopology = "ring",
) -> tuple[Any, list[Any]]:
    """Build an exact-one QAOA+ circuit with explicit parameter ordering."""
    if reps < 1:
        raise ValueError("reps must be positive.")
    if initialization not in {"no-op", "w-state"}:
        raise ValueError("initialization must be 'no-op' or 'w-state'.")

    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector

    n_qubits = int(operator.num_qubits)
    if n_qubits < 1:
        raise ValueError("The candidate register must contain at least one qubit.")

    gammas = ParameterVector("gamma", reps)
    betas = ParameterVector("beta", reps)
    circuit = QuantumCircuit(n_qubits)
    if initialization == "no-op":
        circuit.x(0)
    else:
        _apply_w_state(circuit, n_qubits)

    edges = _xy_edges(n_qubits, xy_topology)
    for layer in range(reps):
        has_cost_term = False
        for label, coefficient in pauli_terms(operator):
            active = [
                n_qubits - 1 - index
                for index, symbol in enumerate(label)
                if symbol == "Z"
            ]
            if len(active) == 1:
                has_cost_term = True
                circuit.rz(
                    2.0 * coefficient * gammas[layer],
                    active[0],
                )
            elif len(active) == 2:
                has_cost_term = True
                circuit.rzz(
                    2.0 * coefficient * gammas[layer],
                    active[0],
                    active[1],
                )
        # Preserve the documented [gamma..., beta...] parameter contract even
        # for a zero/identity Hamiltonian used by circuit-level tests.  The
        # cancelling pair is physically an identity and never changes samples.
        if not has_cost_term:
            circuit.rz(gammas[layer], 0)
            circuit.rz(-gammas[layer], 0)
        for left, right in edges:
            circuit.rxx(2.0 * betas[layer], left, right)
            circuit.ryy(2.0 * betas[layer], left, right)

    return circuit, [*gammas, *betas]


def _bind_parameters(
    circuit: Any,
    parameter_order: Sequence[Any],
    values: Sequence[float],
) -> Any:
    if len(parameter_order) != len(values):
        raise ValueError("Optimizer parameter count does not match the circuit.")
    return circuit.assign_parameters(
        dict(zip(parameter_order, values, strict=True))
    )


def _run_local_qaoa(
    ansatz: Any,
    parameter_order: Sequence[Any],
    normalized_operator: Any,
    *,
    reps: int,
    maxiter: int,
    shots: int,
    random_seed: int,
) -> QuantumExecutionResult:
    from qiskit.quantum_info import Statevector
    from scipy.optimize import minimize

    history: list[Mapping[str, float | int]] = []
    evaluations = 0

    def objective(values: np.ndarray) -> float:
        nonlocal evaluations
        statevector = Statevector.from_instruction(
            _bind_parameters(ansatz, parameter_order, values)
        )
        energy = float(
            np.real(statevector.expectation_value(normalized_operator))
        )
        evaluations += 1
        history.append({"evaluation": evaluations, "energy": energy})
        return energy

    initial = np.concatenate(
        (np.full(reps, 0.4, dtype=float), np.full(reps, 0.2, dtype=float))
    )
    optimum = minimize(
        objective,
        initial,
        method="COBYLA",
        options={"maxiter": maxiter, "rhobeg": 0.15},
    )
    bound = _bind_parameters(ansatz, parameter_order, optimum.x)
    statevector = Statevector.from_instruction(bound)
    statevector.seed(random_seed)
    counts = {
        str(bitstring): int(count)
        for bitstring, count in statevector.sample_counts(shots=shots).items()
    }
    operations = ansatz.count_ops()
    return QuantumExecutionResult(
        counts=counts,
        optimizer_parameters=tuple(float(value) for value in optimum.x),
        optimizer_history=tuple(history),
        optimizer_evaluations=evaluations,
        backend="statevector",
        job_ids=(),
        circuit_depth=int(ansatz.depth()),
        two_qubit_gate_count=int(
            sum(
                int(value)
                for name, value in operations.items()
                if str(name) in {"cx", "cz", "rxx", "ryy", "rzz", "swap"}
            )
        ),
    )


def _extract_estimator_value(result: Any) -> float:
    public_result = result[0]
    data = public_result.data
    values = np.asarray(data.evs, dtype=float).reshape(-1)
    if not len(values):
        raise RuntimeError("IBM Estimator returned no expectation value.")
    return float(values[0])


def _extract_sampler_counts(result: Any) -> dict[str, int]:
    public_result = result[0]
    data = public_result.data
    for attribute in ("meas", "c"):
        register = getattr(data, attribute, None)
        if register is not None and hasattr(register, "get_counts"):
            return {
                str(bitstring): int(count)
                for bitstring, count in register.get_counts().items()
            }
    for attribute in dir(data):
        if attribute.startswith("_"):
            continue
        register = getattr(data, attribute, None)
        if register is not None and hasattr(register, "get_counts"):
            return {
                str(bitstring): int(count)
                for bitstring, count in register.get_counts().items()
            }
    raise RuntimeError("IBM Sampler returned no measurable counts register.")


def _run_ibm_qaoa(
    ansatz: Any,
    parameter_order: Sequence[Any],
    normalized_operator: Any,
    *,
    reps: int,
    maxiter: int,
    shots: int,
    runtime_options: Mapping[str, Any] | None,
) -> QuantumExecutionResult:
    from scipy.optimize import minimize

    from .connection import (
        circuit_metadata,
        get_backend,
        get_pass_manager,
        get_primitives,
        parse_runtime_config,
        safe_job_id,
    )

    config = parse_runtime_config(runtime_options)
    if shots > config.max_shots:
        raise ValueError(
            f"shots exceeds the configured IBM limit of {config.max_shots}."
        )

    backend = get_backend(config, ansatz.num_qubits)
    pass_manager = get_pass_manager(backend, config.optimization_level)
    isa_ansatz = pass_manager.run(ansatz)
    isa_operator = normalized_operator.apply_layout(isa_ansatz.layout)
    estimator, sampler = get_primitives(backend, config)

    isa_parameters = {
        parameter.name: parameter for parameter in isa_ansatz.parameters
    }
    try:
        isa_parameter_order = [
            isa_parameters[parameter.name] for parameter in parameter_order
        ]
    except KeyError as error:
        raise RuntimeError(
            "Transpilation changed an expected QAOA parameter name."
        ) from error

    history: list[Mapping[str, float | int]] = []
    job_ids: list[str] = []
    evaluations = 0

    def objective(values: np.ndarray) -> float:
        nonlocal evaluations
        bound = _bind_parameters(
            isa_ansatz,
            isa_parameter_order,
            values,
        )
        try:
            job = estimator.run([(bound, isa_operator)])
        except TypeError:
            job = estimator.run(pubs=[(bound, [isa_operator])])
        job_id = safe_job_id(job)
        if job_id:
            job_ids.append(job_id)
        energy = _extract_estimator_value(job.result())
        evaluations += 1
        history.append({"evaluation": evaluations, "energy": energy})
        return energy

    initial = np.concatenate(
        (np.full(reps, 0.4, dtype=float), np.full(reps, 0.2, dtype=float))
    )
    optimum = minimize(
        objective,
        initial,
        method="COBYLA",
        options={"maxiter": maxiter, "rhobeg": 0.15},
    )
    final_circuit = _bind_parameters(
        isa_ansatz,
        isa_parameter_order,
        optimum.x,
    )
    final_circuit.measure_all()
    try:
        sampler_job = sampler.run([final_circuit], shots=shots)
    except TypeError:
        sampler_job = sampler.run([(final_circuit,)], shots=shots)
    sampler_job_id = safe_job_id(sampler_job)
    if sampler_job_id:
        job_ids.append(sampler_job_id)
    counts = _extract_sampler_counts(sampler_job.result())
    metadata = circuit_metadata(
        final_circuit,
        backend=backend,
        job_ids=job_ids,
    )
    return QuantumExecutionResult(
        counts=counts,
        optimizer_parameters=tuple(float(value) for value in optimum.x),
        optimizer_history=tuple(history),
        optimizer_evaluations=evaluations,
        backend=metadata["backend"],
        job_ids=tuple(metadata["job_ids"]),
        circuit_depth=metadata["transpiled_circuit_depth"],
        two_qubit_gate_count=metadata["two_qubit_gate_count"],
    )


def analyze_samples(
    counts: Mapping[str, int],
    hamiltonian: CandidateHamiltonian,
    candidates: Sequence[MoveCandidate],
    problem: RouteProblem,
    seed: Solution,
) -> list[SampleAnalysis]:
    """Decode every sampled state and evaluate its true routing outcome."""
    total = int(sum(int(value) for value in counts.values()))
    if total <= 0:
        return []

    analyses: list[SampleAnalysis] = []
    for raw_bitstring, raw_count in sorted(counts.items()):
        bitstring = clean_bitstring(str(raw_bitstring))
        count = int(raw_count)
        hamming_weight = bitstring.count("1") if set(bitstring) <= {"0", "1"} else -1
        selected_index = decode_one_hot_bitstring(
            bitstring,
            len(candidates),
        )
        try:
            energy = evaluate_bitstring_energy(bitstring, hamiltonian)
        except ValueError:
            energy = float("inf")

        selected_move: str | None = None
        feasible = False
        route_objective: float | None = None
        violations: tuple[str, ...] = ()
        if selected_index is not None:
            candidate = candidates[selected_index]
            selected_move = candidate.move_id
            try:
                solution = apply_move(problem, seed, candidate)
                evaluated = evaluate_solution(problem, solution)
                feasible = evaluated.valid
                route_objective = evaluated.cost if evaluated.valid else None
                violations = evaluated.violations
            except (KeyError, IndexError, TypeError, ValueError) as error:
                violations = (str(error),)

        analyses.append(
            SampleAnalysis(
                bitstring=bitstring,
                count=count,
                probability=count / total,
                hamming_weight=hamming_weight,
                one_hot_valid=selected_index is not None,
                selected_move=selected_move,
                energy=float(energy),
                route_cost=route_objective,
                feasible=feasible,
                violations=violations,
            )
        )
    return analyses


def _select_sample(
    analyses: Sequence[SampleAnalysis],
    policy: SamplePolicy,
) -> SampleAnalysis | None:
    valid = [
        analysis
        for analysis in analyses
        if analysis.one_hot_valid
        and analysis.feasible
        and analysis.route_cost is not None
        and analysis.selected_move is not None
    ]
    if not valid:
        return None

    if policy == "best_objective_valid":
        key = lambda item: (
            float(item.route_cost),
            -item.probability,
            item.energy,
            str(item.selected_move),
        )
    elif policy == "lowest_energy_valid":
        key = lambda item: (
            item.energy,
            float(item.route_cost),
            -item.probability,
            str(item.selected_move),
        )
    elif policy == "most_probable_valid":
        key = lambda item: (
            -item.probability,
            float(item.route_cost),
            item.energy,
            str(item.selected_move),
        )
    else:
        raise ValueError("Unsupported sample selection policy.")
    return min(valid, key=key)


def _sample_summary(
    analysis: SampleAnalysis | None,
) -> dict[str, Any] | None:
    return asdict(analysis) if analysis is not None else None


def _candidate_by_id(
    candidates: Sequence[MoveCandidate],
    move_id: str,
) -> MoveCandidate:
    for candidate in candidates:
        if candidate.move_id == move_id:
            return candidate
    raise KeyError(f"Unknown sampled move ID: {move_id}")


def _polishing_move_specs(
    problem: RouteProblem,
    solution: Solution,
) -> list[MoveCandidate]:
    specs: list[MoveCandidate] = []
    for vehicle in range(len(problem.capacities)):
        route = solution.routes[str(vehicle)]
        for left in range(1, len(route) - 1):
            for right in range(left + 1, len(route) - 1):
                specs.append(
                    MoveCandidate(
                        move_id=f"polish_two_opt_v{vehicle}_{left}_{right}",
                        move_type="two_opt",
                        affected_nodes=(route[left], route[right]),
                        affected_vehicles=(vehicle,),
                        parameters=(
                            ("vehicle", vehicle),
                            ("start", left),
                            ("end", right),
                        ),
                        estimated_delta_cost=0.0,
                        exact_delta_cost=None,
                        feasible_precheck=True,
                        rejection_reason=None,
                    )
                )

        for source_position in range(1, len(route) - 1):
            for target_vehicle in range(len(problem.capacities)):
                target_route = solution.routes[str(target_vehicle)]
                for target_position in range(1, len(target_route)):
                    if (
                        vehicle == target_vehicle
                        and target_position in {
                            source_position,
                            source_position + 1,
                        }
                    ):
                        continue
                    specs.append(
                        MoveCandidate(
                            move_id=(
                                f"polish_relocate_v{vehicle}_{source_position}_"
                                f"to_v{target_vehicle}_{target_position}"
                            ),
                            move_type="relocate",
                            affected_nodes=(route[source_position],),
                            affected_vehicles=tuple(
                                sorted({vehicle, target_vehicle})
                            ),
                            parameters=(
                                ("source_vehicle", vehicle),
                                ("target_vehicle", target_vehicle),
                                ("source_position", source_position),
                                ("target_position", target_position),
                            ),
                            estimated_delta_cost=0.0,
                            exact_delta_cost=None,
                            feasible_precheck=True,
                            rejection_reason=None,
                        )
                    )

    for vehicle_a in range(len(problem.capacities)):
        route_a = solution.routes[str(vehicle_a)]
        for vehicle_b in range(vehicle_a + 1, len(problem.capacities)):
            route_b = solution.routes[str(vehicle_b)]
            for position_a in range(1, len(route_a) - 1):
                for position_b in range(1, len(route_b) - 1):
                    specs.append(
                        MoveCandidate(
                            move_id=(
                                f"polish_swap_v{vehicle_a}_{position_a}_"
                                f"v{vehicle_b}_{position_b}"
                            ),
                            move_type="inter_route_swap",
                            affected_nodes=(
                                route_a[position_a],
                                route_b[position_b],
                            ),
                            affected_vehicles=(vehicle_a, vehicle_b),
                            parameters=(
                                ("vehicle_a", vehicle_a),
                                ("vehicle_b", vehicle_b),
                                ("position_a", position_a),
                                ("position_b", position_b),
                            ),
                            estimated_delta_cost=0.0,
                            exact_delta_cost=None,
                            feasible_precheck=True,
                            rejection_reason=None,
                        )
                    )

    if problem.problem_type == "sdvrp":
        by_customer: dict[int, list[DeliveryAssignment]] = {}
        for assignment in solution.deliveries:
            by_customer.setdefault(assignment.customer_id, []).append(assignment)
        for customer, assignments in sorted(by_customer.items()):
            if len(assignments) < 2:
                continue
            for source in assignments:
                for target in assignments:
                    if source == target:
                        continue
                    specs.append(
                        MoveCandidate(
                            move_id=(
                                f"polish_split_merge_n{customer}_"
                                f"v{source.vehicle_id}p{source.route_position}_"
                                f"to_v{target.vehicle_id}p{target.route_position}"
                            ),
                            move_type="split_merge",
                            affected_nodes=(customer,),
                            affected_vehicles=tuple(
                                sorted(
                                    {source.vehicle_id, target.vehicle_id}
                                )
                            ),
                            parameters=(
                                ("source_vehicle", source.vehicle_id),
                                ("source_position", source.route_position),
                                ("target_vehicle", target.vehicle_id),
                                ("target_position", target.route_position),
                                ("quantity", float(source.quantity)),
                            ),
                            estimated_delta_cost=0.0,
                            exact_delta_cost=None,
                            feasible_precheck=True,
                            rejection_reason=None,
                        )
                    )
    return specs


def polish_solution(
    problem: RouteProblem,
    solution: Solution,
    *,
    max_iterations: int = 20,
) -> PolishingResult:
    """Apply bounded deterministic best-improvement local search."""
    if max_iterations < 0:
        raise ValueError("polishing_iterations must be non-negative.")

    current = solution
    current_evaluation = evaluate_solution(problem, current)
    if not current_evaluation.valid:
        return PolishingResult(
            solution=current,
            cost_before=float("inf"),
            cost_after=float("inf"),
            operations=(),
        )

    cost_before = current_evaluation.cost
    operations: list[Mapping[str, Any]] = []
    for iteration in range(1, max_iterations + 1):
        best: tuple[float, str, MoveCandidate, Solution] | None = None
        seen: set[tuple[Any, ...]] = {_solution_signature(current)}
        for move in _polishing_move_specs(problem, current):
            try:
                candidate_solution = apply_move(problem, current, move)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            signature = _solution_signature(candidate_solution)
            if signature in seen:
                continue
            seen.add(signature)
            evaluated = evaluate_solution(problem, candidate_solution)
            if not evaluated.valid:
                continue
            delta = evaluated.cost - current_evaluation.cost
            if delta >= -_EPSILON:
                continue
            ranking = (evaluated.cost, move.move_id, move, candidate_solution)
            if best is None or ranking[:2] < best[:2]:
                best = ranking

        if best is None:
            break
        new_cost, _move_id, move, new_solution = best
        operations.append(
            {
                "iteration": iteration,
                "move_id": move.move_id,
                "move_type": move.move_type,
                "cost_before": current_evaluation.cost,
                "cost_after": new_cost,
            }
        )
        current = new_solution
        current_evaluation = EvaluatedSolution(current, new_cost, ())

    return PolishingResult(
        solution=current,
        cost_before=cost_before,
        cost_after=current_evaluation.cost,
        operations=tuple(operations),
    )


def improvement_gate(
    initial: EvaluatedSolution,
    candidate: EvaluatedSolution,
    *,
    epsilon: float = 0.0,
) -> tuple[EvaluatedSolution, bool, str]:
    """Accept only a feasible candidate that strictly improves the seed."""
    if epsilon < 0:
        raise ValueError("acceptance_epsilon must be non-negative.")
    if not candidate.valid:
        return initial, False, "infeasible_candidate"
    if candidate.cost + epsilon < initial.cost:
        return candidate, True, "accepted_improvement"
    if abs(candidate.cost - initial.cost) <= max(epsilon, _EPSILON):
        return initial, False, "equal_cost"
    return initial, False, "no_improvement"


def greedy_seed(problem: RouteProblem) -> Routes:
    """Build a deterministic capacity-feasible CVRP fallback seed."""
    if problem.problem_type == "sdvrp":
        raise ValueError("SDVRP requires supplied routes and delivery assignments.")
    required = _required_customers(problem)
    if float(sum(problem.demands[node] for node in required)) > float(
        np.sum(problem.capacities)
    ) + _EPSILON:
        raise ValueError("Total demand exceeds total fleet capacity.")

    routes: Routes = {
        str(vehicle): [problem.starting_nodes[vehicle]]
        for vehicle in range(len(problem.capacities))
    }
    remaining = problem.capacities.astype(float).copy()
    for customer in sorted(
        required,
        key=lambda node: (-float(problem.demands[node]), node),
    ):
        feasible = [
            vehicle
            for vehicle in range(len(remaining))
            if remaining[vehicle] + _EPSILON >= problem.demands[customer]
        ]
        if not feasible:
            raise ValueError("No capacity-feasible greedy seed exists.")
        vehicle = min(
            feasible,
            key=lambda index: (
                float(
                    problem.matrix[routes[str(index)][-1]][customer]
                    + problem.matrix[customer][problem.starting_nodes[index]]
                    - problem.matrix[
                        routes[str(index)][-1]
                    ][problem.starting_nodes[index]]
                ),
                -remaining[index],
                index,
            ),
        )
        routes[str(vehicle)].append(customer)
        remaining[vehicle] -= problem.demands[customer]

    for vehicle in range(len(problem.capacities)):
        routes[str(vehicle)].append(problem.starting_nodes[vehicle])
    return routes


def _parse_deliveries(value: Any) -> tuple[DeliveryAssignment, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("deliveries must be a list of delivery assignments.")
    output: list[DeliveryAssignment] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"deliveries[{index}] must be an object.")
        missing = {
            "vehicle_id",
            "route_position",
            "customer_id",
            "quantity",
        }.difference(item)
        if missing:
            raise ValueError(
                f"deliveries[{index}] is missing: {', '.join(sorted(missing))}."
            )
        output.append(
            DeliveryAssignment(
                vehicle_id=int(item["vehicle_id"]),
                route_position=int(item["route_position"]),
                customer_id=int(item["customer_id"]),
                quantity=float(item["quantity"]),
            )
        )
    return tuple(output)


def parse_hybrid_config(payload: Mapping[str, Any]) -> HybridConfig:
    """Parse standalone QAOA+/polishing options with safe defaults."""
    forbidden_credentials = {
        "token",
        "ibm_token",
        "ibm_quantum_token",
        "IBM_QUANTUM_TOKEN",
    }.intersection(payload)
    if forbidden_credentials:
        raise ValueError(
            "IBM credentials must be configured through IBM_QUANTUM_TOKEN, "
            "never through an algorithm payload."
        )
    executor = str(payload.get("executor", "local")).lower()
    if executor not in {"classical", "local", "ibm"}:
        raise ValueError("executor must be 'classical', 'local', or 'ibm'.")
    initialization = str(payload.get("initialization", "no-op")).lower()
    if initialization not in {"no-op", "w-state"}:
        raise ValueError("initialization must be 'no-op' or 'w-state'.")
    topology = str(payload.get("xy_topology", "ring")).lower()
    if topology not in {"ring", "full", "star"}:
        raise ValueError("xy_topology must be 'ring', 'full', or 'star'.")
    policy = str(
        payload.get("sample_selection_policy", "best_objective_valid")
    ).lower()
    if policy not in {
        "best_objective_valid",
        "lowest_energy_valid",
        "most_probable_valid",
    }:
        raise ValueError("Unsupported sample_selection_policy.")
    mode = str(
        payload.get(
            "neighborhood_mode",
            "global_baseline"
            if _as_bool(payload.get("global_baseline", False), "global_baseline")
            else "bottleneck_targeted",
        )
    ).lower()
    if mode not in {"bottleneck_targeted", "global_baseline"}:
        raise ValueError("Unsupported neighborhood_mode.")

    reps = int(payload.get("reps", payload.get("p", 1)))
    maxiter = int(payload.get("maxiter", 40))
    shots = int(payload.get("shots", 1024))
    max_candidates = int(
        payload.get("max_candidates", payload.get("max_candidate_moves", 16))
    )
    neighborhood_size = int(payload.get("neighborhood_size", 6))
    polishing_iterations = int(payload.get("polishing_iterations", 20))
    stagnation_window = int(payload.get("stagnation_window", 10))
    if min(reps, maxiter, shots, max_candidates, neighborhood_size) < 1:
        raise ValueError(
            "reps, maxiter, shots, max_candidates, and neighborhood_size "
            "must be positive."
        )
    if polishing_iterations < 0:
        raise ValueError("polishing_iterations must be non-negative.")
    if stagnation_window < 1:
        raise ValueError("stagnation_window must be positive.")

    one_hot_value = payload.get("one_hot_penalty")
    one_hot_penalty = None if one_hot_value is None else float(one_hot_value)
    if one_hot_penalty is not None and (
        not np.isfinite(one_hot_penalty) or one_hot_penalty <= 0
    ):
        raise ValueError("one_hot_penalty must be finite and positive.")

    move_types_value = payload.get(
        "move_types",
        ["swap", "relocate", "two_opt", "inter_route_swap", "split_merge"],
    )
    if not isinstance(move_types_value, Sequence) or isinstance(
        move_types_value, (str, bytes)
    ):
        raise ValueError("move_types must be a list of move names.")

    runtime_options = dict(payload.get("runtime_options") or {})
    for field in (
        "backend_name",
        "optimization_level",
        "resilience_level",
        "use_dynamical_decoupling",
        "use_dd",
        "max_shots",
        "max_qubits",
    ):
        if field in payload and field not in runtime_options:
            runtime_options[field] = payload[field]

    search_history = tuple(
        float(value) for value in payload.get("search_history", ())
    )
    if search_history and not np.isfinite(search_history).all():
        raise ValueError("search_history must contain finite objective values.")

    return HybridConfig(
        executor=executor,  # type: ignore[arg-type]
        reps=reps,
        maxiter=maxiter,
        shots=shots,
        max_candidates=max_candidates,
        neighborhood_size=neighborhood_size,
        neighborhood_mode=mode,  # type: ignore[arg-type]
        move_types=tuple(str(value) for value in move_types_value),
        initialization=initialization,  # type: ignore[arg-type]
        xy_topology=topology,  # type: ignore[arg-type]
        sample_selection_policy=policy,  # type: ignore[arg-type]
        random_seed=int(payload.get("random_seed", 42)),
        polishing_iterations=polishing_iterations,
        acceptance_epsilon=float(payload.get("acceptance_epsilon", 0.0)),
        one_hot_penalty=one_hot_penalty,
        pairwise_interactions=payload.get("pairwise_interactions"),
        capacity_pressure_threshold=float(
            payload.get("capacity_pressure_threshold", 0.90)
        ),
        route_imbalance_threshold=float(
            payload.get("route_imbalance_threshold", 0.20)
        ),
        stagnation_threshold=float(payload.get("stagnation_threshold", 0.001)),
        stagnation_window=stagnation_window,
        search_history=search_history,
        runtime_options=runtime_options,
    )


def adapt_project_payload(
    payload: Mapping[str, Any],
) -> tuple[RouteProblem, Solution]:
    """Adapt the existing matrix-based payload without backend integration."""
    required = {"matrix", "demands", "capacities", "starting_nodes"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(
            "Missing project payload fields: " + ", ".join(sorted(missing))
        )

    problem_type = str(payload.get("problem_type", "cvrp")).lower()
    problem = RouteProblem.from_data(
        payload["matrix"],
        payload["demands"],
        payload["capacities"],
        payload["starting_nodes"],
        problem_type=problem_type,  # type: ignore[arg-type]
    )

    if problem.problem_type == "sdvrp":
        if "routes" not in payload or "deliveries" not in payload:
            raise ValueError(
                "SDVRP requires supplied routes and position-aware deliveries."
            )
        routes = _copy_routes(payload["routes"])
        deliveries = _parse_deliveries(payload["deliveries"])
    else:
        routes = (
            _copy_routes(payload["routes"])
            if payload.get("routes") is not None
            else greedy_seed(problem)
        )
        deliveries = _parse_deliveries(payload.get("deliveries"))

    return problem, Solution(routes, deliveries)


def _serializable_sample(
    sample: SampleAnalysis | None,
) -> dict[str, Any] | None:
    if sample is None:
        return None
    output = asdict(sample)
    if not np.isfinite(output["energy"]):
        output["energy"] = None
    return output


def run_quasar_qaoa_xy_hybrid(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the standalone classical/local/IBM hybrid refinement pipeline."""
    total_started = perf_counter()
    classical_started = perf_counter()
    config = parse_hybrid_config(payload)
    problem, seed = adapt_project_payload(payload)
    initial = evaluate_solution(problem, seed)
    if not initial.valid:
        raise ValueError("Invalid seed: " + "; ".join(initial.violations))
    classical_runtime = perf_counter() - classical_started

    bottleneck_started = perf_counter()
    bottlenecks = detect_bottlenecks(
        problem,
        seed,
        capacity_pressure_threshold=config.capacity_pressure_threshold,
        route_imbalance_threshold=config.route_imbalance_threshold,
        search_history=config.search_history,
        stagnation_threshold=config.stagnation_threshold,
        stagnation_window=config.stagnation_window,
    )
    primary = select_primary_bottleneck(bottlenecks)
    bottleneck_runtime = perf_counter() - bottleneck_started

    if primary is None:
        return _fallback_result(
            problem=problem,
            config=config,
            initial=initial,
            bottlenecks=bottlenecks,
            primary=None,
            acceptance_reason="no_bottleneck_detected",
            total_started=total_started,
            bottleneck_runtime=bottleneck_runtime,
            classical_runtime=classical_runtime,
        )

    neighborhood = extract_difficult_neighborhood(
        problem,
        seed,
        primary,
        neighborhood_size=config.neighborhood_size,
        mode=config.neighborhood_mode,
    )
    candidates, rejected_moves = generate_candidate_moves(
        problem,
        seed,
        neighborhood,
        max_candidates=config.max_candidates,
        move_types=config.move_types,
    )
    if len(candidates) <= 1:
        return _fallback_result(
            problem=problem,
            config=config,
            initial=initial,
            bottlenecks=bottlenecks,
            primary=primary,
            neighborhood=neighborhood,
            candidates=candidates,
            rejected_moves=rejected_moves,
            acceptance_reason="no_candidate_moves",
            total_started=total_started,
            bottleneck_runtime=bottleneck_runtime,
            classical_runtime=classical_runtime,
        )

    selected_move: MoveCandidate | None = None
    selected_sample: SampleAnalysis | None = None
    analyses: list[SampleAnalysis] = []
    quantum_result: QuantumExecutionResult | None = None
    hamiltonian: CandidateHamiltonian | None = None
    execution_error: str | None = None
    quantum_runtime = 0.0

    if config.executor == "classical":
        selected_move = min(
            candidates,
            key=lambda move: (
                initial.cost + float(move.exact_delta_cost or 0.0),
                move.move_id,
            ),
        )
    else:
        quantum_started = perf_counter()
        try:
            hamiltonian = build_candidate_hamiltonian(
                [float(move.exact_delta_cost or 0.0) for move in candidates],
                one_hot_penalty=config.one_hot_penalty,
                pairwise_interactions=config.pairwise_interactions,
                candidate_ids=[move.move_id for move in candidates],
            )
            normalized_operator, _scale = normalize_operator(hamiltonian.operator)
            ansatz, parameter_order = build_qaoa_xy_circuit(
                normalized_operator,
                config.reps,
                initialization=config.initialization,
                xy_topology=config.xy_topology,
            )
            if config.executor == "local":
                quantum_result = _run_local_qaoa(
                    ansatz,
                    parameter_order,
                    normalized_operator,
                    reps=config.reps,
                    maxiter=config.maxiter,
                    shots=config.shots,
                    random_seed=config.random_seed,
                )
            else:
                quantum_result = _run_ibm_qaoa(
                    ansatz,
                    parameter_order,
                    normalized_operator,
                    reps=config.reps,
                    maxiter=config.maxiter,
                    shots=config.shots,
                    runtime_options=config.runtime_options,
                )
            analyses = analyze_samples(
                quantum_result.counts,
                hamiltonian,
                candidates,
                problem,
                seed,
            )
            selected_sample = _select_sample(
                analyses,
                config.sample_selection_policy,
            )
            if selected_sample is not None and selected_sample.selected_move:
                selected_move = _candidate_by_id(
                    candidates,
                    selected_sample.selected_move,
                )
        except Exception as error:  # Structured fallback; error is disclosed.
            execution_error = f"{type(error).__name__}: {error}"
        quantum_runtime = perf_counter() - quantum_started

    if selected_move is None:
        reason = (
            "quantum_execution_failed"
            if execution_error is not None
            else "no_valid_quantum_sample"
        )
        return _fallback_result(
            problem=problem,
            config=config,
            initial=initial,
            bottlenecks=bottlenecks,
            primary=primary,
            neighborhood=neighborhood,
            candidates=candidates,
            rejected_moves=rejected_moves,
            acceptance_reason=reason,
            total_started=total_started,
            bottleneck_runtime=bottleneck_runtime,
            classical_runtime=classical_runtime,
            quantum_runtime=quantum_runtime,
            quantum_result=quantum_result,
            hamiltonian=hamiltonian,
            analyses=analyses,
            execution_error=execution_error,
        )

    selected_solution = apply_move(problem, seed, selected_move)
    selected_evaluation = evaluate_solution(problem, selected_solution)

    polishing_started = perf_counter()
    polishing = polish_solution(
        problem,
        selected_solution,
        max_iterations=config.polishing_iterations,
    )
    polishing_runtime = perf_counter() - polishing_started
    polished_evaluation = evaluate_solution(problem, polishing.solution)
    final, accepted, acceptance_reason = improvement_gate(
        initial,
        polished_evaluation,
        epsilon=config.acceptance_epsilon,
    )

    total_runtime = perf_counter() - total_started
    feasible_analyses = [analysis for analysis in analyses if analysis.feasible]
    feasible_sample_rate = (
        sum(analysis.probability for analysis in feasible_analyses)
        if analyses
        else None
    )
    success_probability = (
        sum(
            analysis.probability
            for analysis in feasible_analyses
            if analysis.route_cost is not None
            and analysis.route_cost + config.acceptance_epsilon < initial.cost
        )
        if analyses
        else None
    )
    most_probable = max(
        analyses,
        key=lambda item: (item.probability, item.bitstring),
        default=None,
    )
    lowest_energy = min(
        (analysis for analysis in analyses if analysis.feasible),
        key=lambda item: (item.energy, item.bitstring),
        default=None,
    )
    best_objective = min(
        (
            analysis
            for analysis in analyses
            if analysis.feasible and analysis.route_cost is not None
        ),
        key=lambda item: (
            float(item.route_cost),
            -item.probability,
            item.energy,
            item.bitstring,
        ),
        default=None,
    )

    algorithm_name = (
        "QUASAR Bottleneck-Targeted QAOA+ XY Hybrid"
        if config.neighborhood_mode == "bottleneck_targeted"
        else "QUASAR Move-Based QAOA+ XY Baseline"
    )
    return {
        "algorithm": algorithm_name,
        "problem_type": problem.problem_type,
        "routes": final.solution.routes,
        "deliveries": [asdict(item) for item in final.solution.deliveries],
        "valid": final.valid,
        "violations": list(final.violations),
        "initial_routes": initial.solution.routes,
        "initial_deliveries": [
            asdict(item) for item in initial.solution.deliveries
        ],
        "initial_cost": initial.cost,
        "final_cost": final.cost,
        "route_cost": final.cost,
        "improvement": initial.cost - final.cost,
        "improvement_percent": (
            0.0
            if abs(initial.cost) <= _EPSILON
            else 100.0 * (initial.cost - final.cost) / initial.cost
        ),
        "accepted": accepted,
        "acceptance_reason": acceptance_reason,
        "bottlenecks": [asdict(item) for item in bottlenecks],
        "primary_bottleneck": asdict(primary),
        "neighborhood": asdict(neighborhood),
        "candidate_count": len(candidates),
        "candidate_moves_considered": [asdict(item) for item in candidates],
        "rejected_moves": [asdict(item) for item in rejected_moves],
        "selected_moves": [selected_move.move_id],
        "selected_move_type": selected_move.move_type,
        "selected_move_cost": selected_evaluation.cost,
        "bitstring": selected_sample.bitstring if selected_sample else None,
        "energy": selected_sample.energy if selected_sample else None,
        "n_qubits": len(candidates),
        "shots": config.shots if config.executor != "classical" else None,
        "executor": config.executor,
        "backend": quantum_result.backend if quantum_result else None,
        "job_ids": list(quantum_result.job_ids) if quantum_result else [],
        "success_prob": success_probability,
        "selected_sample_probability": (
            selected_sample.probability if selected_sample else None
        ),
        "most_probable_sample": _serializable_sample(most_probable),
        "lowest_energy_valid_sample": _serializable_sample(lowest_energy),
        "best_objective_valid_sample": _serializable_sample(best_objective),
        "feasible_sample_rate": feasible_sample_rate,
        "sample_analysis": [_serializable_sample(item) for item in analyses],
        "repaired": False,
        "repair_steps": [],
        "polishing_operations": list(polishing.operations),
        "classical_runtime": classical_runtime,
        "bottleneck_runtime": bottleneck_runtime,
        "quantum_runtime": quantum_runtime,
        "polishing_runtime": polishing_runtime,
        "total_runtime": total_runtime,
        "circuit_depth": (
            quantum_result.circuit_depth if quantum_result else None
        ),
        "two_qubit_gate_count": (
            quantum_result.two_qubit_gate_count if quantum_result else None
        ),
        "optimizer_evaluations": (
            quantum_result.optimizer_evaluations if quantum_result else 0
        ),
        "optimizer_history": (
            list(quantum_result.optimizer_history) if quantum_result else []
        ),
        "optimizer_parameters": (
            list(quantum_result.optimizer_parameters) if quantum_result else []
        ),
        "xy_topology": config.xy_topology,
        "initialization": config.initialization,
        "sample_selection_policy": config.sample_selection_policy,
        "execution_error": execution_error,
    }


def _fallback_result(
    *,
    problem: RouteProblem,
    config: HybridConfig,
    initial: EvaluatedSolution,
    bottlenecks: Sequence[Bottleneck],
    primary: Bottleneck | None,
    acceptance_reason: str,
    total_started: float,
    bottleneck_runtime: float,
    classical_runtime: float = 0.0,
    neighborhood: Neighborhood | None = None,
    candidates: Sequence[MoveCandidate] = (),
    rejected_moves: Sequence[MoveCandidate] = (),
    quantum_runtime: float = 0.0,
    quantum_result: QuantumExecutionResult | None = None,
    hamiltonian: CandidateHamiltonian | None = None,
    analyses: Sequence[SampleAnalysis] = (),
    execution_error: str | None = None,
) -> dict[str, Any]:
    total_runtime = perf_counter() - total_started
    algorithm_name = (
        "QUASAR Bottleneck-Targeted QAOA+ XY Hybrid"
        if config.neighborhood_mode == "bottleneck_targeted"
        else "QUASAR Move-Based QAOA+ XY Baseline"
    )
    most_probable = max(
        analyses,
        key=lambda item: (item.probability, item.bitstring),
        default=None,
    )
    feasible_rate = (
        sum(item.probability for item in analyses if item.feasible)
        if analyses
        else None
    )
    return {
        "algorithm": algorithm_name,
        "problem_type": problem.problem_type,
        "routes": initial.solution.routes,
        "deliveries": [asdict(item) for item in initial.solution.deliveries],
        "valid": initial.valid,
        "violations": list(initial.violations),
        "initial_routes": initial.solution.routes,
        "initial_deliveries": [
            asdict(item) for item in initial.solution.deliveries
        ],
        "initial_cost": initial.cost,
        "final_cost": initial.cost,
        "route_cost": initial.cost,
        "improvement": 0.0,
        "improvement_percent": 0.0,
        "accepted": False,
        "acceptance_reason": acceptance_reason,
        "bottlenecks": [asdict(item) for item in bottlenecks],
        "primary_bottleneck": asdict(primary) if primary else None,
        "neighborhood": asdict(neighborhood) if neighborhood else None,
        "candidate_count": len(candidates),
        "candidate_moves_considered": [asdict(item) for item in candidates],
        "rejected_moves": [asdict(item) for item in rejected_moves],
        "selected_moves": [],
        "selected_move_type": None,
        "selected_move_cost": None,
        "bitstring": None,
        "energy": None,
        "n_qubits": hamiltonian.n_qubits if hamiltonian else len(candidates),
        "shots": config.shots if config.executor != "classical" else None,
        "executor": config.executor,
        "backend": quantum_result.backend if quantum_result else None,
        "job_ids": list(quantum_result.job_ids) if quantum_result else [],
        "success_prob": None,
        "selected_sample_probability": None,
        "most_probable_sample": _serializable_sample(most_probable),
        "lowest_energy_valid_sample": None,
        "best_objective_valid_sample": None,
        "feasible_sample_rate": feasible_rate,
        "sample_analysis": [_serializable_sample(item) for item in analyses],
        "repaired": False,
        "repair_steps": [],
        "polishing_operations": [],
        "classical_runtime": classical_runtime,
        "bottleneck_runtime": bottleneck_runtime,
        "quantum_runtime": quantum_runtime,
        "polishing_runtime": 0.0,
        "total_runtime": total_runtime,
        "circuit_depth": (
            quantum_result.circuit_depth if quantum_result else None
        ),
        "two_qubit_gate_count": (
            quantum_result.two_qubit_gate_count if quantum_result else None
        ),
        "optimizer_evaluations": (
            quantum_result.optimizer_evaluations if quantum_result else 0
        ),
        "optimizer_history": (
            list(quantum_result.optimizer_history) if quantum_result else []
        ),
        "optimizer_parameters": (
            list(quantum_result.optimizer_parameters) if quantum_result else []
        ),
        "xy_topology": config.xy_topology,
        "initialization": config.initialization,
        "sample_selection_policy": config.sample_selection_policy,
        "execution_error": execution_error,
    }
