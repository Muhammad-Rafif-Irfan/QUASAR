import os
import time
import uuid
import json
import numpy as np
from scipy.optimize import minimize

# Qiskit
from qiskit import QuantumCircuit

# Database & Models
from app.database import SessionLocal
from app.models import BenchmarkRun, QuantumJob, BenchmarkResult
from app.services.routing import calculate_distance_matrix, render_map

# OR-Tools
try:
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


def get_quantum_backend_and_sampler():
    """
    Initializes QiskitRuntimeService using token and returns:
    (backend, sampler, pass_manager, is_simulator)
    """
    # Prefer IBM_QUANTUM_TOKEN, fall back to QISKIT_IBM_TOKEN
    token = os.environ.get("IBM_QUANTUM_TOKEN") or os.environ.get("QISKIT_IBM_TOKEN")
    
    if token:
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
            from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
            
            service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)
            backend = service.least_busy(operational=True, min_num_qubits=127)
            pm = generate_preset_pass_manager(target=backend.target, optimization_level=3)
            sampler = Sampler(mode=backend)
            sampler.options.default_shots = 1024
            return backend, sampler, pm, False
        except Exception as e:
            print(f"WARNING: Failed to connect to IBM Quantum ({e}). Falling back to local simulator.")
            
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
    Solves the TSP using Google OR-Tools.
    Returns (tour, distance, wall_clock_ms).
    """
    n = len(dist_matrix)
    if not OR_TOOLS_AVAILABLE:
        # Greedy fallback
        t0 = time.time()
        tour = solve_greedy_tsp(dist_matrix)
        t_ms = (time.time() - t0) * 1000.0
        dist = tour_distance(tour, dist_matrix)
        return tour, dist, t_ms

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    def distance_callback(from_index, to_index):
        return dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
        
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 3
    
    t0 = time.time()
    assignment = routing.SolveWithParameters(params)
    t_ms = (time.time() - t0) * 1000.0
    
    ort_tour = []
    if assignment:
        idx = routing.Start(0)
        while not routing.IsEnd(idx):
            ort_tour.append(manager.IndexToNode(idx))
            idx = assignment.Value(routing.NextVar(idx))
        ort_tour.append(manager.IndexToNode(idx))
    else:
        ort_tour = solve_greedy_tsp(dist_matrix)
        
    dist = tour_distance(ort_tour, dist_matrix)
    return ort_tour, dist, t_ms


def solve_qaoa(dist_matrix: np.ndarray, backend, sampler, pm, is_simulator: bool, run_id: str, db) -> tuple[list[int], float, float]:
    """
    Executes Closed-Loop QAOA on the backend (COBYLA optimization, max 3 iterations).
    """
    n = len(dist_matrix)
    qaoa_iter = 0
    qaoa_best_tour = []
    qaoa_best_dist = float('inf')
    qaoa_total_qpu_time = 0.0

    def build_qaoa(gamma, beta):
        qc = QuantumCircuit(n-1)
        qc.h(range(n-1))
        for i in range(n-1):
            for j in range(i+1, n-1):
                qc.cx(i, j)
                qc.rz(gamma, j)
                qc.cx(i, j)
        qc.rx(beta, range(n-1))
        qc.measure_all()
        return qc

    def qaoa_obj(params):
        nonlocal qaoa_iter, qaoa_best_dist, qaoa_best_tour, qaoa_total_qpu_time
        qaoa_iter += 1
        qc = build_qaoa(params[0], params[1])
        
        backend_name = "Local Statevector Simulator" if is_simulator else backend.name
        job_id_placeholder = f"sim-qaoa-{qaoa_iter}-{uuid.uuid4().hex[:8]}" if is_simulator else "PENDING"
        
        q_job = QuantumJob(
            run_id=run_id,
            job_id=job_id_placeholder,
            algorithm=f"QAOA-Iter-{qaoa_iter}",
            backend_name=backend_name,
            status="SUBMITTED",
            qpu_time_seconds=0.0
        )
        db.add(q_job)
        db.commit()
        
        try:
            if is_simulator:
                job = sampler.run([qc])
            else:
                isa_qc = pm.run(qc)
                job = sampler.run([isa_qc])
                q_job.job_id = job.job_id()
                db.commit()
                
            result = job.result()
            
            quantum_seconds = 0.0
            if not is_simulator:
                try:
                    quantum_seconds = job.metrics().get("usage", {}).get("quantum_seconds", 0.0)
                except Exception:
                    pass
            qaoa_total_qpu_time += quantum_seconds
            
            q_job.status = "COMPLETED"
            q_job.qpu_time_seconds = quantum_seconds
            db.commit()
            
            # Robust count reading from PubResult
            data = result[0].data
            counts = None
            for attr_name in dir(data):
                attr = getattr(data, attr_name, None)
                if attr and hasattr(attr, 'get_counts'):
                    counts = attr.get_counts()
                    break
            if counts is None:
                counts = data.meas.get_counts()
                
            best_bits = max(counts, key=counts.get)
            tour = [0] + [i+1 for i, b in enumerate(reversed(best_bits)) if b == '1']
            tour.extend([i for i in range(1, n) if i not in tour])
            tour.append(0)
            
            dist = tour_distance(tour, dist_matrix)
            if dist < qaoa_best_dist:
                qaoa_best_dist = dist
                qaoa_best_tour = tour
                
            return float(dist)
        except Exception as e:
            q_job.status = "FAILED"
            db.commit()
            raise e

    minimize(qaoa_obj, [0.5, 0.5], method='COBYLA', options={'maxiter': 3})
    return qaoa_best_tour, qaoa_best_dist, qaoa_total_qpu_time


def solve_qai_hobo(dist_matrix: np.ndarray, backend, sampler, pm, is_simulator: bool, ort_tour: list[int], run_id: str, db) -> tuple[list[int], float, float]:
    """
    Executes Closed-Loop QAI+HOBO on the backend (3 temperatures: 0.8, 0.4, 0.1).
    """
    n = len(dist_matrix)
    B = max(1, int(np.ceil(np.log2(n))))
    qai_best_tour = []
    qai_best_dist = float('inf')
    qai_total_qpu_time = 0.0

    def hobo_decode(bitstring):
        bits = list(reversed(bitstring))
        pos = {c: sum(int(bits[c*B + b]) * (2**b) for b in range(B) if c*B+b < len(bits)) % n for c in range(n)}
        ordered = [None] * n
        for c, p in sorted(pos.items(), key=lambda item: item[1]):
            if ordered[p] is None: ordered[p] = c
            else:
                empty = [i for i in range(n) if ordered[i] is None]
                if empty: ordered[empty[0]] = c
        ordered = [c for c in ordered if c is not None]
        if 0 in ordered: ordered.remove(0)
        return [0] + ordered + [0]

    def build_qai(temp):
        qc = QuantumCircuit(n * B)
        qc.h(range(n * B))
        for seq, city in enumerate(ort_tour[:-1]):
            pos_ratio = seq / max(n - 1, 1)
            for b in range(B): qc.rz(pos_ratio * np.pi * (b + 1) / B, city * B + b)
        gamma = (1.0 - temp) * np.pi * 0.5 + 0.1
        qc.rx(temp * np.pi, range(n * B))
        for i in range((n * B)-1):
            qc.cx(i, i+1)
            qc.rz(gamma, i+1)
            qc.cx(i, i+1)
        qc.measure_all()
        return qc

    suhu_list = [0.8, 0.4, 0.1]
    for i, temp in enumerate(suhu_list):
        qc = build_qai(temp)
        backend_name = "Local Statevector Simulator" if is_simulator else backend.name
        job_id_placeholder = f"sim-qai-{i+1}-{uuid.uuid4().hex[:8]}" if is_simulator else "PENDING"
        
        q_job = QuantumJob(
            run_id=run_id,
            job_id=job_id_placeholder,
            algorithm=f"QAI-HOBO-Temp-{temp}",
            backend_name=backend_name,
            status="SUBMITTED",
            qpu_time_seconds=0.0
        )
        db.add(q_job)
        db.commit()
        
        try:
            if is_simulator:
                job = sampler.run([qc])
            else:
                isa_qc = pm.run(qc)
                job = sampler.run([isa_qc])
                q_job.job_id = job.job_id()
                db.commit()
                
            result = job.result()
            
            quantum_seconds = 0.0
            if not is_simulator:
                try:
                    quantum_seconds = job.metrics().get("usage", {}).get("quantum_seconds", 0.0)
                except Exception:
                    pass
            qai_total_qpu_time += quantum_seconds
            
            q_job.status = "COMPLETED"
            q_job.qpu_time_seconds = quantum_seconds
            db.commit()
            
            data = result[0].data
            counts = None
            for attr_name in dir(data):
                attr = getattr(data, attr_name, None)
                if attr and hasattr(attr, 'get_counts'):
                    counts = attr.get_counts()
                    break
            if counts is None:
                counts = data.meas.get_counts()
                
            bits = max(counts, key=counts.get)
            tour = hobo_decode(bits)
            d = tour_distance(tour, dist_matrix)
            
            if d < qai_best_dist:
                qai_best_dist = d
                qai_best_tour = tour
        except Exception as e:
            q_job.status = "FAILED"
            db.commit()
            raise e

    return qai_best_tour, qai_best_dist, qai_total_qpu_time


def run_optimization_pipeline(run_id: str, depot: dict, stops: list[dict]):
    """
    Main asynchronous worker executing classical and quantum route optimizations.
    """
    db = SessionLocal()
    try:
        # Update status to RUNNING
        run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if not run:
            return
        run.status = "RUNNING"
        db.commit()

        # Step 1: Calculate Distance Matrix
        dist_matrix, G, nodes = calculate_distance_matrix(depot, stops)
        points = [depot] + stops
        n = len(points)
        
        # Step 2: OR-Tools Classical Baseline
        ort_tour, ort_dist, ort_time_ms = solve_or_tools(dist_matrix)
        is_val, val_err = validate_tour(ort_tour, n)
        
        ort_result = BenchmarkResult(
            run_id=run_id,
            algorithm="OR-Tools",
            tour=json.dumps(ort_tour),
            distance_meters=float(ort_dist),
            is_valid=is_val,
            validation_error=val_err,
            approximation_ratio=1.0,
            execution_time_ms=ort_time_ms
        )
        db.add(ort_result)
        db.commit()
        
        # Save baseline map
        render_map(ort_tour, points, G, nodes, f"static/maps/{run_id}_OR_Tools.html", f"OR-Tools ({ort_dist}m)", "orange")

        # Step 3: Connect to Quantum Backend
        backend, sampler, pm, is_simulator = get_quantum_backend_and_sampler()

        # Step 4: Run QAOA
        t0_qaoa = time.time()
        qaoa_tour, qaoa_dist, _ = solve_qaoa(dist_matrix, backend, sampler, pm, is_simulator, run_id, db)
        qaoa_time_ms = (time.time() - t0_qaoa) * 1000.0
        
        qaoa_is_val, qaoa_val_err = validate_tour(qaoa_tour, n)
        qaoa_ratio = float(qaoa_dist / ort_dist) if ort_dist > 0 else 0.0
        
        qaoa_result = BenchmarkResult(
            run_id=run_id,
            algorithm="QUBO+QAOA",
            tour=json.dumps(qaoa_tour),
            distance_meters=float(qaoa_dist),
            is_valid=qaoa_is_val,
            validation_error=qaoa_val_err,
            approximation_ratio=qaoa_ratio,
            execution_time_ms=qaoa_time_ms
        )
        db.add(qaoa_result)
        db.commit()
        
        render_map(qaoa_tour, points, G, nodes, f"static/maps/{run_id}_QAOA.html", f"QAOA ({qaoa_dist}m)", "red")

        # Step 5: Run QAI+HOBO
        t0_qai = time.time()
        qai_tour, qai_dist, _ = solve_qai_hobo(dist_matrix, backend, sampler, pm, is_simulator, ort_tour, run_id, db)
        qai_time_ms = (time.time() - t0_qai) * 1000.0
        
        qai_is_val, qai_val_err = validate_tour(qai_tour, n)
        qai_ratio = float(qai_dist / ort_dist) if ort_dist > 0 else 0.0
        
        qai_result = BenchmarkResult(
            run_id=run_id,
            algorithm="QAI+HOBO",
            tour=json.dumps(qai_tour),
            distance_meters=float(qai_dist),
            is_valid=qai_is_val,
            validation_error=qai_val_err,
            approximation_ratio=qai_ratio,
            execution_time_ms=qai_time_ms
        )
        db.add(qai_result)
        db.commit()
        
        render_map(qai_tour, points, G, nodes, f"static/maps/{run_id}_QAI_HOBO.html", f"QAI+HOBO ({qai_dist}m)", "green")

        # Update status to COMPLETED
        run.status = "COMPLETED"
        db.commit()
        
    except Exception as e:
        # Update status to FAILED and record error message
        db.rollback()
        run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if run:
            run.status = "FAILED"
            run.error_message = str(e)
            db.commit()
        print(f"Pipeline error for run {run_id}: {e}")
    finally:
        db.close()
