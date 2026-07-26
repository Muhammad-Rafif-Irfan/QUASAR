import os
import time
import uuid
import json
import logging
import numpy as np
from scipy.optimize import minimize

# Database & Models
from app.database import SessionLocal
from app.models import BenchmarkRun, QuantumJob, BenchmarkResult
from app.schemas import MAX_OPTIMIZATION_STOPS, MAX_QAOA_STOPS
from app.services.routing import calculate_distance_matrix, render_map
from app.services.quantum_hybrid.warm_start import run_quasar_qaoa_xy_hybrid

from core.small_tsp_qaoa import (
    best_feasible_sample,
    build_qaoa_circuit,
    cost_spectrum,
    expectation_from_counts,
    required_qubits,
)
from services.classical_solver import ORToolsSolver

logger = logging.getLogger("quasar.pipeline")

# OR-Tools availability flag (solver lives in services.classical_solver)
try:
    import ortools  # noqa: F401
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    OR_TOOLS_AVAILABLE = True
except ImportError:
    OR_TOOLS_AVAILABLE = False


def validate_tour(tour: list[int], n: int) -> tuple[bool, str | None]:
    """
    Verifies tour validity:
    1. Must start and end at the depot (index 0).
    2. Must contain exactly n + 1 stops.
    3. Intermediate stops must visit nodes 1 to n-1 exactly once (no duplicates, no omissions).
    """
    if not tour:
        return False, "Tour is empty"
    if len(tour) != n + 1:
        return False, f"Invalid tour length: expected {n+1}, got {len(tour)}"
    if tour[0] != 0:
        return False, f"Tour does not start at depot (index 0): starts with {tour[0]}"
    if tour[-1] != 0:
        return False, f"Tour does not end at depot (index 0): ends with {tour[-1]}"

    middle = tour[1:-1]
    if len(set(middle)) != len(middle):
        return False, "Tour contains duplicate visits to the same stop"

    expected_stops = set(range(1, n))
    actual_stops = set(middle)
    if expected_stops != actual_stops:
        missing = expected_stops - actual_stops
        extra = actual_stops - expected_stops
        return False, f"Tour does not visit all stops. Missing: {missing}, Extra/Invalid: {extra}"

    return True, None


def tour_distance(tour: list[int], dist_matrix: np.ndarray) -> int:
    """
    Calculates total path distance for a given tour sequence.
    """
    if len(tour) < 2:
        return 999999
    return int(sum(dist_matrix[tour[k]][tour[k + 1]] for k in range(len(tour) - 1)))


def get_quantum_backend_and_sampler(min_num_qubits: int = 1):
    """
    Initializes QiskitRuntimeService using token and returns:
    (backend, sampler, pass_manager, is_simulator)
    """
    # Prefer IBM_QUANTUM_TOKEN, fall back to QISKIT_IBM_TOKEN
    token = os.environ.get(
        "IBM_QUANTUM_TOKEN") or os.environ.get("QISKIT_IBM_TOKEN")

    if token:
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
            from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

            service = QiskitRuntimeService(
                channel="ibm_quantum_platform", token=token)
            backend = service.least_busy(
                operational=True, min_num_qubits=max(1, min_num_qubits)
            )
            pm = generate_preset_pass_manager(
                target=backend.target, optimization_level=3)
            sampler = Sampler(mode=backend)
            sampler.options.default_shots = 1024
            return backend, sampler, pm, False
        except Exception as e:
            print(
                f"WARNING: Failed to connect to IBM Quantum ({e}). Falling back to local simulator.")

    # Local Statevector Simulator fallback
    from qiskit.primitives import StatevectorSampler
    sampler = StatevectorSampler()
    return None, sampler, None, True


def solve_greedy_tsp(dist_matrix: np.ndarray) -> list[int]:
    """
    Greedy nearest-neighbor heuristic fallback for TSP if OR-Tools is unavailable.
    """
    n = len(dist_matrix)
    visited = [False] * n
    visited[0] = True
    tour = [0]
    curr = 0
    for _ in range(n - 1):
        next_node = -1
        min_dist = float('inf')
        for j in range(n):
            if not visited[j] and dist_matrix[curr][j] < min_dist:
                min_dist = dist_matrix[curr][j]
                next_node = j
        if next_node == -1:
            break
        visited[next_node] = True
        tour.append(next_node)
        curr = next_node
    tour.append(0)
    return tour


def solve_or_tools(dist_matrix: np.ndarray) -> tuple[list[int], float, float]:
    """
    Solves the TSP using the shared ORToolsSolver (services.classical_solver).
    Returns (tour, distance, wall_clock_ms).
    """
    if not OR_TOOLS_AVAILABLE:
        t0 = time.time()
        tour = solve_greedy_tsp(dist_matrix)
        t_ms = (time.time() - t0) * 1000.0
        dist = tour_distance(tour, dist_matrix)
        return tour, dist, t_ms

    solver = ORToolsSolver(dist_matrix)
    ort_tour, dist, t_ms = solver.solve()
    if not ort_tour:
        t0 = time.time()
        ort_tour = solve_greedy_tsp(dist_matrix)
        t_ms = (time.time() - t0) * 1000.0
        dist = tour_distance(ort_tour, dist_matrix)
    return ort_tour, dist, t_ms


def solve_or_tools_cvrp(
    dist_matrix: np.ndarray,
    demands: list[int],
    vehicles: list[dict],
) -> tuple[list[dict], float, float]:
    """Solve a capacitated multi-vehicle route using OR-Tools routing.

    Each route includes depot node 0 at both ends. This is deliberately a
    classical path: the current quantum encoding is single-vehicle TSP only.
    """
    if not OR_TOOLS_AVAILABLE:
        raise RuntimeError("OR-Tools is required for multi-vehicle CVRP runs")
    if len(demands) != len(dist_matrix):
        raise ValueError("demands must align with the distance matrix")

    manager = pywrapcp.RoutingIndexManager(len(dist_matrix), len(vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return int(dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    def demand_callback(index):
        return int(demands[manager.IndexToNode(index)])

    transit_index = routing.RegisterTransitCallback(distance_callback)
    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)
    routing.AddDimensionWithVehicleCapacity(
        demand_index, 0, [int(vehicle["capacity"]) for vehicle in vehicles], True, "Capacity"
    )

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parameters.time_limit.seconds = 3

    started = time.time()
    solution = routing.SolveWithParameters(parameters)
    elapsed_ms = (time.time() - started) * 1000.0
    if not solution:
        raise ValueError("OR-Tools found no capacity-feasible fleet solution")

    fleet_routes: list[dict] = []
    total_distance = 0
    served_nodes: list[int] = []
    for vehicle_index, vehicle in enumerate(vehicles):
        index = routing.Start(vehicle_index)
        route = [manager.IndexToNode(index)]
        distance = 0
        load = 0
        while not routing.IsEnd(index):
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            distance += int(dist_matrix[manager.IndexToNode(index)][next_node])
            if next_node != 0:
                load += int(demands[next_node])
                served_nodes.append(next_node)
            route.append(next_node)
            index = next_index
        total_distance += distance
        fleet_routes.append({
            "vehicle_id": vehicle["id"],
            "vehicle_name": vehicle["name"],
            "capacity": int(vehicle["capacity"]),
            "load": load,
            "route": route,
            "distance_meters": float(distance),
        })

    expected = set(range(1, len(dist_matrix)))
    if set(served_nodes) != expected or len(served_nodes) != len(expected):
        raise ValueError("CVRP validation failed: stops were not served exactly once")
    if any(route["load"] > route["capacity"] for route in fleet_routes):
        raise ValueError("CVRP validation failed: a vehicle capacity was exceeded")
    return fleet_routes, float(total_distance), elapsed_ms


def solve_nearest_neighbor(dist_matrix: np.ndarray) -> tuple[list[int], float, float]:
    """Classical nearest-neighbor TSP. Returns (tour, distance, wall_clock_ms)."""
    t0 = time.time()
    tour = solve_greedy_tsp(dist_matrix)
    t_ms = (time.time() - t0) * 1000.0
    return tour, float(tour_distance(tour, dist_matrix)), t_ms


ALLOWED_ALGORITHMS = {
    "nearest_neighbor",
    "or_tools",
    "qaoa",
}
# API clients that omit solver selection retain the inexpensive, safe
# classical comparison. The UI explicitly opts into the bounded QAOA path.
DEFAULT_ALGORITHMS = ["nearest_neighbor", "or_tools"]


def _normalize_algorithms(algorithms: list[str] | None) -> list[str]:
    if not algorithms:
        return list(DEFAULT_ALGORITHMS)
    selected: list[str] = []
    for name in algorithms:
        key = str(name).strip().lower()
        if key in ALLOWED_ALGORITHMS and key not in selected:
            selected.append(key)
    return selected or list(DEFAULT_ALGORITHMS)


def solve_qaoa(dist_matrix: np.ndarray, backend, sampler, pm, is_simulator: bool, run_id: str, db) -> tuple[list[int], float, float]:
    """
    Execute a one-layer QAOA whose diagonal phase separator encodes actual
    depot-TSP route costs. The bounded encoding is intentionally restricted to
    three customer stops, keeping every basis state independently auditable.
    """
    n = len(dist_matrix)
    if n - 1 > MAX_QAOA_STOPS:
        raise ValueError(f"QAOA supports at most {MAX_QAOA_STOPS} stops")

    tours, costs = cost_spectrum(dist_matrix)
    qaoa_iter = 0
    qaoa_total_qpu_time = 0.0
    maxiter = int(os.environ.get(
        "QAOA_SIMULATOR_MAXITER" if is_simulator else "QAOA_HARDWARE_MAXITER",
        "8" if is_simulator else "4",
    ))

    def extract_counts(result):
        data = result[0].data
        for attr_name in dir(data):
            attr = getattr(data, attr_name, None)
            if attr and hasattr(attr, "get_counts"):
                return attr.get_counts()
        return data.meas.get_counts()

    def sample(gamma: float, beta: float, label: str) -> tuple[dict[str, int], float]:
        nonlocal qaoa_total_qpu_time
        circuit = build_qaoa_circuit(costs, gamma, beta)
        backend_name = "Local Statevector Simulator" if is_simulator else backend.name
        job_id_placeholder = f"sim-qaoa-{uuid.uuid4().hex[:8]}" if is_simulator else "PENDING"
        q_job = QuantumJob(
            run_id=run_id,
            job_id=job_id_placeholder,
            algorithm=label,
            backend_name=backend_name,
            status="SUBMITTED",
            qpu_time_seconds=0.0,
        )
        db.add(q_job)
        db.commit()

        try:
            job = sampler.run([circuit]) if is_simulator else sampler.run([pm.run(circuit)])
            if not is_simulator:
                q_job.job_id = job.job_id()
                db.commit()
            result = job.result()
            quantum_seconds = 0.0
            if not is_simulator:
                try:
                    quantum_seconds = float(job.metrics().get("usage", {}).get("quantum_seconds", 0.0))
                except Exception:
                    pass
            qaoa_total_qpu_time += quantum_seconds
            q_job.status = "COMPLETED"
            q_job.qpu_time_seconds = quantum_seconds
            db.commit()
            return extract_counts(result), quantum_seconds
        except Exception:
            q_job.status = "FAILED"
            db.commit()
            raise

    def qaoa_obj(params):
        nonlocal qaoa_iter
        qaoa_iter += 1
        counts, _ = sample(
            float(params[0]), float(params[1]), f"QAOA-CostHamiltonian-Iter-{qaoa_iter}"
        )
        return expectation_from_counts(counts, costs)

    optimum = minimize(qaoa_obj, [0.2, 0.2], method="COBYLA", options={"maxiter": maxiter})
    final_counts, _ = sample(
        float(optimum.x[0]), float(optimum.x[1]), "QAOA-CostHamiltonian-Final"
    )
    best_tour, best_distance, _ = best_feasible_sample(final_counts, tours, costs)
    return best_tour, best_distance, qaoa_total_qpu_time


def run_optimization_pipeline(
    run_id: str,
    depot: dict,
    stops: list[dict],
    vehicles: list[dict] | None = None,
    algorithms: list[str] | None = None,
    quantum_mode: str = "none",
):
    """
    Asynchronous worker that runs the selected classical and/or quantum solvers.
    """
    selected = _normalize_algorithms(algorithms)
    needs_quantum = "qaoa" in selected

    if not stops or len(stops) > MAX_OPTIMIZATION_STOPS:
        raise ValueError(
            f"stops must contain between 1 and {MAX_OPTIMIZATION_STOPS} locations"
        )

    db = SessionLocal()
    try:
        run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if not run:
            return
        run.status = "RUNNING"
        db.commit()

        dist_matrix, G, nodes = calculate_distance_matrix(depot, stops)
        run.distance_metric = (
            "OSM road-network distance"
            if G is not None
            else "Haversine great-circle fallback (OSM road graph unavailable)"
        )
        db.commit()
        points = [depot] + stops
        n = len(points)

        is_fleet_run = bool(vehicles)
        if is_fleet_run and needs_quantum:
            raise ValueError("QAOA is not available for multi-vehicle CVRP runs")
        baseline_dist = None
        ort_tour = None
        ort_dist = None

        if is_fleet_run:
            fleet_routes, fleet_distance, fleet_time_ms = solve_or_tools_cvrp(
                dist_matrix,
                [0] + [int(stop.get("demand", 1)) for stop in stops],
                vehicles or [],
            )
            run.fleet_routes = json.dumps(fleet_routes)
            db.add(BenchmarkResult(
                run_id=run_id,
                algorithm="OR-Tools CVRP",
                tour=json.dumps([]),
                distance_meters=fleet_distance,
                is_valid=True,
                validation_error=None,
                approximation_ratio=1.0,
                execution_time_ms=fleet_time_ms,
            ))
            db.commit()
            if quantum_mode == "qudora_warm_start":
                try:
                    warm_payload = {
                        "matrix": dist_matrix,
                        "demands": [0] + [int(stop.get("demand", 1)) for stop in stops],
                        "capacities": [int(vehicle["capacity"]) for vehicle in vehicles or []],
                        "starting_nodes": [0 for _ in vehicles or []],
                        "routes": {str(index): route["route"] for index, route in enumerate(fleet_routes)},
                        "problem_type": "cvrp",
                        "executor": "qudora",
                        "qudora_backend": os.environ.get("QUDORA_BACKEND", "Qamelion"),
                        "shots": 64,
                        "maxiter": 8,
                        "max_candidates": 8,
                        "neighborhood_size": 8,
                        "random_seed": 42,
                    }
                    warm_result = run_quasar_qaoa_xy_hybrid(warm_payload)
                    run.quantum_warm_start = json.dumps(warm_result)
                    for job_id in warm_result.get("job_ids", []):
                        db.add(QuantumJob(
                            run_id=run_id,
                            job_id=str(job_id),
                            algorithm="QAOA+ XY warm-start",
                            backend_name=str(warm_result.get("backend") or "QUDORA"),
                            status="COMPLETED" if not warm_result.get("execution_error") else "FAILED",
                            qpu_time_seconds=None,
                        ))
                    db.commit()
                except Exception as error:
                    # The classical operational run remains valid, but the API
                    # persists a disclosed QUDORA failure rather than hiding it.
                    run.quantum_warm_start = json.dumps({
                        "algorithm": "QAOA+ XY warm-start",
                        "executor": "qudora",
                        "backend": None,
                        "job_ids": [],
                        "error": f"{type(error).__name__}: {error}",
                    })
                    db.commit()
        elif "nearest_neighbor" in selected:
            nn_tour, nn_dist, nn_time_ms = solve_nearest_neighbor(dist_matrix)
            is_val, val_err = validate_tour(nn_tour, n)
            if baseline_dist is None and nn_dist > 0:
                baseline_dist = float(nn_dist)
            db.add(BenchmarkResult(
                run_id=run_id,
                algorithm="Nearest Neighbor",
                tour=json.dumps(nn_tour),
                distance_meters=float(nn_dist),
                is_valid=is_val,
                validation_error=val_err,
                approximation_ratio=(
                    float(nn_dist / baseline_dist) if baseline_dist else None
                ),
                execution_time_ms=nn_time_ms,
            ))
            db.commit()
            render_map(
                nn_tour, points, G, nodes,
                f"static/maps/{run_id}_Nearest_Neighbor.html",
                f"Nearest Neighbor ({nn_dist}m)", "blue",
            )

        if not is_fleet_run and ("or_tools" in selected or needs_quantum):
            ort_tour, ort_dist, ort_time_ms = solve_or_tools(dist_matrix)
            is_val, val_err = validate_tour(ort_tour, n)
            if ort_dist and ort_dist > 0:
                baseline_dist = float(ort_dist)

            if "or_tools" in selected:
                db.add(BenchmarkResult(
                    run_id=run_id,
                    algorithm="OR-Tools",
                    tour=json.dumps(ort_tour),
                    distance_meters=float(ort_dist),
                    is_valid=is_val,
                    validation_error=val_err,
                    approximation_ratio=1.0 if ort_dist else None,
                    execution_time_ms=ort_time_ms,
                ))
                db.commit()
                render_map(
                    ort_tour, points, G, nodes,
                    f"static/maps/{run_id}_OR_Tools.html",
                    f"OR-Tools ({ort_dist}m)", "orange",
                )

            if "nearest_neighbor" in selected and ort_dist and ort_dist > 0:
                nn_row = (
                    db.query(BenchmarkResult)
                    .filter(
                        BenchmarkResult.run_id == run_id,
                        BenchmarkResult.algorithm == "Nearest Neighbor",
                    )
                    .first()
                )
                if nn_row:
                    nn_row.approximation_ratio = float(
                        nn_row.distance_meters / ort_dist
                    )
                    db.commit()

        if needs_quantum:
            backend, sampler, pm, is_simulator = get_quantum_backend_and_sampler(
                required_qubits(n)
            )

            if "qaoa" in selected:
                t0_qaoa = time.time()
                qaoa_tour, qaoa_dist, _ = solve_qaoa(
                    dist_matrix, backend, sampler, pm, is_simulator, run_id, db)
                qaoa_time_ms = (time.time() - t0_qaoa) * 1000.0
                qaoa_is_val, qaoa_val_err = validate_tour(qaoa_tour, n)
                ref = ort_dist if ort_dist and ort_dist > 0 else baseline_dist
                db.add(BenchmarkResult(
                    run_id=run_id,
                    algorithm="QAOA (cost Hamiltonian)",
                    tour=json.dumps(qaoa_tour),
                    distance_meters=float(qaoa_dist),
                    is_valid=qaoa_is_val,
                    validation_error=qaoa_val_err,
                    approximation_ratio=float(qaoa_dist / ref) if ref else None,
                    execution_time_ms=qaoa_time_ms,
                ))
                db.commit()
                render_map(
                    qaoa_tour, points, G, nodes,
                    f"static/maps/{run_id}_QAOA.html",
                    f"QAOA ({qaoa_dist}m)", "red",
                )

        run.status = "COMPLETED"
        db.commit()

    except Exception:
        db.rollback()
        run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if run:
            run.status = "FAILED"
            run.error_message = (
                "Optimization pipeline failed. Review server logs using this run ID."
            )
            db.commit()
        logger.exception("Pipeline error for run %s", run_id)
    finally:
        db.close()
