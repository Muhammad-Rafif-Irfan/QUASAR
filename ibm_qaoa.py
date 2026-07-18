"""
ibm_qaoa.py — QUASAR QAOA on IBM Quantum Hardware
==================================================
Standard Quantum Approximate Optimization Algorithm (QAOA)
running directly on IBM QPU via qiskit_ibm_runtime.

Uses COBYLA classical optimizer. Recommended maxiter=3-5 for
hardware to minimize job queue submissions.

Usage
-----
from ibm_qaoa import run_qaoa_ibm

result = run_qaoa_ibm({
    "matrix":         [[0,10],[10,0]],
    "demands":        [0,3],
    "capacities":     [5],
    "starting_nodes": [0],
    "p":              1,
    "maxiter":        3,
    "shots":          4096,
    "token":          "YOUR_IBM_TOKEN",
})
"""

import numpy as np
import scipy.optimize
from qiskit import QuantumCircuit
from qiskit.circuit.library import qaoa_ansatz

from hamiltonian import build_ising, normalize
from ibm_connection  import parse_payload, get_backend, get_pass_manager, get_sampler, get_estimator, best_bitstring


def run_qaoa_ibm(payload: dict) -> dict:
    """
    Run standard QAOA on IBM Quantum hardware.

    Each COBYLA evaluation = 1 Estimator job to IBM QPU.
    Keep maxiter small (3-5) to avoid long queue times.

    Parameters
    ----------
    payload : dict with keys from I/O CONTRACT

    Returns
    -------
    dict with bitstring, energy, cost_history, backend, job_ids, etc.
    """
    p          = parse_payload(payload)
    n_nodes    = p["n_nodes"]
    n_vehicles = p["n_vehicles"]
    n_qubits   = n_nodes * n_nodes * n_vehicles
    shots      = p["shots"]
    reps       = p["p"]

    # Build and normalize Hamiltonian
    ising_op          = build_ising(
        p["matrix"], p["demands"], p["capacities"],
        n_nodes, n_vehicles, p["alpha"], p["beta"],
        p["lambda_scale"], p["demand_priority"],
    )
    ising_norm, max_c = normalize(ising_op)

    # Connect to IBM
    backend   = get_backend(p["token"], p["backend_name"], n_qubits)
    pm        = get_pass_manager(backend, p["optimization_level"])
    estimator = get_estimator(backend, p["resilience_level"], p["use_dd"])
    sampler   = get_sampler(backend, p["use_dd"])

    # Build QAOA ansatz and ISA observable
    ansatz     = qaoa_ansatz(ising_norm, reps=reps, flatten=True)
    param_list = list(ansatz.parameters)
    isa_obs    = ising_norm.apply_layout(pm.run(ansatz).layout)

    cost_history: list[float] = []
    job_ids:      list[str]   = []
    n_evals = [0]

    def objective(params: np.ndarray) -> float:
        bound    = ansatz.assign_parameters(dict(zip(param_list, params)))
        isa_circ = pm.run(bound)
        job      = estimator.run(pubs=[(isa_circ, [isa_obs])])
        job_ids.append(job.job_id())
        # Optimizer works in normalized space; rescale for logging
        val_norm = float(job.result()[0].data.evs)
        val      = val_norm * max_c
        cost_history.append(val)
        n_evals[0] += 1
        print(f"  Eval {n_evals[0]}/{p['maxiter']}: energy = {val:.4f}")
        return val_norm  # return normalized value to optimizer

    print(f"[QAOA] p={reps}, maxiter={p['maxiter']} | {n_qubits} qubits | backend: {backend.name}")
    x0  = np.random.default_rng(42).uniform(-np.pi, np.pi, len(param_list))
    opt = scipy.optimize.minimize(
        objective, x0, method="COBYLA",
        options={"maxiter": p["maxiter"], "rhobeg": 0.5},
    )

    # Final sampling with optimal parameters
    print("  Final sampling...")
    bound_final = ansatz.assign_parameters(dict(zip(param_list, opt.x)))
    bound_final.measure_all()
    isa_final = pm.run(bound_final)
    job_samp  = sampler.run([(isa_final,)], shots=shots)
    job_ids.append(job_samp.job_id())
    counts    = job_samp.result()[0].data.meas.get_counts()
    best_bs, best_prob = best_bitstring(counts, shots)

    return {
        "bitstring":    best_bs,
        "n_qubits":     n_qubits,
        "n_nodes":      n_nodes,
        "n_vehicles":   n_vehicles,
        "energy":       round(float(opt.fun) * max_c, 6),
        "n_evals":      n_evals[0],
        "cost_history": [round(c, 4) for c in cost_history],
        "backend":      backend.name,
        "shots":        shots,
        "algorithm":    "QAOA",
        "job_ids":      job_ids,
        "success_prob": round(best_prob, 4),
    }