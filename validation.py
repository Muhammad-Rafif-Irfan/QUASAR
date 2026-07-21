import pytest
import time


import ibm_qaoa
import ibm_qaoa_plus
import ibm_falqon
import ibm_gas


from ibm_qaoa import run_qaoa_ibm
from ibm_qaoa_plus import run_qaoa_plus_ibm
from ibm_falqon import run_falqon_ibm
from ibm_gas import run_gas_ibm



# ==========================================
# MOCKING IBM CONNECTION UNTUK LOKAL / CI
# ==========================================
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import EstimatorV2, SamplerV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


for module in [ibm_qaoa, ibm_qaoa_plus, ibm_falqon, ibm_gas]:
    module.get_backend = lambda *args, **kwargs: AerSimulator()
    module.get_pass_manager = lambda backend, opt: generate_preset_pass_manager(optimization_level=0, backend=backend)
    module.get_estimator = lambda *args, **kwargs: EstimatorV2()
    module.get_sampler = lambda *args, **kwargs: SamplerV2()


def print_result(name, result, runtime):
    print("\n" + "=" * 50)
    print(f"{name} RESULTS")
    print("=" * 50)

    print(f"Execution Time : {runtime:.2f} seconds")
    print(f"Route Status   : {'VALID' if result['valid'] else 'INVALID'}")
    print(f"Route          : {result['routes']}")
    print(f"Route Cost     : {result['route_cost']}")

    if result["route_cost"] == 33:
        print("Conclusion     : SUCCESS! Optimal route found.")
    elif result["valid"]:
        print("Conclusion     : Valid solution, but not optimal.")
    else:
        print(f"Conclusion     : FAILED ({result['violations']})")


def benchmark_small_cvrp():
    print("=" * 60)
    print("Small CVRP Benchmark on Quantum Algorithms")
    print("=" * 60)

    base_payload = {
        "matrix": [
            [0, 10, 15],
            [10, 0, 8],
            [15, 8, 0]
        ],
        "demands": [0, 1, 1],
        "capacities": [5],
        "starting_nodes": [0],
        "n_nodes": 3,
        "n_vehicles": 1,

        "shots": 4096,

        "token": "DUMMY_TOKEN",
        "backend_name": "aer_simulator",
        "optimization_level": 1,
        "resilience_level": 0,
        "use_dd": False,

        "alpha": 10.0,
        "beta": 10.0,
        "lambda_scale": 10.0,
        "demand_priority": False
    }

    algorithms = [
        (
            "QAOA",
            run_qaoa_ibm,
            {
                **base_payload,
                "p": 2,
                "maxiter": 100
            }
        ),
        (
            "QAOA+",
            run_qaoa_plus_ibm,
            {
                **base_payload,
                "p": 2,
                "maxiter": 100
            }
        ),
        (
            "FALQON",
            run_falqon_ibm,
            {
                **base_payload,
                "n_layers": 20,
                "dt": 0.1
            }
        ),
        (
            "Grover Adaptive Search (GAS)",
            run_gas_ibm,
            {
                **base_payload,
                "iterations": 20,
                "max_energy_scale": 1000
            }
        )
    ]

    summary = []

    for name, algorithm, payload in algorithms:
        print(f"\nRunning {name}...")

        start = time.time()
        result = algorithm(payload)
        elapsed = time.time() - start

        print_result(name, result, elapsed)

        summary.append({
            "Algorithm": name,
            "Cost": result["route_cost"],
            "Valid": result["valid"],
            "Time (s)": round(elapsed, 2)
        })

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)

    print(f"{'Algorithm':<30}{'Cost':<10}{'Valid':<10}{'Time (s)':<10}")
    print("-" * 60)

    for item in summary:
        print(
            f"{item['Algorithm']:<30}"
            f"{str(item['Cost']):<10}"
            f"{str(item['Valid']):<10}"
            f"{item['Time (s)']:<10}"
        )


if __name__ == "__main__":
    benchmark_small_cvrp()
