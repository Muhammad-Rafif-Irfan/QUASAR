"""Hamiltonian utilities for QUASAR Bottleneck-Targeted QAOA+ XY.

The quantum register represents a compact candidate-move neighborhood.  Qubit
``j`` corresponds to candidate move ``j``.  The stable MVP uses an exact-one
constraint; pairwise interaction terms are retained for leakage diagnostics and
future fixed-k extensions, but they are inactive on valid exact-one states.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class CandidateHamiltonian:
    """Exact-one candidate-selection Hamiltonian and mapping metadata."""

    operator: Any
    candidate_costs: tuple[float, ...]
    one_hot_penalty: float
    pairwise_interactions: tuple[tuple[float, ...], ...]
    candidate_to_qubit: tuple[tuple[str, int], ...]
    qubit_to_candidate: tuple[str, ...]

    @property
    def n_qubits(self) -> int:
        return len(self.candidate_costs)

    def candidate_index(self, move_id: str) -> int:
        mapping = dict(self.candidate_to_qubit)
        if move_id not in mapping:
            raise KeyError(f"Unknown candidate move ID: {move_id}")
        return mapping[move_id]


class _DiagonalPauliBuilder:
    """Build a diagonal Ising operator using ``x = (I - Z) / 2``."""

    def __init__(self, n_qubits: int) -> None:
        if n_qubits < 1:
            raise ValueError("n_qubits must be positive.")
        self.n_qubits = n_qubits
        self._terms: dict[str, float] = {}

    def _label(self, active_qubits: Iterable[int]) -> str:
        chars = ["I"] * self.n_qubits
        for qubit in active_qubits:
            if qubit < 0 or qubit >= self.n_qubits:
                raise ValueError(f"Qubit index {qubit} is out of range.")
            # Qiskit Pauli labels are big-endian: rightmost character is q0.
            chars[self.n_qubits - 1 - qubit] = "Z"
        return "".join(chars)

    def add_pauli(self, active_qubits: Iterable[int], coefficient: float) -> None:
        value = float(coefficient)
        if not np.isfinite(value):
            raise ValueError("Hamiltonian coefficients must be finite.")
        if abs(value) < 1e-12:
            return
        label = self._label(active_qubits)
        self._terms[label] = self._terms.get(label, 0.0) + value

    def add_constant(self, coefficient: float) -> None:
        self.add_pauli((), coefficient)

    def add_x(self, qubit: int, coefficient: float) -> None:
        """Add ``coefficient * x_qubit``."""
        self.add_constant(coefficient / 2.0)
        self.add_pauli((qubit,), -coefficient / 2.0)

    def add_xx(self, left: int, right: int, coefficient: float) -> None:
        """Add ``coefficient * x_left * x_right``."""
        if left == right:
            self.add_x(left, coefficient)
            return
        self.add_constant(coefficient / 4.0)
        self.add_pauli((left,), -coefficient / 4.0)
        self.add_pauli((right,), -coefficient / 4.0)
        self.add_pauli((left, right), coefficient / 4.0)

    def build(self) -> Any:
        """Return a Qiskit ``SparsePauliOp`` using a lazy import."""
        from qiskit.quantum_info import SparsePauliOp

        terms = [
            (label, value)
            for label, value in self._terms.items()
            if abs(value) >= 1e-12
        ]
        if not terms:
            terms = [("I" * self.n_qubits, 0.0)]
        return SparsePauliOp.from_list(terms).simplify()


def _validated_interactions(
    n_candidates: int,
    pairwise_interactions: Sequence[Sequence[float]] | None,
) -> np.ndarray:
    if pairwise_interactions is None:
        return np.zeros((n_candidates, n_candidates), dtype=float)

    interactions = np.asarray(pairwise_interactions, dtype=float)
    if interactions.shape != (n_candidates, n_candidates):
        raise ValueError(
            "pairwise_interactions must be a square matrix matching candidate_costs."
        )
    if not np.isfinite(interactions).all():
        raise ValueError("pairwise_interactions must be finite.")
    if not np.allclose(interactions, interactions.T, atol=1e-12):
        raise ValueError("pairwise_interactions must be symmetric.")
    if not np.allclose(np.diag(interactions), 0.0, atol=1e-12):
        raise ValueError("pairwise_interactions must have a zero diagonal.")
    return interactions


def build_candidate_hamiltonian(
    candidate_costs: Sequence[float],
    one_hot_penalty: float | None = None,
    pairwise_interactions: Sequence[Sequence[float]] | None = None,
    candidate_ids: Sequence[str] | None = None,
) -> CandidateHamiltonian:
    """Build the exact-one candidate Hamiltonian.

    Formula::

       H = sum_j c_j y_j + sum_{j<k} J_jk y_j y_k
           + A (sum_j y_j - 1)^2.

    ``candidate_costs`` are objective deltas relative to the classical seed.
    Candidate zero must be ``m0_no_change`` with a zero delta.

    Pairwise terms are mathematically inactive on valid exact-one states because
    ``y_j y_k = 0`` for ``j != k``.  They are retained for invalid-sector energy
    diagnostics and future fixed-k work, not advertised as an exact-one benefit.
    """
    costs = tuple(float(value) for value in candidate_costs)
    if not costs:
        raise ValueError("At least one candidate move is required.")
    if not np.isfinite(costs).all():
        raise ValueError("candidate_costs must be finite.")
    if abs(costs[0]) > 1e-9:
        raise ValueError("The no-change candidate at index 0 must have zero cost.")

    identifiers = tuple(
        candidate_ids
        or ["m0_no_change", *[f"m{index}" for index in range(1, len(costs))]]
    )
    if len(identifiers) != len(costs):
        raise ValueError("candidate_ids must match candidate_costs in length.")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("candidate_ids must be unique.")
    if identifiers[0] != "m0_no_change":
        raise ValueError("m0_no_change must map to qubit 0.")

    interactions = _validated_interactions(len(costs), pairwise_interactions)
    coefficient_scale = max(
        1.0,
        max(abs(cost) for cost in costs),
        float(np.max(np.abs(interactions))),
    )
    penalty = (
        float(one_hot_penalty)
        if one_hot_penalty is not None
        else 4.0 * coefficient_scale
    )
    if not np.isfinite(penalty) or penalty <= 0.0:
        raise ValueError("one_hot_penalty must be a finite positive number.")

    builder = _DiagonalPauliBuilder(len(costs))
    # A*(sum y - 1)^2 = A - A*sum y + 2A*sum_{j<k} y_j*y_k.
    builder.add_constant(penalty)
    for index, cost in enumerate(costs):
        builder.add_x(index, cost - penalty)
    for left in range(len(costs)):
        for right in range(left + 1, len(costs)):
            builder.add_xx(left, right, 2.0 * penalty)
            builder.add_xx(left, right, float(interactions[left, right]))

    return CandidateHamiltonian(
        operator=builder.build(),
        candidate_costs=costs,
        one_hot_penalty=penalty,
        pairwise_interactions=tuple(
            tuple(float(value) for value in row) for row in interactions
        ),
        candidate_to_qubit=tuple(
            (candidate_id, index)
            for index, candidate_id in enumerate(identifiers)
        ),
        qubit_to_candidate=identifiers,
    )


def normalize_operator(operator: Any) -> tuple[Any, float]:
    """Normalize Pauli coefficients and return the restoration scale."""
    coefficients = np.asarray(operator.coeffs, dtype=complex)
    scale = float(np.max(np.abs(coefficients))) if len(coefficients) else 1.0
    if not np.isfinite(scale):
        raise ValueError("Operator coefficients must be finite.")
    return (operator / scale, scale) if scale > 0.0 else (operator, 1.0)


def pauli_terms(operator: Any) -> list[tuple[str, float]]:
    """Return real diagonal Pauli terms, rejecting accidental non-Z terms."""
    output: list[tuple[str, float]] = []
    for label, coefficient in operator.to_list():
        if any(symbol not in {"I", "Z"} for symbol in label):
            raise ValueError("Candidate Hamiltonian must contain only I/Z terms.")
        value = complex(coefficient)
        if abs(value.imag) > 1e-10:
            raise ValueError("Candidate Hamiltonian coefficients must be real.")
        output.append((label, float(value.real)))
    return output


def clean_bitstring(bitstring: str) -> str:
    """Remove Qiskit register separators without changing bit order."""
    return bitstring.replace(" ", "").replace("_", "")


def decode_one_hot_bitstring(bitstring: str, n_candidates: int) -> int | None:
    """Return the selected candidate index, or ``None`` for a non-one-hot state."""
    cleaned = clean_bitstring(bitstring)
    if len(cleaned) != n_candidates or set(cleaned) - {"0", "1"}:
        return None
    # Measured Qiskit strings are big-endian; q0 is the rightmost bit.
    selected = [
        index for index, bit in enumerate(reversed(cleaned)) if bit == "1"
    ]
    return selected[0] if len(selected) == 1 else None


def evaluate_bitstring_energy(
    bitstring: str,
    hamiltonian: CandidateHamiltonian,
) -> float:
    """Evaluate the binary Hamiltonian directly using Qiskit bit ordering."""
    cleaned = clean_bitstring(bitstring)
    if len(cleaned) != hamiltonian.n_qubits or set(cleaned) - {"0", "1"}:
        raise ValueError("Bitstring does not match the candidate register.")

    values = [int(bit) for bit in reversed(cleaned)]
    total = sum(
        cost * value
        for cost, value in zip(
            hamiltonian.candidate_costs,
            values,
            strict=True,
        )
    )
    total += hamiltonian.one_hot_penalty * (sum(values) - 1) ** 2
    for left in range(len(values)):
        for right in range(left + 1, len(values)):
            total += (
                hamiltonian.pairwise_interactions[left][right]
                * values[left]
                * values[right]
            )
    return float(total)


def brute_force_exact_one(
    hamiltonian: CandidateHamiltonian,
) -> list[tuple[str, float]]:
    """Enumerate exact-one states for deterministic toy verification."""
    states: list[tuple[str, float]] = []
    for selected in range(hamiltonian.n_qubits):
        little_endian = ["0"] * hamiltonian.n_qubits
        little_endian[selected] = "1"
        bitstring = "".join(reversed(little_endian))
        states.append(
            (bitstring, evaluate_bitstring_energy(bitstring, hamiltonian))
        )
    return sorted(states, key=lambda item: (item[1], item[0]))
