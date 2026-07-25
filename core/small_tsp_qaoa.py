"""A bounded, auditable QAOA implementation for a tiny depot TSP.

The solver enumerates the feasible permutations for up to three customer stops
and encodes their *actual route costs* in a diagonal cost Hamiltonian.  This is
deliberately a small-instance demonstration: it makes the mapping, the sampled
bitstrings, and the exact classical optimum independently verifiable before a
hardware experiment is attempted.
"""

from __future__ import annotations

from itertools import permutations
import math
from typing import Sequence

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import DiagonalGate


def feasible_tours(num_nodes: int) -> list[tuple[int, ...]]:
    """Return every depot-start/depot-end tour for a small TSP instance."""
    if num_nodes < 2:
        raise ValueError("at least a depot and one stop are required")
    return [(0, *order, 0) for order in permutations(range(1, num_nodes))]


def required_qubits(num_nodes: int) -> int:
    """Number of bits needed to index every feasible depot tour."""
    return max(1, math.ceil(math.log2(math.factorial(num_nodes - 1))))


def route_cost(tour: Sequence[int], distance_matrix: np.ndarray) -> float:
    return float(sum(distance_matrix[tour[i]][tour[i + 1]] for i in range(len(tour) - 1)))


def cost_spectrum(distance_matrix: np.ndarray) -> tuple[list[tuple[int, ...]], np.ndarray]:
    """Build the diagonal cost spectrum indexed by computational-basis state.

    Valid basis states index one feasible permutation. Unused bit patterns are
    assigned an energy strictly above every valid route, so QAOA has no
    incentive to sample them.
    """
    matrix = np.asarray(distance_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("distance_matrix must be square")

    tours = feasible_tours(len(matrix))
    route_costs = np.asarray([route_cost(tour, matrix) for tour in tours], dtype=float)
    span = max(1.0, float(route_costs.max() - route_costs.min()))
    invalid_penalty = float(route_costs.max() + 4.0 * span)
    spectrum = np.full(2 ** required_qubits(len(matrix)), invalid_penalty, dtype=float)
    spectrum[:len(tours)] = route_costs
    return tours, spectrum


def build_qaoa_circuit(costs: np.ndarray, gamma: float, beta: float) -> QuantumCircuit:
    """Build a single-layer QAOA circuit U(B, beta) U(C, gamma).

    ``DiagonalGate(exp(-i gamma C))`` is the exact phase separator for the
    supplied diagonal cost Hamiltonian, rather than a distance-independent
    placeholder circuit.
    """
    qubits = int(math.log2(len(costs)))
    if 2**qubits != len(costs):
        raise ValueError("cost spectrum length must be a power of two")

    circuit = QuantumCircuit(qubits)
    circuit.h(range(qubits))
    circuit.append(DiagonalGate(np.exp(-1j * float(gamma) * costs)), range(qubits))
    circuit.rx(2.0 * float(beta), range(qubits))
    circuit.measure_all()
    return circuit


def expectation_from_counts(counts: dict[str, int], costs: np.ndarray) -> float:
    """Compute the sampled expectation of the encoded cost Hamiltonian."""
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("sampler returned no shots")
    return float(
        sum(costs[int(bitstring.replace(" ", ""), 2)] * count for bitstring, count in counts.items())
        / total
    )


def best_feasible_sample(
    counts: dict[str, int], tours: Sequence[tuple[int, ...]], costs: np.ndarray
) -> tuple[list[int], float, float]:
    """Return the lowest-cost feasible tour sampled and its observed rate."""
    total = sum(counts.values())
    candidates = [
        (costs[index], -count, index, count)
        for bitstring, count in counts.items()
        for index in [int(bitstring.replace(" ", ""), 2)]
        if index < len(tours)
    ]
    if not candidates:
        raise ValueError("QAOA sampled no feasible route encoding")
    cost, _, index, count = min(candidates)
    return list(tours[index]), float(cost), float(count / total)
