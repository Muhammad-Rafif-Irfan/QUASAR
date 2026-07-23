"""
ibm_qaoa.py — QUASAR QAOA on IBM Quantum Hardware
==================================================
Standard Quantum Approximate Optimization Algorithm (QAOA)
running directly on IBM QPU via qiskit_ibm_runtime.

Uses COBYLA classical optimizer. Recommended maxiter=3-5 for
hardware to minimize job queue submissions.

Usage
-----
from research.ibm_sdvrp.ibm_qaoa import run_qaoa_ibm

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
from qiskit.circuit.library import qaoa_ansatz

from .hamiltonian import build_ising, normalize, decode_bitstring, compute_objective, hp_terms, eval_bitstring
from .ibm_connection import parse_payload, get_backend, get_pass_manager, get_sampler, get_estimator, best_bitstring


def _decode_result(bitstring: str, p: dict, matrix: np.ndarray) -> dict:
    """
    Decode bitstring and validate feasibility.
    Returns fields to be merged into the main result dict.
    """
    decoded = decode_bitstring(
        bitstring,
        p["n_nodes"],
        p["n_vehicles"],
        p["starting_nodes"],
        np.array(p["demands"], dtype=float),
        np.array(p["capacities"], dtype=float),
    )
    objective = compute_objective(decoded["routes"], matrix) if decoded["valid"] else None
    return {
        "routes":      decoded["routes"],
        "valid":       decoded["valid"],
        "violations":  decoded["violations"],
        "route_cost":  objective,
    }


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
    p = parse_payload(payload)
    n_nodes = p["n_nodes"]
    n_vehicles = p["n_vehicles"]
    shots = p["shots"]
    reps = p["p"]

    # Build and normalize Hamiltonian
    ising_op = build_ising(
        p["matrix"], p["demands"], p["capacities"],
        n_nodes, n_vehicles, p["starting_nodes"],
        p["alpha"], p["beta"], p["lambda_scale"], p["demand_priority"],
    )
    n_qubits = ising_op.num_qubits
    ising_norm, max_c = normalize(ising_op)

    # Connect to IBM
    backend = get_backend(p["token"], p["backend_name"], n_qubits)
    pm = get_pass_manager(backend, p["optimization_level"])
    estimator = get_estimator(backend, p["resilience_level"], p["use_dd"])
    sampler = get_sampler(backend, p["use_dd"])

    # Build QAOA ansatz, transpile once to get layout
    ansatz = qaoa_ansatz(ising_norm, reps=reps, flatten=True)
    param_list = list(ansatz.parameters)
    # Transpile with placeholder parameters to get layout
    isa_ansatz = pm.run(ansatz)
    isa_obs = ising_norm.apply_layout(isa_ansatz.layout)

    cost_history: list[float] = []
    job_ids:      list[str] = []
    n_evals = [0]

    def objective(params: np.ndarray) -> float:
        isa_circ = isa_ansatz.assign_parameters(params)
        job = estimator.run(pubs=[(isa_circ, [isa_obs])])
        job_ids.append(job.job_id())
        # Optimizer works in normalized space; rescale for logging
        val_norm = float(job.result()[0].data.evs)
        val = val_norm * max_c
        cost_history.append(val)
        n_evals[0] += 1
        print(f"  Eval {n_evals[0]}/{p['maxiter']}: energy = {val:.4f}")
        return val_norm  # return normalized value to optimizer

    print(f"[QAOA] p={reps}, maxiter={p['maxiter']} | {n_qubits} qubits | backend: {backend.name}")
    x0 = np.random.default_rng(42).uniform(-np.pi, np.pi, len(param_list))
    opt = scipy.optimize.minimize(
        objective, x0, method="COBYLA",
        options={"maxiter": p["maxiter"], "rhobeg": 0.5},
    )

    matrix_orig = p["matrix"].copy()

    # Final sampling with optimal parameters
    print("  Final sampling...")
    bind_dict = dict(zip(isa_ansatz.parameters, opt.x))
    isa_final = isa_ansatz.assign_parameters(bind_dict)
    isa_final.measure_all()
    job_samp = sampler.run([(isa_final,)], shots=shots)
    job_ids.append(job_samp.job_id())
    counts = job_samp.result()[0].data.meas.get_counts()

    best_bs = None
    best_prob = 0.0
    best_val = float('inf')
    for bs, cnt in counts.items():
        val = eval_bitstring(bs, hp_terms(ising_norm), n_qubits) * max_c
        try:
            decoded = decode_bitstring(
                bs,
                n_nodes,
                n_vehicles,
                p["starting_nodes"],
                np.array(p["demands"], dtype=float),
                np.array(p["capacities"], dtype=float),
            )
        except ValueError:
            continue
        if decoded["valid"] and val < best_val:
            best_val = val
            best_bs = bs
            best_prob = cnt / shots
    if best_bs is None:
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
        **_decode_result(best_bs, p, matrix_orig),
    }
