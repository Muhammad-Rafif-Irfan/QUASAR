"""
ibm_qaoa_plus.py — QUASAR QAOA+ on IBM Quantum Hardware
========================================================
QAOA+ (Quantum Alternating Operator Ansatz) with partial XY mixer
running directly on IBM QPU via qiskit_ibm_runtime.


Usage
-----
from research.ibm_sdvrp.ibm_qaoa_plus import run_qaoa_plus_ibm

result = run_qaoa_plus_ibm({
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
from qiskit.circuit import ParameterVector
from qiskit.circuit.library import StatePreparation

from .hamiltonian import build_ising, normalize, decode_bitstring, compute_objective, hp_terms
from .ibm_connection import parse_payload, get_backend, get_pass_manager, get_sampler, get_estimator, best_bitstring


def apply_w_state(qc, qubits):
    n = len(qubits)

    if n == 0:
        return

    if n == 1:
        qc.x(qubits[0])
        return

    state = np.zeros(2**n, dtype=complex)

    for i in range(n):
        state[1 << i] = 1 / np.sqrt(n)

    prep = StatePreparation(state)
    qc.compose(prep, qubits=qubits, inplace=True)


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


# ═════════════════════════════════════════════
# CIRCUIT BUILDER
# ═════════════════════════════════════════════

def _build_circuit(
    ising_op:   object,
    p:          int,
    n_nodes:    int,
    n_vehicles: int,
    starting_nodes: list,
) -> tuple[object, list]:
    """
    Build QAOA+ circuit with full XY mixer.

    Cost unitary   : e^{-iγ H_p} via RZ/RZZ gates
    """
    n = ising_op.num_qubits
    N = n_nodes
    K = n_vehicles
    gammas = ParameterVector('γ', p)
    betas = ParameterVector('β', p)

    P = N + 1

    def q(i, t, v):
        return i * P * K + t * K + v

    hterms = hp_terms(ising_op)

    qc = QuantumCircuit(n)
    # qc.h(range(n))  # Initial state: |+⟩^n (Skipped for QAOA+)

    # ==========================================
    # Feasible Solution Initialization
    # ==========================================

    # 1. Initialize the Depot from starting_nodes
    for v in range(K):
        depot = starting_nodes[v]
        qc.x(q(depot, 0, v))          # Start at depot
        qc.x(q(depot, P - 1, v))      # End at depot

    # 2. Initialize Customer Nodes (W-state)
    for i in range(N):
        if i in starting_nodes:
            continue  # Skip depots

        node_qubits = []
        for v in range(K):
            for t in range(1, P - 1):
                node_qubits.append(q(i, t, v))

        if node_qubits:
            apply_w_state(qc, node_qubits)
    # ==========================================
    for layer in range(p):
        # Cost unitary via RZ/RZZ (Trotterized)
        for pauli_str, coeff in hterms:
            nz = [(n - 1 - i, pp) for i, pp in enumerate(pauli_str) if pp != "I"]
            if len(nz) == 1:
                qc.rz(2 * coeff * gammas[layer], nz[0][0])
            elif len(nz) == 2:
                qc.rzz(2 * coeff * gammas[layer], nz[0][0], nz[1][0])

        # Partial XY mixer: RXX+RYY on same node+vehicle qubit pairs
        # for i in range(N):
        #    for v in range(K):
        #        for t1 in range(1, P - 1):
        #            for t2 in range(t1 + 1, P - 1):
        #                q1 = q(i, t1, v)
        #                q2 = q(i, t2, v)
        #                qc.rxx(2 * betas[layer], q1, q2)
        #                qc.ryy(2 * betas[layer], q1, q2)

        # FULL XY Mixer (For Routing Variables)
        for i in range(N):
            if i in starting_nodes:
                continue  # Skip depots for the mixer

            node_qubits = []
            for v in range(K):
                for t in range(1, P - 1):
                    node_qubits.append(q(i, t, v))

            num_q = len(node_qubits)
            for idx1 in range(num_q):
                for idx2 in range(idx1 + 1, num_q):
                    q1 = node_qubits[idx1]
                    q2 = node_qubits[idx2]

                    qc.rxx(2 * betas[layer], q1, q2)
                    qc.ryy(2 * betas[layer], q1, q2)

        # ----------------------------------------------
        # RX Mixer (For Slack Variables)
        # ----------------------------------------------
        # Total routing variables = N * P * K
        # The remaining qubits (up to n) are slack variables
        num_routing_qubits = N * P * K
        for slack_q in range(num_routing_qubits, n):
            qc.rx(2 * betas[layer], slack_q)
        # ----------------------------------------------
        # ----------------------------------------------

    return qc, list(gammas) + list(betas)


# ═════════════════════════════════════════════
# MAIN RUNNER
# ═════════════════════════════════════════════

def run_qaoa_plus_ibm(payload: dict) -> dict:
    """
    Run QAOA+ with full XY mixer on IBM Quantum hardware.

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

    # Build circuit, transpile once to get layout
    ansatz, param_list = _build_circuit(ising_norm, reps, n_nodes, n_vehicles, p["starting_nodes"])
    isa_ansatz = pm.run(ansatz)
    isa_obs = ising_norm.apply_layout(isa_ansatz.layout)

    cost_history: list[float] = []
    job_ids:      list[str] = []
    n_evals = [0]

    def objective(params: np.ndarray) -> float:
        bind_dict = dict(zip(isa_ansatz.parameters, params))
        isa_circ = isa_ansatz.assign_parameters(bind_dict)
        job = estimator.run(pubs=[(isa_circ, [isa_obs])])
        job_ids.append(job.job_id())
        val_norm = float(job.result()[0].data.evs.item())
        val = val_norm * max_c
        cost_history.append(val)
        n_evals[0] += 1
        print(f"  Eval {n_evals[0]}/{p['maxiter']}: energy = {val:.4f}")
        return val_norm

    print(f"[QAOA+] p={reps}, maxiter={p['maxiter']} | {n_qubits} qubits | backend: {backend.name}")
    x0 = np.concatenate([
        np.full(reps, 0.40),   # gamma
        np.full(reps, 0.20)    # beta
    ])
    opt = scipy.optimize.minimize(
        objective, x0, method="COBYLA",
        options={"maxiter": p["maxiter"], "rhobeg": 0.1
                 })

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
    best_objective = float("inf")
    for bs, cnt in counts.items():
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
        objective = compute_objective(decoded["routes"], matrix_orig)

        if decoded["valid"] and objective is not None:
            if objective < best_objective:
                best_objective = objective
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
        "algorithm":    "QAOA+",
        "job_ids":      job_ids,
        "success_prob": round(best_prob, 4),
        "counts":       counts,
        **_decode_result(best_bs, p, matrix_orig),
    }
