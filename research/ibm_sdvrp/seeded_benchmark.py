"""Seeded validation and benchmark script for QUASAR's experimental quantum routing solvers.

This script executes QAOA and QAOA+ on a reproducible local Aer simulator
using fixed seeds. It collects and prints scientific metrics including:
- Qubit count
- Transpiled gate depth
- Feasibility (valid tour) rate
- Success (optimal tour) rate
- Best feasible route cost
- Optimizer jobs/evaluations
- Simulator runtime
"""

import sys
import os
import time
import numpy as np

# Ensure root path is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from qiskit_aer import AerSimulator
from qiskit_aer.primitives import EstimatorV2, SamplerV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.circuit.library import qaoa_ansatz

# Import research modules
from research.ibm_sdvrp import ibm_qaoa, ibm_qaoa_plus
from research.ibm_sdvrp.ibm_qaoa import run_qaoa_ibm
from research.ibm_sdvrp.ibm_qaoa_plus import run_qaoa_plus_ibm, _build_circuit as build_qaoa_plus_circuit
from research.ibm_sdvrp.hamiltonian import build_ising, normalize, decode_bitstring, compute_objective

# Global mock for reproducible simulator runs
SIM_SEED = 42
MOCK_BACKEND = AerSimulator(seed_simulator=SIM_SEED)
MOCK_PM = generate_preset_pass_manager(optimization_level=1, backend=MOCK_BACKEND)

# Apply mock connection functions to the runner modules
for module in [ibm_qaoa, ibm_qaoa_plus]:
    module.get_backend = lambda *args, **kwargs: MOCK_BACKEND
    module.get_pass_manager = lambda backend, opt: MOCK_PM
    module.get_estimator = lambda *args, **kwargs: EstimatorV2(options={"run_options": {"seed": SIM_SEED}})
    module.get_sampler = lambda *args, **kwargs: SamplerV2(seed=SIM_SEED)


def analyze_results(results: dict, matrix: np.ndarray, optimal_cost: float) -> dict:
    """Analyze the final shot distribution to compute feasibility and optimality rates."""
    counts = results.get("counts", {})
    shots = results.get("shots", 1)

    n_nodes = results["n_nodes"]
    n_vehicles = results["n_vehicles"]
    starting_nodes = [0] * n_vehicles  # Depot is node 0 in this benchmark
    demands = np.array([0, 1, 1], dtype=float)
    capacities = np.array([5], dtype=float)

    valid_shots = 0
    optimal_shots = 0
    best_feasible_cost = float("inf")

    for bs, cnt in counts.items():
        try:
            decoded = decode_bitstring(
                bs,
                n_nodes,
                n_vehicles,
                starting_nodes,
                demands,
                capacities
            )
        except Exception:
            continue

        if decoded["valid"]:
            valid_shots += cnt
            cost = compute_objective(decoded["routes"], matrix)
            if cost < best_feasible_cost:
                best_feasible_cost = cost
            if abs(cost - optimal_cost) < 1e-5:
                optimal_shots += cnt

    feasibility_rate = valid_shots / shots
    success_rate = optimal_shots / shots

    return {
        "feasibility_rate": feasibility_rate,
        "success_rate": success_rate,
        "best_feasible_cost": best_feasible_cost if best_feasible_cost != float("inf") else None
    }


def get_transpiled_depth(ising_op, is_qaoa_plus: bool, reps: int) -> int:
    """Calculate the gate depth of the transpiled ansatz circuit."""
    ising_norm, _ = normalize(ising_op)
    if is_qaoa_plus:
        ansatz, _ = build_qaoa_plus_circuit(ising_norm, reps, 3, 1, [0])
    else:
        ansatz = qaoa_ansatz(ising_norm, reps=reps, flatten=True)

    transpiled = MOCK_PM.run(ansatz)
    return transpiled.depth()


def run_benchmark():
    print("=" * 80)
    print("QUASAR SEEDED SIMULATOR BENCHMARK (QAOA VS QAOA+)")
    print("=" * 80)
    print("Instance Details:")
    print("  Nodes: 3 (1 Depot, 2 Customers)")
    print("  Demands: [0, 1, 1] | Vehicle Capacity: 5")
    print("  Optimal Cost: 33.0 (OR-Tools baseline for depot start/return)")
    print("-" * 80)

    # Base payload parameters
    payload = {
        "matrix": [
            [0, 10, 15],
            [10, 0, 8],
            [15, 8, 0]
        ],
        "demands": [0, 1, 1],
        "capacities": [5],
        "starting_nodes": [0],
        "shots": 4096,
        "token": "DUMMY_TOKEN_FOR_BENCHMARK",
        "backend_name": "aer_simulator",
        "optimization_level": 1,
        "resilience_level": 0,
        "use_dd": False,
        "alpha": 10.0,
        "beta": 10.0,
        "lambda_scale": 10.0,
        "demand_priority": False,
        "p": 1,
        "maxiter": 15,
    }

    matrix = np.array(payload["matrix"], dtype=float)
    optimal_cost = 33.0

    # Build Ising operator to calculate qubit count and gate depth beforehand
    ising_op = build_ising(
        matrix, np.array(payload["demands"]), np.array(payload["capacities"]),
        3, 1, payload["starting_nodes"],
        payload["alpha"], payload["beta"], payload["lambda_scale"], payload["demand_priority"]
    )
    qubit_count = ising_op.num_qubits

    qaoa_depth = get_transpiled_depth(ising_op, is_qaoa_plus=False, reps=payload["p"])
    qaoa_plus_depth = get_transpiled_depth(ising_op, is_qaoa_plus=True, reps=payload["p"])

    # 1. Run Standard QAOA
    print("\nRunning Standard QAOA...")
    t0 = time.time()
    qaoa_res = run_qaoa_ibm(payload)
    qaoa_time = time.time() - t0
    qaoa_metrics = analyze_results(qaoa_res, matrix, optimal_cost)

    # 2. Run QAOA+ (with XY mixer and W-state initialization)
    print("\nRunning QAOA+ (with XY mixer)...")
    t0 = time.time()
    qaoa_plus_res = run_qaoa_plus_ibm(payload)
    qaoa_plus_time = time.time() - t0
    qaoa_plus_metrics = analyze_results(qaoa_plus_res, matrix, optimal_cost)

    # Output results in Markdown format for the walkthough and presentation
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)

    print(f"| Metric | Standard QAOA | QAOA+ (XY Mixer) |")
    print(f"| :--- | :---: | :---: |")
    print(f"| Qubits Required | {qubit_count} | {qubit_count} |")
    print(f"| Transpiled Circuit Depth | {qaoa_depth} | {qaoa_plus_depth} |")
    print(f"| Feasibility Rate (Valid Tour %) | {qaoa_metrics['feasibility_rate'] * 100:.2f}% | {qaoa_plus_metrics['feasibility_rate'] * 100:.2f}% |")
    print(f"| Success Rate (Optimal Tour %) | {qaoa_metrics['success_rate'] * 100:.2f}% | {qaoa_plus_metrics['success_rate'] * 100:.2f}% |")
    print(f"| Best Feasible Cost Found | {qaoa_metrics['best_feasible_cost']} | {qaoa_plus_metrics['best_feasible_cost']} |")
    print(f"| Optimizer Evaluations (Jobs) | {qaoa_res['n_evals'] + 1} | {qaoa_plus_res['n_evals'] + 1} |")
    print(f"| Simulator Runtime | {qaoa_time:.2f}s | {qaoa_plus_time:.2f}s |")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmark()
