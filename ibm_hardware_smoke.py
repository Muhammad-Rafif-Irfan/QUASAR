"""Manual IBM Quantum hardware smoke test for the experimental SDVRP solvers.

This script submits paid/queued remote jobs and is intentionally excluded from
the normal CI suite. Set IBM_QUANTUM_TOKEN explicitly before running it.
"""

import os

from ibm_falqon import run_falqon_ibm
from ibm_gas import run_gas_ibm
from ibm_qaoa import run_qaoa_ibm
from ibm_qaoa_plus import run_qaoa_plus_ibm


def main() -> None:
    token = os.environ.get("IBM_QUANTUM_TOKEN")
    if not token:
        raise SystemExit(
            "IBM_QUANTUM_TOKEN is required. Never put an IBM token in source code."
        )

    payload = {
        "matrix": [[0, 10], [10, 0]],
        "demands": [0, 3],
        "capacities": [5],
        "starting_nodes": [0],
        "alpha": 1.0,
        "beta": 0.5,
        "lambda_scale": 5.0,
        "demand_priority": False,
        "p": 1,
        "maxiter": 2,
        "n_layers": 2,
        "dt": 0.1,
        "iterations": 2,
        "shots": 1024,
        "token": token,
        "backend_name": None,
        "optimization_level": 1,
        "resilience_level": 0,
        "use_dd": False,
    }

    algorithms = {
        "FALQON": run_falqon_ibm,
        "GAS": run_gas_ibm,
        "QAOA": run_qaoa_ibm,
        "QAOA+": run_qaoa_plus_ibm,
    }
    failures = []

    for name, run_function in algorithms.items():
        print(f"\n[TESTING] Running {name}...")
        try:
            result = run_function(payload)
            print(f"  qubits={result['n_qubits']}")
            print(f"  bitstring={result['bitstring']}")
            print(f"  energy={result['energy']}")
            print(f"  success_probability={result['success_prob']}")
            print(f"  jobs={len(result['job_ids'])}")
        except Exception as exc:
            failures.append((name, str(exc)))
            print(f"  [FAILED] {name}: {exc}")

    if failures:
        raise SystemExit(
            "IBM hardware smoke test failed: "
            + "; ".join(f"{name}: {error}" for name, error in failures)
        )


if __name__ == "__main__":
    main()
