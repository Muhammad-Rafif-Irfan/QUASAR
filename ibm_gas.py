"""Grover Adaptive Search (GAS) runner for QUASAR's diagonal SDVRP Hamiltonian.

Unlike the previous implementation, this module uses a binary energy-threshold
oracle.  It marks ``H(x) < threshold`` with a phase flip, uncomputes all
arithmetic ancillas, and only accepts feasible decoded routes as incumbents.
"""

from __future__ import annotations

from math import ceil, sqrt

import numpy as np
from qiskit import QuantumCircuit

from gas_oracle import (
    ThresholdOracle,
    ThresholdOracleError,
    build_threshold_oracle,
    evaluate_ising_energy,
    suggest_energy_scale,
)
from hamiltonian import build_ising, compute_objective, decode_bitstring
from ibm_connection import get_backend, get_pass_manager, get_sampler, parse_payload


def _decode_result(bitstring: str, payload: dict, matrix: np.ndarray) -> dict:
    decoded = decode_bitstring(
        bitstring,
        payload["n_nodes"],
        payload["n_vehicles"],
        payload["starting_nodes"],
        np.array(payload["demands"], dtype=float),
        np.array(payload["capacities"], dtype=float),
    )
    return {
        "routes": decoded["routes"],
        "valid": decoded["valid"],
        "violations": decoded["violations"],
        "route_cost": compute_objective(decoded["routes"], matrix) if decoded["valid"] else None,
    }


def _diffuser(n_problem_qubits: int) -> QuantumCircuit:
    """Return Grover's inversion-about-the-mean on problem qubits only."""
    circuit = QuantumCircuit(n_problem_qubits, name="diffuser")
    if n_problem_qubits == 1:
        circuit.x(0)
        return circuit

    circuit.h(range(n_problem_qubits))
    circuit.x(range(n_problem_qubits))
    circuit.h(n_problem_qubits - 1)
    circuit.mcx(list(range(n_problem_qubits - 1)), n_problem_qubits - 1)
    circuit.h(n_problem_qubits - 1)
    circuit.x(range(n_problem_qubits))
    circuit.h(range(n_problem_qubits))
    return circuit


def _build_grover_circuit(oracle: ThresholdOracle, grover_steps: int) -> QuantumCircuit:
    """Prepare a uniform problem state and apply the threshold oracle/diffuser."""
    if grover_steps < 0:
        raise ValueError("grover_steps must not be negative.")

    n_problem = oracle.resources.problem_qubits
    total_qubits = oracle.resources.total_qubits
    circuit = QuantumCircuit(total_qubits, n_problem)
    circuit.h(range(n_problem))
    diffuser = _diffuser(n_problem)

    for _ in range(grover_steps):
        circuit.compose(oracle.circuit, qubits=range(total_qubits), inplace=True)
        circuit.compose(diffuser, qubits=range(n_problem), inplace=True)

    # Ancillas are deliberately not measured.  They must be back at |0> after
    # the oracle so the sampler bitstrings remain compatible with the decoder.
    circuit.measure(range(n_problem), range(n_problem))
    return circuit


def _counts_from_result(result) -> dict[str, int]:
    """Read a SamplerV2 result without assuming a particular classical register name."""
    data = result[0].data
    for attribute in dir(data):
        register = getattr(data, attribute, None)
        if register is not None and hasattr(register, "get_counts"):
            return register.get_counts()
    raise RuntimeError("Sampler result contains no classical counts register.")


def _best_feasible_measurement(
    counts: dict[str, int],
    payload: dict,
    ising_operator: object,
) -> tuple[str | None, float, float]:
    """Return the feasible sampled state with the lowest Hamiltonian energy."""
    total_shots = sum(counts.values())
    best_bitstring: str | None = None
    best_energy = float("inf")
    best_probability = 0.0

    for bitstring, count in counts.items():
        try:
            decoded = decode_bitstring(
                bitstring,
                payload["n_nodes"],
                payload["n_vehicles"],
                payload["starting_nodes"],
                np.array(payload["demands"], dtype=float),
                np.array(payload["capacities"], dtype=float),
            )
        except ValueError:
            continue

        if not decoded["valid"]:
            continue
        energy = evaluate_ising_energy(ising_operator, bitstring)
        if energy < best_energy:
            best_bitstring = bitstring
            best_energy = energy
            best_probability = count / total_shots

    return best_bitstring, best_energy, best_probability


def _initial_threshold(
    ising_operator: object,
    n_problem_qubits: int,
    energy_scale: int,
    random: np.random.Generator,
) -> float:
    """Choose a sampled, integer-grid threshold that marks some but not all samples.

    This samples bitstrings directly.  It never constructs an array of all
    ``2**n`` states, which is essential once the routing encoding grows.
    """
    sample_size = min(500, 1 << min(n_problem_qubits, 20))
    if n_problem_qubits <= 20:
        selected = random.choice(1 << n_problem_qubits, size=sample_size, replace=False)
        bitstrings = [format(int(index), f"0{n_problem_qubits}b") for index in selected]
    else:
        bits = random.integers(0, 2, size=(sample_size, n_problem_qubits), dtype=np.int8)
        bitstrings = ["".join(str(int(bit)) for bit in row) for row in bits]

    sampled_integer_energies = sorted({
        int(round(evaluate_ising_energy(ising_operator, bitstring) * energy_scale))
        for bitstring in bitstrings
    })
    if len(sampled_integer_energies) < 2:
        raise RuntimeError(
            "Unable to derive a discriminating initial GAS threshold from the sampled energies."
        )

    cutoff = max(1, min(len(sampled_integer_energies) - 1, ceil(0.30 * len(sampled_integer_energies))))
    return sampled_integer_energies[cutoff] / energy_scale


def run_gas_ibm(payload: dict) -> dict:
    """Run adaptive GAS against IBM Runtime using a true energy-threshold oracle.

    The threshold predicate is defined over the complete penalized SDVRP
    Hamiltonian.  Measured candidates are independently decoded and validated
    before they are allowed to replace the incumbent solution.
    """
    params = parse_payload(payload)
    shots = params["shots"]
    iterations = params["iterations"]
    if shots < 1:
        raise ValueError("shots must be at least 1.")
    if iterations < 1:
        raise ValueError("iterations must be at least 1.")

    matrix_original = params["matrix"].copy()
    ising = build_ising(
        params["matrix"],
        params["demands"],
        params["capacities"],
        params["n_nodes"],
        params["n_vehicles"],
        params["starting_nodes"],
        params["alpha"],
        params["beta"],
        params["lambda_scale"],
        params["demand_priority"],
    )
    # The comparator works in the original Hamiltonian units.  Normalising
    # first can introduce long rational coefficients that require a huge
    # fixed-point scale and silently change the threshold predicate.
    n_problem_qubits = ising.num_qubits
    energy_scale = suggest_energy_scale(
        ising, maximum_scale=payload.get("max_energy_scale", 1000)
    )

    # A deterministic classical sample gives an initial discriminating
    # threshold without enumerating the exponential search space.
    random = np.random.default_rng(42)
    threshold = _initial_threshold(ising, n_problem_qubits, energy_scale, random)

    try:
        initial_oracle = build_threshold_oracle(
            ising, threshold, energy_scale=energy_scale
        )
    except ThresholdOracleError as error:
        raise RuntimeError(f"Unable to construct an initial GAS threshold oracle: {error}") from error

    backend = get_backend(
        params["token"], params["backend_name"], initial_oracle.resources.total_qubits
    )
    if backend.num_qubits < initial_oracle.resources.total_qubits:
        raise RuntimeError("Selected backend cannot accommodate GAS work qubits.")

    pass_manager = get_pass_manager(backend, params["optimization_level"])
    sampler = get_sampler(backend, params["use_dd"])

    incumbent_bitstring: str | None = None
    incumbent_energy = float("inf")
    incumbent_probability = 0.0
    job_ids: list[str] = []
    energy_history: list[float] = []
    grover_history: list[int] = []
    transpiled_depths: list[int] = []
    resource_summary = initial_oracle.resources

    # Dürr-Høyer-style adaptive range.  A random Grover count avoids the
    # fixed sqrt(2**n)/(iteration+1) schedule that can repeatedly overshoot.
    growth_factor = 6.0 / 5.0
    grover_range = 1.0
    maximum_range = sqrt(2**n_problem_qubits)

    print(
        f"[GAS] {iterations} adaptive iterations | {n_problem_qubits} problem qubits | "
        f"{resource_summary.total_qubits} total circuit qubits | backend: {backend.name}"
    )

    for iteration in range(iterations):
        try:
            oracle = build_threshold_oracle(ising, threshold, energy_scale=energy_scale)
        except ThresholdOracleError:
            # No strictly better state is representable under this threshold.
            break

        grover_steps = int(random.integers(0, max(1, ceil(grover_range))))
        grover_history.append(grover_steps)
        circuit = _build_grover_circuit(oracle, grover_steps)
        isa_circuit = pass_manager.run(circuit)

        if isa_circuit.num_qubits > backend.num_qubits:
            raise RuntimeError(
                f"Transpiled GAS circuit needs {isa_circuit.num_qubits} qubits, "
                f"but backend {backend.name} has {backend.num_qubits}."
            )
        circuit_depth = isa_circuit.depth()
        if circuit_depth > params["max_circuit_depth"]:
            raise RuntimeError(
                f"Transpiled GAS circuit depth is {circuit_depth}, exceeding the configured "
                f"limit of {params['max_circuit_depth']}. Refuse to submit this IBM job."
            )
        transpiled_depths.append(circuit_depth)

        job = sampler.run([(isa_circuit,)], shots=shots)
        job_ids.append(job.job_id())
        counts = _counts_from_result(job.result())

        candidate_bitstring, candidate_energy, candidate_probability = _best_feasible_measurement(
            counts, params, ising
        )
        if candidate_bitstring is not None:
            energy_history.append(candidate_energy)

        if candidate_bitstring is not None and candidate_energy < incumbent_energy:
            incumbent_bitstring = candidate_bitstring
            incumbent_energy = candidate_energy
            incumbent_probability = candidate_probability
            threshold = candidate_energy
            grover_range = 1.0
            print(
                f"  Iteration {iteration + 1}: improved feasible energy "
                f"to {incumbent_energy:.6f}"
            )
        else:
            grover_range = min(growth_factor * grover_range, maximum_range)

    if incumbent_bitstring is None:
        raise RuntimeError(
            "GAS completed without measuring a feasible SDVRP state. "
            "Increase shots/iterations or adjust the penalty Hamiltonian."
        )

    return {
        "bitstring": incumbent_bitstring,
        "n_qubits": n_problem_qubits,
        "n_nodes": params["n_nodes"],
        "n_vehicles": params["n_vehicles"],
        "energy": round(incumbent_energy, 6),
        "threshold": round(threshold, 6),
        "n_evals": len(job_ids),
        "cost_history": [round(value, 6) for value in energy_history],
        "backend": backend.name,
        "shots": shots,
        "algorithm": "GAS",
        "job_ids": job_ids,
        "success_prob": round(incumbent_probability, 4),
        "grover_steps": grover_history,
        "max_transpiled_depth": max(transpiled_depths, default=0),
        "energy_scale": energy_scale,
        "oracle_resources": {
            "problem_qubits": resource_summary.problem_qubits,
            "term_ancillas": resource_summary.term_ancillas,
            "accumulator_qubits": resource_summary.accumulator_qubits,
            "arithmetic_ancillas": resource_summary.arithmetic_ancillas,
            "comparator_ancillas": resource_summary.comparator_ancillas,
            "total_qubits": resource_summary.total_qubits,
        },
        **_decode_result(incumbent_bitstring, params, matrix_original),
    }
