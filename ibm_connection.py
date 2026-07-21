"""
ibm_connection.py — QUASAR IBM Quantum Connection Utilities
============================================================
Shared by all IBM hardware runner modules.
Handles IBM Quantum authentication, backend selection,
and primitive (Sampler/Estimator) configuration.
"""

import os
import json
import numpy as np
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    SamplerV2,
    EstimatorV2,
)
from qiskit_ibm_runtime.options import SamplerOptions, EstimatorOptions
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

def parse_payload(payload: dict) -> dict:
    def _load(value, field):
            if not isinstance(value, str):
                return value
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"'{field}' must be valid JSON when supplied as a string.") from exc

    def _boolean(value, field):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"'{field}' must be a boolean.")

    required = ("matrix", "demands", "capacities", "starting_nodes")
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"Missing required payload field(s): {', '.join(missing)}.")
    matrix = np.asarray(_load(payload["matrix"], "matrix"), dtype=float)
    demands = np.asarray(_load(payload["demands"], "demands"), dtype=float)
    capacities = np.asarray(_load(payload["capacities"], "capacities"), dtype=float)
    starting_nodes = list(_load(payload["starting_nodes"], "starting_nodes"))
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] < 2:
        raise ValueError("'matrix' must be a finite square distance matrix with at least two nodes.")
    n_nodes = matrix.shape[0]
    n_vehicles = len(capacities)
    if demands.ndim != 1 or len(demands) != n_nodes:
        raise ValueError("'demands' must be a vector with one value per node.")
    if capacities.ndim != 1 or n_vehicles == 0:
        raise ValueError("'capacities' must contain at least one vehicle capacity.")
    if len(starting_nodes) != n_vehicles:
        raise ValueError("'starting_nodes' must contain one depot/start node per vehicle.")
    if not (np.isfinite(matrix).all() and np.isfinite(demands).all() and np.isfinite(capacities).all()):
        raise ValueError("matrix, demands, and capacities must contain only finite numbers.")
    if np.any(demands < 0) or np.any(capacities <= 0):
        raise ValueError("demands must be non-negative and capacities must be positive.")
    if any(not isinstance(node, (int, np.integer)) or node < 0 or node >= n_nodes for node in starting_nodes):
        raise ValueError("each starting node must be an integer index in the distance matrix.")
    parsed = {
        # Problem parameters
        "matrix":          matrix,
        "demands":         demands,
        "capacities":      capacities,
        "starting_nodes":  starting_nodes,
        "n_nodes":         n_nodes,
        "n_vehicles":      n_vehicles,
        "alpha":           float(payload.get("alpha",           1.0)),
        "beta":            float(payload.get("beta",            0.5)),
        "lambda_scale":    float(payload.get("lambda_scale",    10.0)),
        "demand_priority": _boolean(payload.get("demand_priority", False), "demand_priority"),
        # Algorithm parameters
        "p":               int(  payload.get("p",               2)),
        "maxiter":         int(  payload.get("maxiter",         3)),
        "shots":           int(  payload.get("shots",           4096)),
        "n_layers":        int(  payload.get("n_layers",        3)),
        "dt":              float(payload.get("dt",              0.1)),
        "iterations":      int(  payload.get("iterations",      3)),
        "max_circuit_depth": int(payload.get("max_circuit_depth", 100000)), # Added per review
        "max_energy_scale":  int(payload.get("max_energy_scale", 1000)),    # Added per review
        # IBM settings
        "token":               payload.get("token",               os.getenv("IBM_QUANTUM_TOKEN", "")),
        "backend_name":        payload.get("backend_name",        None),
        "optimization_level":  int(  payload.get("optimization_level",  3)),
        "resilience_level":    int(  payload.get("resilience_level",    1)),
        "use_dd":              _boolean(payload.get("use_dd", True), "use_dd"),
    }
    if parsed["p"] < 1 or parsed["maxiter"] < 1 or parsed["shots"] < 1:
        raise ValueError("p, maxiter, and shots must be positive integers.")
    if parsed["n_layers"] < 1 or parsed["iterations"] < 1:
        raise ValueError("n_layers and iterations must be positive integers.")
    if parsed["max_circuit_depth"] < 1 or parsed["max_energy_scale"] < 1:
        raise ValueError("max_circuit_depth and max_energy_scale must be positive integers.")
    return parsed


def get_backend(token: str, backend_name: str | None, n_qubits: int):
    """
    Connect to IBM Quantum and return the target backend.

    Parameters
    ----------
    token        : IBM Quantum API token
    backend_name : specific backend name, or None for least busy
    n_qubits     : minimum number of qubits required

    Returns
    -------
    IBMBackend instance
    """
    assert token, "IBM Quantum token required. Set IBM_QUANTUM_TOKEN env var or pass 'token' in payload."

    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)

    if backend_name:
        backend = service.backend(backend_name)
        print(f"[IBM] Using specified backend: {backend.name} ({backend.num_qubits} qubits)")
    else:
        backend = service.least_busy(
            simulator=False,
            operational=True,
            min_num_qubits=n_qubits,
        )
        print(f"[IBM] Selected least busy backend: {backend.name} ({backend.num_qubits} qubits)")

    return backend


def get_pass_manager(backend, optimization_level: int = 3):
    """Return a preset pass manager for the given backend."""
    return generate_preset_pass_manager(
        optimization_level=optimization_level,
        backend=backend,
    )


def get_sampler(backend, use_dd: bool = True) -> SamplerV2:
    """Configure and return SamplerV2 with error mitigation."""
    opts = SamplerOptions()
    if use_dd:
        opts.dynamical_decoupling.enable        = True
        opts.dynamical_decoupling.sequence_type = "XX"
    return SamplerV2(mode=backend, options=opts)


def get_estimator(backend, resilience_level: int = 1, use_dd: bool = True) -> EstimatorV2:
    """Configure and return EstimatorV2 with error mitigation."""
    opts = EstimatorOptions()
    opts.resilience_level = resilience_level
    if use_dd:
        opts.dynamical_decoupling.enable        = True
        opts.dynamical_decoupling.sequence_type = "XX"
    return EstimatorV2(mode=backend, options=opts)


def best_bitstring(counts: dict, shots: int) -> tuple[str, float]:
    """Return most frequent bitstring and its success probability."""
    best = max(counts, key=counts.get)
    prob = counts[best] / shots
    return best, prob