"""
hamiltonian.py — QUASAR Shared Ising Hamiltonian Builder
=========================================================
Provides two Hamiltonian formulations:
  - build_ising_cvrp  : for single-vehicle or no-split multi-vehicle (CVRP)
  - build_ising_sdvrp : for split-delivery multi-vehicle (SDVRP)

Selected automatically by build_ising() based on n_vehicles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VARIABLE ENCODING (shared)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
x[i][t][v] = 1 if node i visited at position t by vehicle v
Qubit index: q(i,t,v) = i*N*K + t*K + v
Total qubits: N × N × K

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CVRP FORMULATION (n_vehicles == 1, or no split)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
H = H_cost + λ_D·H_depot + λ_A·H_node + λ_B·H_position + λ_C·H_capacity

H_depot  : depot node fixed at position 0 for each vehicle
  Σ_v (1 - x[depot_v][0][v])²

H_node   : every non-depot node visited exactly once
  Σ_{i≠depot} (Σ_{t,v} x[i][t][v] - 1)²

H_position: each (position,vehicle) slot filled by exactly one node
  Σ_{t,v} (Σ_i x[i][t][v] - 1)²

H_capacity: total demand per vehicle ≤ capacity (soft penalty)
  Σ_v max(0, Σ_{i,t} demand[i]·x[i][t][v] - cap[v])²
  approximated as: Σ_v (Σ_{i,t} demand[i]·x[i][t][v] - cap[v])²

H_cost   : minimise total travel cost
  Σ_{i,j,t,v} w(i,j,v) · x[i][t][v] · x[j][t+1][v]
  w(i,j,v) = α·d(i,j) + β·(cap[v] - demand[i])²
           + γ/demand[i]  if demand_priority else 0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SDVRP FORMULATION (n_vehicles > 1, split allowed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
H = H_cost + λ_D·H_depot + λ_A·H_node + λ_B·H_position + λ_C·H_capacity

H_depot  : same as CVRP

H_node   : every non-depot node visited at least once (split allowed)
  Σ_{i≠depot} (1 - min(1, Σ_{t,v} x[i][t][v]))²
  approximate QUBO: penalize missing routes without rewarding repeated visits.
  encoded as a quadratic relaxation with positive cross terms, so repeated
  visits are not incentivized.

H_position: each (position,vehicle) slot filled by at most one node
  Σ_{t,v} (Σ_i x[i][t][v] - 1)²  [same as CVRP]

H_capacity: same soft penalty as CVRP, applied per vehicle
"""

import numpy as np
from qiskit.quantum_info import SparsePauliOp


# ═════════════════════════════════════════════
# PAULI BUILDER UTILITIES
# ═════════════════════════════════════════════

class _PauliBuilder:
    """
    Helper for building Ising Hamiltonians as SparsePauliOp.

    Pauli convention: Qiskit uses big-endian ordering in string labels,
    meaning the rightmost character corresponds to qubit 0.
    All index-to-string conversions here are consistent with this convention.

    Binary-to-spin substitution: x = (1 - Z) / 2
      x     → (I - Z) / 2
      x · x'→ (I - Z - Z' + ZZ) / 4
      x²    → x  (since x ∈ {0,1}, x² = x)
              implemented as _x, not _xx(qa, qa)
    """

    def __init__(self, n_qubits: int):
        self.n = n_qubits
        self.d: dict[str, float] = {}

    def _I(self) -> str:
        return "I" * self.n

    def _Z(self, q: int) -> str:
        """
        Single-Z Pauli string with Z at qubit q.
        Qiskit big-endian: string index = (n-1-q).
        """
        s = ["I"] * self.n
        s[self.n - 1 - q] = "Z"
        return "".join(s)

    def _ZZ(self, q1: int, q2: int) -> str:
        """Two-Z Pauli string with Z at qubits q1 and q2."""
        s = ["I"] * self.n
        s[self.n - 1 - q1] = "Z"
        s[self.n - 1 - q2] = "Z"
        return "".join(s)

    def add(self, pauli: str, coeff: float):
        if abs(coeff) > 1e-12:
            self.d[pauli] = self.d.get(pauli, 0.0) + coeff

    def x(self, qa: int, coeff: float):
        """
        Add terms for linear variable x[qa]:
          x = (I - Z) / 2
          coeff·x → coeff/2·I - coeff/2·Z
        """
        self.add(self._I(),    coeff * 0.5)
        self.add(self._Z(qa), -coeff * 0.5)

    def xx(self, qa: int, qb: int, coeff: float):
        """
        Add terms for quadratic product x[qa]·x[qb] where qa ≠ qb:
          x·x' = (I - Z - Z' + ZZ) / 4
        Note: for qa == qb use x() instead, since x² = x for binary vars.
        """
        assert qa != qb, "Use x() for diagonal terms x²=x, not xx()"
        self.add(self._I(),        coeff * 0.25)
        self.add(self._Z(qa),     -coeff * 0.25)
        self.add(self._Z(qb),     -coeff * 0.25)
        self.add(self._ZZ(qa, qb), coeff * 0.25)

    def build(self) -> SparsePauliOp:
        pauli_list = [(p, c) for p, c in self.d.items() if abs(c) > 1e-12]
        if not pauli_list:
            return SparsePauliOp.from_list([("I" * self.n, 1.0)])
        return SparsePauliOp.from_list(pauli_list)


def _qubit_index(i: int, t: int, v: int, N: int, P: int, K: int) -> int:
    """Qubit index for variable x[i][t][v] = i*P*K + t*K + v."""
    return i * P * K + t * K + v


def _slack_bits(capacities: np.ndarray) -> list[int]:
    """Compute binary slack width per vehicle for capacity inequalities."""
    bits = []
    for cap in capacities:
        cap_int = int(np.ceil(float(cap))) if cap > 0 else 0
        bits.append(0 if cap_int <= 0 else int(np.floor(np.log2(cap_int)) + 1))
    return bits


def _slack_qubit_index(
    v: int,
    b: int,
    N: int,
    P: int,
    K: int,
    slack_bits: list[int],
    delivery_bits: list[int] | None = None,
) -> int:
    """Qubit index for vehicle slack bit s[v,b] appended after route and delivery qubits."""
    route_qubits = N * P * K
    delivery_qubits = sum(delivery_bits) * P * K if delivery_bits is not None else 0
    offset = sum(slack_bits[:v])
    return route_qubits + delivery_qubits + offset + b


def _delivery_bits(demands: np.ndarray) -> list[int]:
    """Compute per-node binary widths for delivery quantities."""
    bits = []
    for d in demands:
        val = int(np.ceil(float(d))) if d > 0 else 0
        bits.append(0 if val == 0 else int(np.floor(np.log2(val)) + 1))
    return bits


def _delivery_qubit_index(
    i: int,
    t: int,
    v: int,
    b: int,
    N: int,
    P: int,
    K: int,
    delivery_bits: list[int],
) -> int:
    """Qubit index for delivered quantity bit y[i,t,v,b] after route qubits."""
    route_qubits = N * P * K
    offset = sum(d * P * K for d in delivery_bits[:i])
    visit_index = t * K + v
    return route_qubits + offset + visit_index * delivery_bits[i] + b


# ═════════════════════════════════════════════
# SHARED HAMILTONIAN TERMS
# ═════════════════════════════════════════════

def _add_h_cost(
    pb: _PauliBuilder,
    matrix: np.ndarray,
    demands: np.ndarray,
    capacities: np.ndarray,
    N: int, P: int, K: int,
    alpha: float, beta: float, gamma: float,
    demand_priority: bool,
):
    """
    H_cost: Σ_{i,j,t,v} w(i,j,v) · x[i][t][v] · x[j][t+1][v]
    w(i,j,v) = α·d(i,j) + β·(cap[v]-demand[i])² + γ/demand[i]
    """
    q = _qubit_index
    for v in range(K):
        for t in range(P - 1):
            for i in range(N):
                for j in range(N):
                    if i == j:
                        continue
                    d_ij = float(matrix[i][j])
                    w = alpha * d_ij + beta * (capacities[v] - demands[i]) ** 2
                    if demand_priority and demands[i] > 0:
                        w += gamma / float(demands[i])
                    pb.xx(q(i, t, v, N, P, K), q(j, t + 1, v, N, P, K), w)


def _add_h_depot(
    pb: _PauliBuilder,
    starting_nodes: list,
    N: int, P: int, K: int,
    lambda_D: float,
):
    """
    H_depot: depot at start and end positions for each vehicle.
    Forces each vehicle v to start at depot at t=0 and return at t=P-1.
    """
    q = _qubit_index
    for v in range(K):
        depot = starting_nodes[v]
        qa0 = q(depot, 0, v, N, P, K)
        qa_end = q(depot, P - 1, v, N, P, K)
        pb.add(pb._I(), 2.0 * lambda_D)
        pb.x(qa0, -lambda_D)
        pb.x(qa_end, -lambda_D)


def _add_h_route_shape(
    pb: _PauliBuilder,
    starting_nodes: list,
    N: int, P: int, K: int,
    lambda_D: float,
):
    """
    Enforce route shape constraints for CVRP:
      - depot can only appear at t=0 and t=P-1
      - customers cannot occupy t=0 or t=P-1
    """
    q = _qubit_index
    depot_set = set(starting_nodes)
    for v in range(K):
        depot = starting_nodes[v]
        for t in range(1, P - 1):
            pb.x(q(depot, t, v, N, P, K), lambda_D)
        for i in range(N):
            if i in depot_set:
                continue
            for t in (0, P - 1):
                pb.x(q(i, t, v, N, P, K), lambda_D)


def _add_h_position(
    pb: _PauliBuilder,
    N: int, P: int, K: int,
    lambda_B: float,
):
    """
    H_position: Σ_{t,v} (Σ_i x[i][t][v] - 1)²
    Each (position, vehicle) slot filled by exactly one node.
    Expanded: Σ_{t,v} [Σ_i x² + 2·Σ_{i<j} x·x' - 2·Σ_i x + 1]
            = Σ_{t,v} [Σ_i x + 2·Σ_{i<j} x·x' - 2·Σ_i x + 1]   (x²=x)
            = Σ_{t,v} [1 - Σ_i x + 2·Σ_{i<j} x·x']
    """
    q = _qubit_index
    for t in range(P):
        for v in range(K):
            slots = [q(i, t, v, N, P, K) for i in range(N)]
            # constant +1
            pb.add(pb._I(), lambda_B)
            for qa in slots:
                # diagonal x²=x contributes +x, minus 2x from cross → net -x
                pb.x(qa, -lambda_B)
            for idx, qa in enumerate(slots):
                for qb in slots[idx + 1:]:
                    pb.xx(qa, qb, 2.0 * lambda_B)


def _add_h_position_sdvrp(
    pb: _PauliBuilder,
    N: int, P: int, K: int,
    lambda_B: float,
):
    """
    H_position (SDVRP): at most one node per slot.
    Penalizes only pairwise conflicts in the same position and vehicle.
    """
    q = _qubit_index
    for t in range(P):
        for v in range(K):
            slots = [q(i, t, v, N, P, K) for i in range(N)]
            for idx, qa in enumerate(slots):
                for qb in slots[idx + 1:]:
                    pb.xx(qa, qb, 2.0 * lambda_B)


def _add_h_node_sdvrp(
    pb: _PauliBuilder,
    starting_nodes: list,
    N: int, P: int, K: int,
    lambda_A: float,
):
    """
    H_node for SDVRP: penalize missing non-depot nodes.
    Uses a quadratic relaxation that does not reward repeated visits.
    """
    q = _qubit_index
    depot_set = set(starting_nodes)
    for i in range(N):
        if i in depot_set:
            continue
        slots = [q(i, t, v, N, P, K) for t in range(1, P - 1) for v in range(K)]
        pb.add(pb._I(), lambda_A)
        for qa in slots:
            pb.x(qa, -lambda_A)
        for idx, qa in enumerate(slots):
            for qb in slots[idx + 1:]:
                pb.xx(qa, qb, 2.0 * lambda_A)


def _add_h_capacity(
    pb: _PauliBuilder,
    demands: np.ndarray,
    capacities: np.ndarray,
    N: int, P: int, K: int,
    lambda_C: float,
    slack_bits: list[int],
    delivery_bits: list[int] | None = None,
):
    """
    H_capacity: Σ_v (Σ_{i,t} delivered[i,t,v] + slack[v] - cap[v])²
    This enforces the capacity inequality by introducing slack bits for
    each vehicle. For CVRP, delivered[i,t,v] reduces to demand[i]·x[i,t,v].
    """
    q = _qubit_index
    qy = _delivery_qubit_index
    sq = _slack_qubit_index
    if delivery_bits is None:
        delivery_bits = [0] * N

    for v in range(K):
        cap = float(capacities[v])
        bit_width = slack_bits[v]
        slack_weights = [2**b for b in range(bit_width)]

        # constant cap²
        pb.add(pb._I(), lambda_C * cap ** 2)

        # delivery terms and cross terms
        delivered_bits = []
        delivered_weights = []
        for i in range(N):
            width = delivery_bits[i]
            if width == 0:
                for t in range(P):
                    qa = q(i, t, v, N, P, K)
                    delivered_bits.append(qa)
                    delivered_weights.append(float(demands[i]))
                continue
            for t in range(1, P - 1):
                for b, w in enumerate([2**bb for bb in range(width)]):
                    delivered_bits.append(qy(i, t, v, b, N, P, K, delivery_bits))
                    delivered_weights.append(w)

        # linear and quadratic terms among delivered bits
        for idx, qa in enumerate(delivered_bits):
            w = delivered_weights[idx]
            pb.x(qa, lambda_C * (w * w - 2.0 * cap * w))
            for qb_idx in range(idx + 1, len(delivered_bits)):
                qb = delivered_bits[qb_idx]
                wp = delivered_weights[qb_idx]
                pb.xx(qa, qb, 2.0 * lambda_C * w * wp)

        # cross terms with slack bits
        for idx, qa in enumerate(delivered_bits):
            w = delivered_weights[idx]
            for b, ws in enumerate(slack_weights):
                qb = sq(v, b, N, P, K, slack_bits, delivery_bits)
                pb.xx(qa, qb, 2.0 * lambda_C * w * ws)

        # slack terms
        for b, ws in enumerate(slack_weights):
            qb = sq(v, b, N, P, K, slack_bits, delivery_bits)
            pb.x(qb, lambda_C * (ws * ws - 2.0 * cap * ws))
            for bp in range(b + 1, bit_width):
                qb2 = sq(v, bp, N, P, K, slack_bits)
                pb.xx(qb, qb2, 2.0 * lambda_C * ws * (2 ** bp))


# ═════════════════════════════════════════════
# CVRP HAMILTONIAN
# ═════════════════════════════════════════════

def build_ising_cvrp(
    matrix:          np.ndarray,
    demands:         np.ndarray,
    capacities:      np.ndarray,
    n_nodes:         int,
    n_vehicles:      int,
    starting_nodes:  list,
    alpha:           float = 1.0,
    beta:            float = 0.5,
    lambda_scale:    float = 10.0,
    demand_priority: bool = False,
) -> SparsePauliOp:
    """
    Build Ising Hamiltonian for CVRP (no split delivery).
    Each non-depot node is assigned exactly once to a middle route position.

    Positions: t=0 is depot start, t=P-1 is depot return, P = N + 1.
    H = H_cost + λ_D·H_depot + λ_A·H_node + λ_B·H_position + λ_C·H_capacity
    """
    N = n_nodes
    P = N + 1
    K = n_vehicles
    slack_bits = _slack_bits(capacities)
    n_qubits = N * P * K + sum(slack_bits)
    pb = _PauliBuilder(n_qubits)

    max_d = float(np.max(matrix)) if np.max(matrix) > 0 else 1.0
    n_cost = max(1, N * (N - 1) * (N - 1) * K)
    base_pen = max_d * n_cost * lambda_scale
    lambda_D = base_pen * 2.0   # depot constraint (hard)
    lambda_A = base_pen          # node constraint (hard)
    lambda_B = base_pen          # position constraint (hard)
    lambda_C = base_pen * 0.5   # capacity constraint (soft)
    gamma = alpha * max_d if demand_priority else 0.0

    q = _qubit_index
    depot_set = set(starting_nodes)

    # H_cost
    _add_h_cost(pb, matrix, demands, capacities, N, P, K, alpha, beta, gamma, demand_priority)

    # H_depot start + return
    _add_h_depot(pb, starting_nodes, N, P, K, lambda_D)
    _add_h_route_shape(pb, starting_nodes, N, P, K, lambda_D)

    # H_node: every non-depot node visited exactly once in middle positions
    # (Σ_{t=1..P-2,v} x[i][t][v] - 1)²
    for i in range(N):
        if i in depot_set:
            continue  # depot handled by H_depot and H_route_shape
        slots = [q(i, t, v, N, P, K) for t in range(1, P - 1) for v in range(K)]
        pb.add(pb._I(), lambda_A)
        for qa in slots:
            pb.x(qa, -lambda_A)
        for idx, qa in enumerate(slots):
            for qb in slots[idx + 1:]:
                pb.xx(qa, qb, 2.0 * lambda_A)

    # H_position
    _add_h_position(pb, N, P, K, lambda_B)

    # H_capacity
    _add_h_capacity(pb, demands, capacities, N, P, K, lambda_C, slack_bits)

    return pb.build()


# ═════════════════════════════════════════════
# SDVRP HAMILTONIAN
# ═════════════════════════════════════════════

def build_ising_sdvrp(
    matrix:          np.ndarray,
    demands:         np.ndarray,
    capacities:      np.ndarray,
    n_nodes:         int,
    n_vehicles:      int,
    starting_nodes:  list,
    alpha:           float = 1.0,
    beta:            float = 0.5,
    lambda_scale:    float = 10.0,
    demand_priority: bool = False,
) -> SparsePauliOp:
    """
    Build Ising Hamiltonian for SDVRP (split delivery allowed) with delivered
    quantity bits.

    Variables:
      x[i,t,v]  = visit node i at position t by vehicle v
      y[i,t,v,b] = delivered quantity bit b for visit x[i,t,v]
      s[v,b]    = capacity slack bit for vehicle v

    Constraints:
      - if y bit is active then x must be active
      - total delivered per node equals demand
      - total delivered per vehicle + slack = capacity
      - route shape, depot start/return, and slot conflicts
    """
    N = n_nodes
    P = N + 1
    K = n_vehicles
    delivery_bits = _delivery_bits(demands)
    slack_bits = _slack_bits(capacities)
    route_qubits = N * P * K
    delivery_qubits = sum(delivery_bits) * P * K
    n_qubits = route_qubits + delivery_qubits + sum(slack_bits)
    pb = _PauliBuilder(n_qubits)

    max_d = float(np.max(matrix)) if np.max(matrix) > 0 else 1.0
    n_cost = max(1, N * (N - 1) * (N - 1) * K)
    base_pen = max_d * n_cost * lambda_scale
    lambda_D = base_pen * 2.0
    lambda_A = base_pen
    lambda_B = base_pen
    lambda_C = base_pen * 0.5
    gamma = alpha * max_d if demand_priority else 0.0

    q = _qubit_index
    qy = _delivery_qubit_index
    depot_set = set(starting_nodes)

    # Route cost
    _add_h_cost(pb, matrix, demands, capacities, N, P, K, alpha, beta, gamma, demand_priority)

    # Depot constraints and route shape
    _add_h_depot(pb, starting_nodes, N, P, K, lambda_D)
    _add_h_route_shape(pb, starting_nodes, N, P, K, lambda_D)

    # Delivery implies visit
    for i in range(N):
        if delivery_bits[i] == 0:
            continue
        for t in range(1, P - 1):
            for v in range(K):
                qa = q(i, t, v, N, P, K)
                for b, w in enumerate([2**bb for bb in range(delivery_bits[i])]):
                    qb = qy(i, t, v, b, N, P, K, delivery_bits)
                    pb.x(qb, lambda_A * w)
                    pb.xx(qa, qb, -lambda_A * w)

    # Node coverage for SDVRP
    _add_h_node_sdvrp(pb, starting_nodes, N, P, K, lambda_A)

    # Demand fulfillment per customer
    for i in range(N):
        if i in depot_set:
            continue
        width = delivery_bits[i]
        if width == 0:
            continue
        demand_i = float(demands[i])
        weights = [2**b for b in range(width)]
        slots = []
        slot_wts = []
        for t in range(1, P - 1):
            for v in range(K):
                for b in range(width):
                    slots.append(qy(i, t, v, b, N, P, K, delivery_bits))
                    slot_wts.append(weights[b])

        pb.add(pb._I(), lambda_A * demand_i ** 2)
        for idx, qa in enumerate(slots):
            w = slot_wts[idx]
            pb.x(qa, lambda_A * (w * w - 2.0 * demand_i * w))
            for qb_idx in range(idx + 1, len(slots)):
                qb = slots[qb_idx]
                wp = slot_wts[qb_idx]
                pb.xx(qa, qb, 2.0 * lambda_A * w * wp)

    # Route slot conflicts for SDVRP (at most one node per slot)
    _add_h_position_sdvrp(pb, N, P, K, lambda_B)

    # Capacity inequality with slack bits
    _add_h_capacity(pb, demands, capacities, N, P, K, lambda_C, slack_bits, delivery_bits)

    return pb.build()


# ═════════════════════════════════════════════
# AUTO-SELECTOR
# ═════════════════════════════════════════════

def build_ising(
    matrix:          np.ndarray,
    demands:         np.ndarray,
    capacities:      np.ndarray,
    n_nodes:         int,
    n_vehicles:      int,
    starting_nodes:  list,
    alpha:           float = 1.0,
    beta:            float = 0.5,
    lambda_scale:    float = 10.0,
    demand_priority: bool = False,
) -> SparsePauliOp:
    """
    Auto-select CVRP or SDVRP Hamiltonian based on n_vehicles.
    """
    if n_vehicles == 1:
        return build_ising_cvrp(
            matrix, demands, capacities, n_nodes, n_vehicles,
            starting_nodes, alpha, beta, lambda_scale, demand_priority,
        )
    return build_ising_sdvrp(
        matrix, demands, capacities, n_nodes, n_vehicles,
        starting_nodes, alpha, beta, lambda_scale, demand_priority,
    )


# ═════════════════════════════════════════════
# NORMALIZATION & UTILITIES
# ═════════════════════════════════════════════

def normalize(ising_op: SparsePauliOp) -> tuple[SparsePauliOp, float]:
    """
    Normalize Hamiltonian coefficients to [-1, 1] for numerical stability.

    Returns
    -------
    normalized_op : SparsePauliOp
    max_coeff     : float — scale factor to restore original energy units
    """
    coeffs = np.array([float(np.real(op.coeffs[0])) for op in ising_op])
    max_coeff = float(np.max(np.abs(coeffs))) if len(coeffs) > 0 else 1.0
    if max_coeff > 0:
        return ising_op / max_coeff, max_coeff
    return ising_op, 1.0


def hp_terms(ising_op: SparsePauliOp) -> list[tuple[str, float]]:
    """
    Extract non-identity Pauli terms from Hamiltonian.
    Returns list of (pauli_string, coefficient).
    Pauli strings use Qiskit big-endian convention.
    """
    return [
        (str(op.paulis[0]), float(np.real(op.coeffs[0])))
        for op in ising_op
        if not all(p == "I" for p in str(op.paulis[0]))
    ]


# ═════════════════════════════════════════════
# BITSTRING UTILITIES
# ═════════════════════════════════════════════

def eval_bitstring(
    bitstring: str,
    hterms:    list[tuple[str, float]],
    n_qubits:  int,
) -> float:
    """
    Evaluate energy of a bitstring via Pauli Z eigenvalues.

    Qiskit big-endian convention:
      bitstring[n-1-q] = measurement outcome of qubit q
      Z eigenvalue: +1 if measured 0, -1 if measured 1

    Parameters
    ----------
    bitstring : str of length n_qubits (Qiskit big-endian)
    hterms    : list of (pauli_string, coefficient)
    n_qubits  : total number of qubits
    """
    n = n_qubits
    # spin[q] = +1 if bitstring[n-1-q]='0', -1 if '1'
    spins = {q: (1 - 2 * int(bitstring[n - 1 - q])) for q in range(n)}
    val = 0.0
    for pauli_str, coeff in hterms:
        # Qiskit big-endian: pauli_str[n-1-q] is the operator on qubit q
        nz = [(n - 1 - idx, p) for idx, p in enumerate(pauli_str) if p != "I"]
        if len(nz) == 0:
            val += coeff  # identity term
        elif len(nz) == 1:
            val += coeff * spins[nz[0][0]]
        elif len(nz) == 2:
            val += coeff * spins[nz[0][0]] * spins[nz[1][0]]
    return val


def decode_bitstring(
    bitstring:      str,
    n_nodes:        int,
    n_vehicles:     int,
    starting_nodes: list,
    demands:        np.ndarray | None = None,
    capacities:     np.ndarray | None = None,
) -> dict:
    """
    Decode bitstring into routes per vehicle.

    Returns
    -------
    {
        "routes"     : {"0": [depot, node_a, node_b, ...], "1": [...], ...}
        "assignment" : {node: [list of vehicles that visit it]}
        "deliveries" : {(i,t,v): qty} for SDVRP delivery bits
        "slack"      : {vehicle: slack_value}
        "valid"      : bool — True if all feasibility constraints satisfied
        "violations" : list of violation descriptions
    }
    """
    N = n_nodes
    K = n_vehicles
    n = len(bitstring)
    P = N + 1
    route_qubits = N * P * K
    if n < route_qubits:
        raise ValueError(
            f"Invalid bitstring length {n}; expected at least {route_qubits} for N={n_nodes}, K={n_vehicles}"
        )

    def q(i, t, v):
        return i * P * K + t * K + v

    # Parse x[i][t][v] from bitstring (big-endian: bit q → bitstring[n-1-q])
    x = {}
    for i in range(N):
        for t in range(P):
            for v in range(K):
                idx = q(i, t, v)
                x[i, t, v] = int(bitstring[n - 1 - idx])

    # Build routes: ordered list of nodes at each position per vehicle
    routes = {}
    assignment = {i: [] for i in range(N)}
    for v in range(K):
        route = []
        for t in range(P):
            for i in range(N):
                if x[i, t, v] == 1:
                    route.append((t, i))
                    assignment[i].append(v)
        route.sort()
        routes[str(v)] = [i for _, i in route]

    # Parse delivery and slack bits when demands/capacities are provided
    deliveries = {}
    slack_values = {}
    delivery_bits = None
    if demands is not None and capacities is not None:
        delivery_bits = _delivery_bits(np.asarray(demands, dtype=float))
        delivery_qubits = sum(delivery_bits) * P * K
        slack_bits = _slack_bits(np.asarray(capacities, dtype=float))
        no_delivery_len = route_qubits + sum(slack_bits)
        delivery_len = route_qubits + delivery_qubits + sum(slack_bits)

        if n == no_delivery_len:
            # CVRP / route-only encoding with slack bits
            def sq(v, b):
                route_qubits = N * P * K
                offset = sum(slack_bits[:v])
                return route_qubits + offset + b

            for i in range(N):
                for t in range(P):
                    for v in range(K):
                        if x[i, t, v] == 1 and float(demands[i]) > 0:
                            deliveries[(i, t, v)] = float(demands[i])

            for v in range(K):
                slack_values[v] = 0
                for b in range(slack_bits[v]):
                    idx = sq(v, b)
                    slack_values[v] += int(bitstring[n - 1 - idx]) * (2**b)

        elif n == delivery_len:
            # Full SDVRP encoding with delivery bits
            def qy(i, t, v, b):
                route_qubits = N * P * K
                offset = sum(d * P * K for d in delivery_bits[:i])
                visit_index = t * K + v
                return route_qubits + offset + visit_index * delivery_bits[i] + b

            def sq(v, b):
                route_qubits = N * P * K
                delivery_qubits = sum(delivery_bits) * P * K
                offset = sum(slack_bits[:v])
                return route_qubits + delivery_qubits + offset + b

            for i in range(N):
                for t in range(P):
                    for v in range(K):
                        if delivery_bits[i] == 0:
                            continue
                        qty = 0
                        for b in range(delivery_bits[i]):
                            qidx = qy(i, t, v, b)
                            qty += int(bitstring[n - 1 - qidx]) * (2**b)
                        if qty > 0:
                            deliveries[(i, t, v)] = qty

            for v in range(K):
                slack_values[v] = 0
                for b in range(slack_bits[v]):
                    idx = sq(v, b)
                    slack_values[v] += int(bitstring[n - 1 - idx]) * (2**b)

        else:
            raise ValueError(
                f"Invalid bitstring length {n}; expected {no_delivery_len} or {delivery_len} for route-only or delivery encoding"
            )

    # Validate constraints
    violations = []
    depot_set = set(starting_nodes)

    # Depot at position 0 and return at position P-1
    for v in range(K):
        depot = starting_nodes[v]
        if x[depot, 0, v] != 1:
            violations.append(f"Vehicle {v}: depot {depot} not at position 0")
        if x[depot, P - 1, v] != 1:
            violations.append(f"Vehicle {v}: depot {depot} not at position {P - 1}")

    # Every non-depot node visited at least once
    for i in range(N):
        if i not in depot_set:
            total_visits = sum(x[i, t, v] for t in range(P) for v in range(K))
            if total_visits == 0:
                violations.append(f"Node {i} not visited")

    # Each position slot has at most one node
    for t in range(P):
        for v in range(K):
            slot_sum = sum(x[i, t, v] for i in range(N))
            if slot_sum > 1:
                violations.append(f"Position conflict: slot (t={t}, v={v}) has {slot_sum} nodes")

    if demands is not None and capacities is not None:
        depot_set = set(starting_nodes)
        for (i, t, v), qty in deliveries.items():
            if x[i, t, v] != 1:
                violations.append(
                    f"Delivery quantity assigned to node {i} at slot (t={t},v={v}) without a visit"
                )

        for i in range(N):
            if i in depot_set:
                continue
            total_delivered = sum(
                qty for ((j, t, v), qty) in deliveries.items() if j == i
            )
            if abs(total_delivered - float(demands[i])) > 1e-9:
                violations.append(
                    f"Node {i} delivered {total_delivered} != demand {demands[i]}"
                )

        for v in range(K):
            total_delivered = sum(
                qty for ((i, t, vv), qty) in deliveries.items() if vv == v
            )
            slack = slack_values.get(v, 0)
            cap = float(capacities[v])
            if total_delivered + slack != cap:
                violations.append(
                    f"Vehicle {v} load {total_delivered} + slack {slack} != cap {cap}"
                )
            if total_delivered > cap + 1e-9:
                violations.append(
                    f"Vehicle {v} overload: delivered {total_delivered} > cap {cap}"
                )

    return {
        "routes":     routes,
        "assignment": {i: vlist for i, vlist in assignment.items()},
        "deliveries": deliveries,
        "slack":       slack_values,
        "valid":      len(violations) == 0,
        "violations": violations,
    }


def compute_objective(
    routes:  dict,
    matrix:  np.ndarray,
) -> float:
    """
    Compute total travel cost from decoded routes.

    Parameters
    ----------
    routes : {"0": [node_list], "1": [node_list], ...}
    matrix : N×N distance matrix
    """
    total = 0.0
    for v_nodes in routes.values():
        for i in range(len(v_nodes) - 1):
            a, b = v_nodes[i], v_nodes[i + 1]
            total += float(matrix[a][b])
    return round(total, 6)
