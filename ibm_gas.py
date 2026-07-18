"""
ibm_gas.py — QUASAR GAS on IBM Quantum Hardware
================================================
Grover Adaptive Search (GAS) running directly on IBM QPU
via qiskit_ibm_runtime.

Iteratively tightens an energy threshold using Grover amplification,
sampling low-energy states from the hardware.

Usage
-----
from ibm_gas import run_gas_ibm

result = run_gas_ibm({
    "matrix":         [[0,10],[10,0]],
    "demands":        [0,3],
    "capacities":     [5],
    "starting_nodes": [0],
    "iterations":     3,
    "shots":          4096,
    "token":          "YOUR_IBM_TOKEN",
})
"""

import numpy as np
from qiskit import QuantumCircuit

from hamiltonian import build_ising, normalize, hp_terms
from ibm_connection  import parse_payload, get_backend, get_pass_manager, get_sampler, best_bitstring


# ═════════════════════════════════════════════
# ENERGY EVALUATION
# ═════════════════════════════════════════════

def _eval_energy(bs: str, hterms: list[tuple[str, float]]) -> float:
    """
    Evaluate energy of a bitstring via Pauli Z eigenvalues.
    Avoids dense matrix materialization.

    spin[i] = +1 if bit[i] = 0 (|0⟩ is +1 eigenstate of Z)
    spin[i] = -1 if bit[i] = 1
    """
    spins = [1 - 2*int(b) for b in bs]
    val   = 0.0
    for pauli_str, coeff in hterms:
        nz = [(i, p) for i, p in enumerate(pauli_str) if p != "I"]
        if len(nz) == 1:
            val += coeff * spins[nz[0][0]]
        elif len(nz) == 2:
            val += coeff * spins[nz[0][0]] * spins[nz[1][0]]
    return val


# ═════════════════════════════════════════════
# CIRCUIT BUILDER
# ═════════════════════════════════════════════

def _build_grover_circuit(
    n_qubits:  int,
    hterms:    list[tuple[str, float]],
    threshold: float,
    k_steps:   int,
) -> QuantumCircuit:
    """
    Build Grover circuit with Trotterized phase oracle and standard diffuser.

    Oracle: applies phase to basis states with energy < threshold
            via RZ/RZZ gates (avoids unitary gate which requires dense matrix)
    Diffuser: H^n X^n H_{n-1} MCX H_{n-1} X^n H^n
    """
    qc = QuantumCircuit(n_qubits)
    qc.h(range(n_qubits))  # Initial state: |+⟩^n

    for _ in range(k_steps):
        # Oracle: phase kickback for low-energy states
        for pauli_str, coeff in hterms:
            if coeff >= threshold:
                continue  # only act on terms below threshold
            nz = [(i, p) for i, p in enumerate(pauli_str) if p != "I"]
            if len(nz) == 1:
                qc.rz(-np.pi * abs(coeff), nz[0][0])
            elif len(nz) == 2:
                qc.rzz(-np.pi * abs(coeff), nz[0][0], nz[1][0])

        # Diffuser: 2|s⟩⟨s| - I
        qc.h(range(n_qubits))
        qc.x(range(n_qubits))
        qc.h(n_qubits - 1)
        qc.mcx(list(range(n_qubits - 1)), n_qubits - 1)
        qc.h(n_qubits - 1)
        qc.x(range(n_qubits))
        qc.h(range(n_qubits))

    qc.measure_all()
    return qc


# ═════════════════════════════════════════════
# MAIN RUNNER
# ═════════════════════════════════════════════

def run_gas_ibm(payload: dict) -> dict:
    """
    Run Grover Adaptive Search on IBM Quantum hardware.

    Each iteration = 1 Sampler job to IBM QPU.
    Total jobs = iterations (much fewer than QAOA with maxiter evaluations).

    Parameters
    ----------
    payload : dict with keys from I/O CONTRACT

    Returns
    -------
    dict with bitstring, energy, threshold, backend, job_ids, etc.
    """
    p          = parse_payload(payload)
    n_nodes    = p["n_nodes"]
    n_vehicles = p["n_vehicles"]
    n_qubits   = n_nodes * n_nodes * n_vehicles
    shots      = p["shots"]
    iterations = p["iterations"]

    # Build and normalize Hamiltonian
    ising_op          = build_ising(
        p["matrix"], p["demands"], p["capacities"],
        n_nodes, n_vehicles, p["alpha"], p["beta"],
        p["lambda_scale"], p["demand_priority"],
    )
    ising_norm, max_c = normalize(ising_op)
    hterms            = hp_terms(ising_norm)

    # Connect to IBM
    backend = get_backend(p["token"], p["backend_name"], n_qubits)
    pm      = get_pass_manager(backend, p["optimization_level"])
    sampler = get_sampler(backend, p["use_dd"])

    # Initial threshold from random sampling (no hardware needed)
    rng             = np.random.default_rng(42)
    n_samples       = min(500, 2**n_qubits)
    sample_indices  = rng.choice(2**n_qubits, size=n_samples, replace=False)
    sample_energies = [
        _eval_energy(format(int(idx), f"0{n_qubits}b")[::-1], hterms)
        for idx in sample_indices
    ]
    threshold = float(np.percentile(sample_energies, 30))
    best_idx  = int(np.argmin(sample_energies))
    best_val  = float(sample_energies[best_idx]) * max_c
    best_bs   = format(int(sample_indices[best_idx]), f"0{n_qubits}b")[::-1]
    best_prob = 0.0

    cost_history: list[float] = []
    job_ids:      list[str]   = []

    print(f"[GAS] {iterations} iterations | {n_qubits} qubits | backend: {backend.name}")
    print(f"  Initial threshold: {threshold:.4f} | best energy: {best_val:.4f}")

    for it in range(iterations):
        # Grover steps decrease with iteration (more targeted search)
        k = max(1, int(np.sqrt(2**n_qubits) / (it + 1)))
        print(f"  Iteration {it+1}/{iterations} (k={k} Grover steps)...")

        qc      = _build_grover_circuit(n_qubits, hterms, threshold, k)
        isa_qc  = pm.run(qc)
        job     = sampler.run([(isa_qc,)], shots=shots)
        job_ids.append(job.job_id())
        counts  = job.result()[0].data.meas.get_counts()
        total   = sum(counts.values())

        # Evaluate top-10 measured bitstrings
        top_bs = sorted(counts, key=counts.get, reverse=True)[:10]
        for bs in top_bs:
            val = _eval_energy(bs, hterms) * max_c
            cost_history.append(val)
            if val < best_val:
                best_val  = val
                best_bs   = bs
                best_prob = counts[bs] / total
                threshold = _eval_energy(bs, hterms) * 0.99
                print(f"    New best: energy={val:.4f}, prob={best_prob:.3f}")

    return {
        "bitstring":    best_bs,
        "n_qubits":     n_qubits,
        "n_nodes":      n_nodes,
        "n_vehicles":   n_vehicles,
        "energy":       round(best_val, 6),
        "n_evals":      iterations,
        "threshold":    round(threshold * max_c, 6),
        "cost_history": [round(c, 4) for c in cost_history],
        "backend":      backend.name,
        "shots":        shots,
        "algorithm":    "GAS",
        "job_ids":      job_ids,
        "success_prob": round(best_prob, 4),
    }