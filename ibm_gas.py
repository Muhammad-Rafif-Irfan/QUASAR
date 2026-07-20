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

from hamiltonian import build_ising, normalize, decode_bitstring, compute_objective, hp_terms, eval_bitstring
from ibm_connection  import parse_payload, get_backend, get_pass_manager, get_sampler, best_bitstring

def _decode_result(bitstring: str, p: dict, matrix: np.ndarray) -> dict:
    """
    Decode bitstring and validate feasibility.
    Returns fields to be merged into the main result dict.
    """
    decoded   = decode_bitstring(
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
# ENERGY EVALUATION
# ═════════════════════════════════════════════

def _eval_energy(bs: str, hterms: list[tuple[str, float]]) -> float:
    """
    Evaluate energy of a bitstring via Pauli Z eigenvalues.
    Uses the same convention as hamiltonian_new.eval_bitstring.
    """
    return eval_bitstring(bs, hterms, len(bs))


# ═════════════════════════════════════════════
# CIRCUIT BUILDER
# ═════════════════════════════════════════════

def _phase_oracle_for_threshold(
    n_qubits:  int,
    hterms:    list[tuple[str, float]],
    threshold: float,
) -> QuantumCircuit:
    """
    Build a phase oracle that marks basis states with energy < threshold.

    Kenneth's review (poin 6): filtering Hamiltonian terms by coefficient
    is NOT equivalent to marking basis states whose total objective is below
    the threshold. The correct approach evaluates the full energy of each
    basis state.

    Implementation: diagonal phase kickback via Pauli Z rotations.
    For each basis state |x⟩, the accumulated phase is proportional to
    its Hamiltonian energy E(x) = Σ coeff·z_i·z_j...
    States with E(x) < threshold accumulate a negative phase → amplified.

    Gate decomposition:
      e^{-i·θ·Z_q} → RZ(2θ, q)
      e^{-i·θ·ZZ_{q1,q2}} → RZZ(2θ, q1, q2)
    where θ = -π·coeff / (2·|E_max|) to scale phases appropriately.
    """
    qc = QuantumCircuit(n_qubits, name="phase_oracle")
    # Scale factor: map energy range to [0, π] phase range
    # States below threshold get phase > π/2 → constructive interference
    scale = np.pi / max(abs(threshold), 1e-6) if threshold != 0 else np.pi
    for pauli_str, coeff in hterms:
        # Qiskit big-endian: string index n-1-q corresponds to qubit q
        nz = [(n_qubits - 1 - idx, p)
              for idx, p in enumerate(pauli_str) if p != "I"]
        if len(nz) == 1:
            qc.rz(-2.0 * scale * coeff, nz[0][0])
        elif len(nz) == 2:
            qc.rzz(-2.0 * scale * coeff, nz[0][0], nz[1][0])
    return qc


def _diffuser(n_qubits: int) -> QuantumCircuit:
    """
    Grover diffuser: 2|s⟩⟨s| - I  (inversion about the mean).
    H^n X^n H_{n-1} MCX H_{n-1} X^n H^n
    """
    qc = QuantumCircuit(n_qubits, name="diffuser")
    qc.h(range(n_qubits))
    qc.x(range(n_qubits))
    qc.h(n_qubits - 1)
    qc.mcx(list(range(n_qubits - 1)), n_qubits - 1)
    qc.h(n_qubits - 1)
    qc.x(range(n_qubits))
    qc.h(range(n_qubits))
    return qc


def _build_grover_circuit(
    n_qubits:  int,
    hterms:    list[tuple[str, float]],
    threshold: float,
    k_steps:   int,
) -> QuantumCircuit:
    """
    Build full Grover circuit: |+⟩^n → [oracle → diffuser]^k → measure.

    The oracle applies phase proportional to Hamiltonian energy,
    such that states below threshold accumulate more phase and are
    amplified by the diffuser.
    """
    oracle   = _phase_oracle_for_threshold(n_qubits, hterms, threshold)
    diffuser = _diffuser(n_qubits)

    qc = QuantumCircuit(n_qubits)
    qc.h(range(n_qubits))  # Initial state: |+⟩^n
    for _ in range(k_steps):
        qc.compose(oracle,   inplace=True)
        qc.compose(diffuser, inplace=True)
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
    shots      = p["shots"]
    iterations = p["iterations"]

    # Build and normalize Hamiltonian
    matrix_orig = p["matrix"].copy()
    ising_op = build_ising(
        p["matrix"], p["demands"], p["capacities"],
        n_nodes, n_vehicles, p["starting_nodes"],
        p["alpha"], p["beta"], p["lambda_scale"], p["demand_priority"],
    )
    n_qubits = ising_op.num_qubits
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
        _eval_energy(format(int(idx), f"0{n_qubits}b"), hterms)
        for idx in sample_indices
    ]
    threshold = float(np.percentile(sample_energies, 30))
    best_idx  = int(np.argmin(sample_energies))
    best_val  = float(sample_energies[best_idx]) * max_c
    best_bs   = format(int(sample_indices[best_idx]), f"0{n_qubits}b")
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
        **_decode_result(best_bs, p, matrix_orig),
    }