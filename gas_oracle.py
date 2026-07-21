"""Reversible energy-threshold oracle used by Grover Adaptive Search (GAS).

The oracle implements the binary predicate ``H(x) < threshold``.  This is
different from a QAOA cost unitary: a marked computational-basis state gets a
phase of -1 and every other state is unchanged.  The energy is evaluated with
a fixed-point QUBO accumulator, compared to the threshold, phase-kicked, and
then uncomputed so that all work qubits return to |0>.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from qiskit import QuantumCircuit
from qiskit.circuit.library import IntegerComparator, WeightedAdder


class ThresholdOracleError(ValueError):
    """Raised when a threshold cannot produce a meaningful GAS oracle."""


@dataclass(frozen=True)
class OracleResources:
    problem_qubits: int
    term_ancillas: int
    accumulator_qubits: int
    arithmetic_ancillas: int
    comparator_ancillas: int

    @property
    def total_qubits(self) -> int:
        return (
            self.problem_qubits
            + self.term_ancillas
            + self.accumulator_qubits
            + self.arithmetic_ancillas
            + 1  # comparator flag
            + self.comparator_ancillas
        )


@dataclass(frozen=True)
class ThresholdOracle:
    circuit: QuantumCircuit
    resources: OracleResources
    threshold_integer: int
    constant_integer: int
    maximum_integer_energy: int


@dataclass(frozen=True)
class _PositiveTerm:
    qubits: tuple[int, ...]
    active_values: tuple[int, ...]
    weight: int


def _ising_terms(ising_op: object) -> tuple[float, dict[int, float], dict[tuple[int, int], float]]:
    """Convert a diagonal Ising operator into ``constant + linear + quadratic`` QUBO terms.

    Qiskit's Pauli strings are big-endian, while circuit qubits are indexed
    little-endian.  The mapping mirrors ``hamiltonian.eval_bitstring``.
    """
    constant = 0.0
    linear: dict[int, float] = defaultdict(float)
    quadratic: dict[tuple[int, int], float] = defaultdict(float)

    for op in ising_op:
        pauli = str(op.paulis[0])
        coeff = float(op.coeffs[0].real)
        n_qubits = len(pauli)
        z_qubits = [n_qubits - 1 - index for index, value in enumerate(pauli) if value == "Z"]

        if len(z_qubits) == 0:
            constant += coeff
        elif len(z_qubits) == 1:
            qubit = z_qubits[0]
            constant += coeff
            linear[qubit] -= 2.0 * coeff
        elif len(z_qubits) == 2:
            first, second = sorted(z_qubits)
            constant += coeff
            linear[first] -= 2.0 * coeff
            linear[second] -= 2.0 * coeff
            quadratic[(first, second)] += 4.0 * coeff
        else:
            raise ThresholdOracleError(
                "GAS requires a diagonal Hamiltonian with at most Z and ZZ terms."
            )

    return constant, dict(linear), dict(quadratic)


def evaluate_ising_energy(ising_op: object, bitstring: str) -> float:
    """Evaluate the full Ising energy, including the identity offset."""
    n_qubits = getattr(ising_op, "num_qubits")
    if len(bitstring) != n_qubits:
        raise ValueError(f"Expected a {n_qubits}-bit string, got {len(bitstring)} bits.")

    energy = 0.0
    for op in ising_op:
        pauli = str(op.paulis[0])
        coeff = float(op.coeffs[0].real)
        eigenvalue = 1.0
        for index, value in enumerate(pauli):
            if value == "Z":
                qubit = n_qubits - 1 - index
                eigenvalue *= 1.0 - 2.0 * int(bitstring[n_qubits - 1 - qubit])
            elif value != "I":
                raise ThresholdOracleError("GAS threshold oracle only supports diagonal Pauli terms.")
        energy += coeff * eigenvalue
    return energy


def suggest_energy_scale(ising_op: object, *, maximum_scale: int = 1_000) -> int:
    """Return the smallest practical fixed-point scale for an Ising operator.

    Integer-valued routing costs should stay at scale 1; coefficients such as
    0.5 select scale 2.  A caller can reject a problem when its coefficients
    cannot be represented within the configured precision budget instead of
    silently constructing an enormous accumulator register.
    """
    if maximum_scale < 1:
        raise ValueError("maximum_scale must be at least 1.")

    candidate_scales = [1, 2, 5]
    factor = 10
    while factor <= maximum_scale:
        candidate_scales.extend([factor, factor * 2, factor * 5])
        factor *= 10

    coefficients = [float(op.coeffs[0].real) for op in ising_op]
    for scale in sorted({value for value in candidate_scales if value <= maximum_scale}):
        if all(abs(coefficient * scale - round(coefficient * scale)) <= 1e-9 for coefficient in coefficients):
            return scale

    raise ThresholdOracleError(
        f"Hamiltonian coefficients cannot be represented exactly with a fixed-point scale <= {maximum_scale}."
    )


def _positive_terms(
    constant: float,
    linear: dict[int, float],
    quadratic: dict[tuple[int, int], float],
    energy_scale: int,
) -> tuple[int, list[_PositiveTerm]]:
    """Rewrite signed QUBO terms as a constant plus positive weighted predicates."""
    constant_integer = int(round(constant * energy_scale))
    terms: list[_PositiveTerm] = []

    def add_term(qubits: tuple[int, ...], coefficient: float) -> None:
        nonlocal constant_integer
        integer_coefficient = int(round(coefficient * energy_scale))
        if integer_coefficient == 0:
            return
        if integer_coefficient > 0:
            terms.append(_PositiveTerm(qubits, (1,) * len(qubits), integer_coefficient))
        else:
            # Rewrite negative terms using disjoint positive predicates.  For
            # a linear term c*x, c < 0: c*x = c + (-c)*(not x).  For a
            # quadratic term c*x*y: c*x*y = c + (-c)*(not x) +
            # (-c)*(x and not y).  The latter is deliberately *not* encoded
            # as ``not x and y``: that would mark the wrong truth-table rows.
            constant_integer += integer_coefficient
            if len(qubits) == 1:
                terms.append(_PositiveTerm(qubits, (0,), -integer_coefficient))
            elif len(qubits) == 2:
                first, second = qubits
                terms.append(_PositiveTerm((first,), (0,), -integer_coefficient))
                terms.append(_PositiveTerm((first, second), (1, 0), -integer_coefficient))
            else:
                raise ThresholdOracleError("Only linear and quadratic QUBO terms are supported.")

    for qubit, coefficient in linear.items():
        add_term((qubit,), coefficient)
    for qubits, coefficient in quadratic.items():
        add_term(qubits, coefficient)

    return constant_integer, terms


def _compute_term(qc: QuantumCircuit, term: _PositiveTerm, target: int) -> None:
    """Compute one positive predicate into ``target``; the operation is self-inverse."""
    zero_controls = [q for q, value in zip(term.qubits, term.active_values) if value == 0]
    for qubit in zero_controls:
        qc.x(qubit)

    if len(term.qubits) == 1:
        qc.cx(term.qubits[0], target)
    elif len(term.qubits) == 2:
        qc.ccx(term.qubits[0], term.qubits[1], target)
    else:
        raise ThresholdOracleError("Only linear and quadratic QUBO terms are supported.")

    for qubit in reversed(zero_controls):
        qc.x(qubit)


def build_threshold_oracle(
    ising_op: object,
    threshold: float,
    *,
    energy_scale: int = 1_000,
) -> ThresholdOracle:
    """Build ``U_T`` that phase-flips exactly the states with ``H(x) < threshold``.

    The circuit is parameterized by the problem Hamiltonian and therefore does
    not enumerate computational-basis states.  It supports arbitrary problem
    sizes in code; the caller must still check ``resources.total_qubits`` and
    transpiled depth against the selected IBM backend before submission.
    """
    if energy_scale <= 0:
        raise ValueError("energy_scale must be positive.")

    problem_qubits = int(getattr(ising_op, "num_qubits"))
    if problem_qubits < 1:
        raise ThresholdOracleError("GAS requires at least one problem qubit.")

    constant, linear, quadratic = _ising_terms(ising_op)
    constant_integer, terms = _positive_terms(constant, linear, quadratic, energy_scale)
    threshold_integer = int(round(threshold * energy_scale))
    comparator_value = threshold_integer - constant_integer
    max_sum = sum(term.weight for term in terms)

    if comparator_value <= 0:
        raise ThresholdOracleError("Threshold marks no states after fixed-point quantization.")
    if comparator_value > max_sum:
        raise ThresholdOracleError("Threshold marks every state; GAS has no discrimination predicate.")

    weights = [term.weight for term in terms]
    if not weights:
        raise ThresholdOracleError("Hamiltonian has no non-constant terms to optimize.")

    adder = WeightedAdder(len(weights), weights)
    comparator = IntegerComparator(adder.num_sum_qubits, comparator_value, geq=False)
    resources = OracleResources(
        problem_qubits=problem_qubits,
        term_ancillas=len(terms),
        accumulator_qubits=adder.num_sum_qubits,
        arithmetic_ancillas=adder.num_ancillas,
        comparator_ancillas=comparator.num_ancillas,
    )

    qc = QuantumCircuit(resources.total_qubits, name="threshold_oracle")
    term_qubits = list(range(problem_qubits, problem_qubits + len(terms)))
    sum_start = term_qubits[-1] + 1
    sum_qubits = list(range(sum_start, sum_start + adder.num_sum_qubits))
    adder_ancillas = list(range(sum_qubits[-1] + 1, sum_qubits[-1] + 1 + adder.num_ancillas))
    flag = sum_qubits[-1] + 1 + adder.num_ancillas
    comparator_ancillas = list(range(flag + 1, flag + 1 + comparator.num_ancillas))

    for term, target in zip(terms, term_qubits):
        _compute_term(qc, term, target)

    qc.append(adder.to_gate(), term_qubits + sum_qubits + adder_ancillas)
    qc.append(comparator.to_gate(), sum_qubits + [flag] + comparator_ancillas)
    qc.z(flag)
    qc.append(comparator.to_gate().inverse(), sum_qubits + [flag] + comparator_ancillas)
    qc.append(adder.to_gate().inverse(), term_qubits + sum_qubits + adder_ancillas)

    for term, target in reversed(list(zip(terms, term_qubits))):
        _compute_term(qc, term, target)

    return ThresholdOracle(
        circuit=qc,
        resources=resources,
        threshold_integer=threshold_integer,
        constant_integer=constant_integer,
        maximum_integer_energy=constant_integer + max_sum,
    )
