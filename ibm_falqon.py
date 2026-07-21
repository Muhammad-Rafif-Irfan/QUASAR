"""
ibm_falqon.py — QUASAR FALQON on IBM Quantum Hardware
======================================================
Feedback-based ALgorithm for Quantum OptimizatioN (FALQON)
running directly on IBM QPU via qiskit_ibm_runtime.

Beta feedback law: β_{k+1} = -A_k = -⟨ψ_k|i[H_d,H_p]|ψ_k⟩
Sequential job submission — one set of circuits per layer.

Usage
-----
from ibm_falqon import run_falqon_ibm

result = run_falqon_ibm({
    "matrix":         [[0,10],[10,0]],
    "demands":        [0,3],
    "capacities":     [5],
    "starting_nodes": [0],
    "n_layers":       3,
    "dt":             0.1,
    "shots":          4096,
    "token":          "YOUR_IBM_TOKEN",
})
"""

import numpy as np
from collections import defaultdict
from qiskit import QuantumCircuit

from hamiltonian import build_ising, normalize, decode_bitstring, compute_objective, hp_terms, eval_bitstring
from ibm_connection import parse_payload, get_backend, get_pass_manager, get_sampler, get_estimator, best_bitstring


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
# CIRCUIT BUILDERS
# ═════════════════════════════════════════════

def _build_circuit(
    n_qubits: int,
    hterms:   list[tuple[str, float]],
    betas:    list[float],
    n_layers: int,
    dt:       float,
    measure:  bool = True,
) -> QuantumCircuit:
    """
    Build FALQON circuit for n_layers with known beta sequence.

    Structure per layer k:
      e^{-i H_p dt}    via RZ/RZZ gates
      e^{-i β_k H_d dt} via RX(2β_k·dt) gates
    """
    qc = QuantumCircuit(n_qubits, n_qubits if measure else 0)
    qc.h(range(n_qubits))

    for layer in range(n_layers):
        # Cost unitary
        for pauli_str, coeff in hterms:
            nz = [(n_qubits - 1 - i, p) for i, p in enumerate(pauli_str) if p != "I"]
            if len(nz) == 1:
                qc.rz(2 * coeff * dt, nz[0][0])
            elif len(nz) == 2:
                qc.rzz(2 * coeff * dt, nz[0][0], nz[1][0])
        # Mixer unitary
        beta = betas[layer] if layer < len(betas) else 0.0
        for qq in range(n_qubits):
            qc.rx(2 * beta * dt, qq)

    if measure:
        qc.measure(range(n_qubits), range(n_qubits))
    return qc


def _group_commutator_terms(
    hterms:   list[tuple[str, float]],
    n_qubits: int,
) -> dict[int, dict[str, float]]:
    """
    Group i[H_d, H_p] terms by Y-qubit position for grouped measurement.
    Since H_d = Σ X_j and H_p is Z/ZZ:
      i[X_j, Z_j]      = 2Y_j
      i[X_j, ZZ_{jk}]  = 2Y_j Z_k
    """
    groups: dict[int, dict[str, float]] = defaultdict(dict)
    for pauli_str, coeff in hterms:
        nz = [(n_qubits - 1 - i, p) for i, p in enumerate(pauli_str) if p != "I"]
        for j in range(n_qubits):
            if len(nz) == 1:
                idx, p = nz[0]
                if p == "Z" and idx == j:
                    new = ["I"] * n_qubits
                    new[j] = "Y"
                    key = "".join(new)
                    groups[j][key] = groups[j].get(key, 0.0) + 2.0 * coeff
            elif len(nz) == 2:
                idxs = [i for i, _ in nz]
                if j in idxs:
                    other = [i for i in idxs if i != j][0]
                    new = ["I"] * n_qubits
                    new[j] = "Y"
                    new[other] = "Z"
                    key = "".join(new)
                    groups[j][key] = groups[j].get(key, 0.0) + 2.0 * coeff
    return dict(groups)


def _commutator_circuit(
    qc_base:  QuantumCircuit,
    terms:    dict[str, float],
    n_qubits: int,
) -> QuantumCircuit:
    """
    Build measurement circuit for one commutator group.
    Applies basis rotation: Y → Sdg+H, Z → no rotation.
    """
    qc = qc_base.copy()
    qc.remove_final_measurements(inplace=True)
    rotation = {}
    for pauli_str in terms:
        for i, p in enumerate(pauli_str):
            if p == "Y":
                rotation[i] = "Y"
            elif p == "X" and i not in rotation:
                rotation[i] = "X"
    for qubit, gate in rotation.items():
        if gate == "Y":
            qc.sdg(qubit)
            qc.h(qubit)
        elif gate == "X":
            qc.h(qubit)
    qc.measure_all()
    return qc


# ═════════════════════════════════════════════
# MAIN RUNNER
# ═════════════════════════════════════════════

def run_falqon_ibm(payload: dict) -> dict:
    """
    Run FALQON on IBM Quantum hardware.

    Sequential job submission per layer:
      1. Build circuit for k layers
      2. Estimator → measure ⟨H_p⟩
      3. Sampler   → measure A_k = ⟨i[H_d,H_p]⟩ (grouped by Y-qubit)
      4. Set β_{k+1} = -A_k
      5. If best energy so far → sample bitstring

    Parameters
    ----------
    payload : dict with keys from I/O CONTRACT (see module docstring)

    Returns
    -------
    dict with bitstring, energy, betas, backend, job_ids, etc.
    """
    p = parse_payload(payload)
    n_nodes = p["n_nodes"]
    n_vehicles = p["n_vehicles"]
    n_layers = p["n_layers"]
    dt = p["dt"]
    shots = p["shots"]

    # Build and normalize Hamiltonian
    matrix_orig = p["matrix"].copy()
    ising_op = build_ising(
        p["matrix"], p["demands"], p["capacities"],
        n_nodes, n_vehicles, p["starting_nodes"],
        p["alpha"], p["beta"], p["lambda_scale"], p["demand_priority"],
    )
    n_qubits = ising_op.num_qubits
    ising_norm, max_c = normalize(ising_op)
    hterms = hp_terms(ising_norm)
    comm_groups = _group_commutator_terms(hterms, n_qubits)

    # Connect to IBM
    backend = get_backend(p["token"], p["backend_name"], n_qubits)
    pm = get_pass_manager(backend, p["optimization_level"])
    sampler = get_sampler(backend, p["use_dd"])
    estimator = get_estimator(backend, p["resilience_level"], p["use_dd"])

    # ISA observable: apply layout from first actual circuit (not dummy)
    # Build layer-1 circuit to get the correct transpiled layout
    _init_circuit = _build_circuit(n_qubits, hp_terms(ising_norm), [0.0], 1, dt, measure=False)
    _isa_init = pm.run(_init_circuit)
    isa_obs = ising_norm.apply_layout(_isa_init.layout)

    betas = [0.0]
    best_energy = np.inf
    best_bs = "0" * n_qubits
    best_prob = 0.0
    job_ids = []
    energy_history = []

    print(f"[FALQON] {n_layers} layers | {n_qubits} qubits | backend: {backend.name}")

    for layer in range(1, n_layers + 1):
        print(f"  Layer {layer}/{n_layers}...")

        # Build circuit for this layer
        qc = _build_circuit(n_qubits, hterms, betas, layer, dt, measure=False)
        isa_qc = pm.run(qc)

        # ── ⟨H_p⟩ via Estimator ──
        job_est = estimator.run(pubs=[(isa_qc, [isa_obs])])
        job_ids.append(job_est.job_id())
        energy = float(job_est.result()[0].data.evs) * max_c
        energy_history.append(energy)
        print(f"    ⟨H_p⟩ = {energy:.4f}")

        # ── A_k via grouped Sampler ──
        A_k = 0.0
        for y_qubit, terms in comm_groups.items():
            comm_qc = _commutator_circuit(qc, terms, n_qubits)
            isa_comm = pm.run(comm_qc)
            job_comm = sampler.run([(isa_comm,)], shots=shots)
            job_ids.append(job_comm.job_id())
            data_bin = job_comm.result()[0].data
            register_name = list(data_bin.keys())[0]
            counts = data_bin[register_name].get_counts()
            total = sum(counts.values())
            for pauli_str, coeff in terms.items():
                non_i = [i for i, pp in enumerate(pauli_str) if pp != "I"]
                exp_p = sum(
                    (1 - 2 * (sum(int(bs[n_qubits - 1 - i]) for i in non_i) % 2))
                    * cnt / total
                    for bs, cnt in counts.items()
                )
                A_k += coeff * exp_p

        betas.append(-A_k)
        print(f"    A_k = {A_k:.6f} → β_{layer+1} = {-A_k:.6f}")

        # ── Sample bitstring if best layer ──
        if energy < best_energy:
            best_energy = energy
            qc_meas = _build_circuit(n_qubits, hterms, betas[:-1], layer, dt, measure=True)
            isa_meas = pm.run(qc_meas)
            job_samp = sampler.run([(isa_meas,)], shots=shots)
            job_ids.append(job_samp.job_id())
            data_bin_samp = job_samp.result()[0].data
            reg_name_samp = list(data_bin_samp.keys())[0]
            counts = data_bin_samp[reg_name_samp].get_counts()
            best_bs = None
            best_prob = 0.0
            best_val = float('inf')
            for bs, cnt in counts.items():
                val = eval_bitstring(bs, hterms, n_qubits) * max_c
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
        "bitstring":      best_bs,
        "n_qubits":       n_qubits,
        "n_nodes":        n_nodes,
        "n_vehicles":     n_vehicles,
        "energy":         round(best_energy, 6),
        "betas":          [round(b, 6) for b in betas],
        "energy_history": [round(e, 4) for e in energy_history],
        "backend":        backend.name,
        "shots":          shots,
        "algorithm":      "FALQON",
        "job_ids":        job_ids,
        "success_prob":   round(best_prob, 4),
        **_decode_result(best_bs, p, matrix_orig),
    }
