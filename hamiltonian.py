"""
hamiltonian.py — QUASAR Shared Ising Hamiltonian Builder
=============================================================
Shared by all IBM hardware runner modules.

Builds the Ising Hamiltonian for Split Delivery VRP (SDVRP).

EXPERIMENTAL: this formulation has known correctness blockers documented in
QUANTUM_MODULE_REVIEW.md. Do not use it for benchmark claims or the production
API until those blockers have executable regression tests.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HAMILTONIAN FORMULATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
H = H_cost + λ_A·H_node + λ_B·H_position + λ_C·H_capacity

H_cost:
  Σ_{i,j,t,v} w(i,j,v) · x[i][t][v] · x[j][t+1][v]
  w(i,j,v) = α·d(i,j) + β·(cap[v] - demand[i])²
           + γ/demand[i]  if demand_priority else 0

H_node (relaxed for SDVRP — at least once, not exactly once):
  Linear penalty for unvisited nodes only.
  Multi-visit allowed (split delivery).

H_position:
  Σ_{t,v} (Σ_i x[i][t][v] - 1)²

H_capacity:
  Σ_v (Σ_{i,t} demand[i]·x[i][t][v] - cap[v])²

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VARIABLE ENCODING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
x[i][t][v] = 1 if node i visited at position t by vehicle v
Qubit index: q(i,t,v) = i*N*K + t*K + v
Total qubits: N × N × K
"""

import numpy as np
from qiskit.quantum_info import SparsePauliOp


def build_ising(
    matrix:          np.ndarray,
    demands:         np.ndarray,
    capacities:      np.ndarray,
    n_nodes:         int,
    n_vehicles:      int,
    alpha:           float = 1.0,
    beta:            float = 0.5,
    lambda_scale:    float = 10.0,
    demand_priority: bool  = False,
) -> SparsePauliOp:
    """
    Build the Ising Hamiltonian for Split Delivery VRP.

    Parameters
    ----------
    matrix          : N×N distance matrix
    demands         : demand per node (length N)
    capacities      : capacity per vehicle (length K)
    n_nodes         : N
    n_vehicles      : K
    alpha           : distance weight in H_cost
    beta            : load-balancing weight in H_cost
    lambda_scale    : penalty scaling factor
    demand_priority : if True, nodes with larger demand are visited earlier

    Returns
    -------
    SparsePauliOp representing the full VRP Hamiltonian
    """
    N        = n_nodes
    K        = n_vehicles
    n_qubits = N * N * K

    max_d    = float(np.max(matrix)) if np.max(matrix) > 0 else 1.0
    n_cost   = max(1, N * (N - 1) * (N - 1) * K)
    base_pen = max_d * n_cost * lambda_scale
    lambda_A = base_pen
    lambda_B = base_pen
    lambda_C = base_pen * 0.5
    gamma    = alpha * max_d if demand_priority else 0.0

    pauli_dict: dict[str, float] = {}

    def _add(p: str, c: float):
        if abs(c) > 1e-12:
            pauli_dict[p] = pauli_dict.get(p, 0.0) + c

    def _I() -> str: return "I" * n_qubits
    def _Z(q: int) -> str:
        s = ["I"] * n_qubits; s[q] = "Z"; return "".join(s)
    def _ZZ(q1: int, q2: int) -> str:
        s = ["I"] * n_qubits; s[q1] = "Z"; s[q2] = "Z"; return "".join(s)
    def q(i: int, t: int, v: int) -> int:
        return i * N * K + t * K + v

    def _xx(qa: int, qb: int, c: float):
        _add(_I(), c*0.25); _add(_Z(qa), -c*0.25)
        _add(_Z(qb), -c*0.25); _add(_ZZ(qa, qb), c*0.25)

    def _x(qa: int, c: float):
        _add(_I(), c*0.5); _add(_Z(qa), -c*0.5)

    # ── H_cost ──────────────────────────────────────────────────────────────
    for v in range(K):
        for t in range(N - 1):
            for i in range(N):
                for j in range(N):
                    if i == j: continue
                    d_ij = float(matrix[i][j])
                    w    = alpha * d_ij + beta * (capacities[v] - demands[i]) ** 2
                    if demand_priority and demands[i] > 0:
                        w += gamma / float(demands[i])
                    _xx(q(i, t, v), q(j, t+1, v), w)

    # ── H_node (relaxed for SDVRP) ───────────────────────────────────────────
    for i in range(N):
        slots = [q(i, t, v) for t in range(N) for v in range(K)]
        _add(_I(), lambda_A)
        for qa in slots:
            _x(qa, -lambda_A)

    # ── H_position ──────────────────────────────────────────────────────────
    for t in range(N):
        for v in range(K):
            slots = [q(i, t, v) for i in range(N)]
            _add(_I(), lambda_B)
            for qa in slots: _x(qa, -2.0 * lambda_B)
            for idx, qa in enumerate(slots):
                _xx(qa, qa, lambda_B)
                for qb in slots[idx+1:]: _xx(qa, qb, 2.0 * lambda_B)

    # ── H_capacity ──────────────────────────────────────────────────────────
    for v in range(K):
        cap = float(capacities[v])
        _add(_I(), lambda_C * cap**2)
        for i in range(N):
            d_i = float(demands[i])
            for t in range(N):
                qa = q(i, t, v)
                _x(qa, -2.0 * lambda_C * cap * d_i)
                _xx(qa, qa, lambda_C * d_i**2)
                for j in range(N):
                    d_j = float(demands[j])
                    for tp in range(t+1, N):
                        _xx(qa, q(j, tp, v), 2.0 * lambda_C * d_i * d_j)
                for jp in range(i+1, N):
                    d_jp = float(demands[jp])
                    for tp in range(N):
                        _xx(qa, q(jp, tp, v), 2.0 * lambda_C * d_i * d_jp)

    pauli_list = [(p, c) for p, c in pauli_dict.items() if abs(c) > 1e-12]
    if not pauli_list:
        return SparsePauliOp.from_list([(_I(), 1.0)])
    return SparsePauliOp.from_list(pauli_list)


def normalize(ising_op: SparsePauliOp) -> tuple[SparsePauliOp, float]:
    """
    Normalize Hamiltonian coefficients to [-1, 1] for numerical stability.

    Returns
    -------
    normalized_op : SparsePauliOp
    max_coeff     : float — scale factor to restore original energy units
    """
    coeffs    = np.array([float(np.real(op.coeffs[0])) for op in ising_op])
    max_coeff = float(np.max(np.abs(coeffs))) if len(coeffs) > 0 else 1.0
    if max_coeff > 0:
        return ising_op / max_coeff, max_coeff
    return ising_op, 1.0


def hp_terms(ising_op: SparsePauliOp) -> list[tuple[str, float]]:
    """Extract non-identity Pauli terms from Hamiltonian."""
    return [
        (str(op.paulis[0]), float(np.real(op.coeffs[0])))
        for op in ising_op
        if not all(p == "I" for p in str(op.paulis[0]))
    ]