"""
ibm_connection.py — QUASAR IBM Quantum Connection Utilities
============================================================
Shared by all IBM hardware runner modules.
Handles IBM Quantum authentication, backend selection,
and primitive (Sampler/Estimator) configuration.
"""

import json
import os

import numpy as np
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    SamplerV2,
    EstimatorV2,
)
from qiskit_ibm_runtime.options import SamplerOptions, EstimatorOptions
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


def parse_payload(payload: dict) -> dict:
    """
    Parse and validate the universal input payload.
    Extracts both problem parameters and IBM-specific settings.
    """
    def _load(v):
        return json.loads(v) if isinstance(v, str) else v

    matrix         = np.array(_load(payload["matrix"]),     dtype=float)
    demands        = np.array(_load(payload["demands"]),    dtype=float)
    capacities     = np.array(_load(payload["capacities"]), dtype=float)
    starting_nodes = list(_load(payload["starting_nodes"]))
    n_nodes        = matrix.shape[0]
    n_vehicles     = len(capacities)

    if matrix.ndim != 2 or matrix.shape != (n_nodes, n_nodes):
        raise ValueError("matrix must be a non-empty square N×N array")
    if len(demands) != n_nodes:
        raise ValueError("demands length must equal N")
    if n_vehicles == 0:
        raise ValueError("at least one vehicle capacity is required")
    if len(starting_nodes) != n_vehicles:
        raise ValueError("starting_nodes length must equal the vehicle count")
    if not np.all(np.isfinite(matrix)) or np.any(matrix < 0):
        raise ValueError("matrix entries must be finite and non-negative")
    if not np.all(np.isfinite(demands)) or np.any(demands < 0):
        raise ValueError("demands must be finite and non-negative")
    if not np.all(np.isfinite(capacities)) or np.any(capacities <= 0):
        raise ValueError("capacities must be finite and positive")
    if any(node < 0 or node >= n_nodes for node in starting_nodes):
        raise ValueError("starting_nodes entries must be valid node indices")

    layers = int(payload.get("p", 2))
    maxiter = int(payload.get("maxiter", 3))
    shots = int(payload.get("shots", 4096))
    falqon_layers = int(payload.get("n_layers", 3))
    dt = float(payload.get("dt", 0.1))
    iterations = int(payload.get("iterations", 3))
    optimization_level = int(payload.get("optimization_level", 3))
    resilience_level = int(payload.get("resilience_level", 1))

    if min(layers, maxiter, shots, falqon_layers, iterations) <= 0:
        raise ValueError("algorithm iteration, layer, and shot counts must be positive")
    if dt <= 0:
        raise ValueError("dt must be positive")
    if optimization_level not in range(4):
        raise ValueError("optimization_level must be between 0 and 3")
    if resilience_level not in range(3):
        raise ValueError("resilience_level must be between 0 and 2")

    return {
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
        "demand_priority": bool( payload.get("demand_priority", False)),
        # Algorithm parameters
        "p":               layers,
        "maxiter":         maxiter,
        "shots":           shots,
        "n_layers":        falqon_layers,
        "dt":              dt,
        "iterations":      iterations,
        # IBM settings
        "token":               payload.get("token",               os.getenv("IBM_QUANTUM_TOKEN", "")),
        "backend_name":        payload.get("backend_name",        None),
        "optimization_level":  optimization_level,
        "resilience_level":    resilience_level,
        "use_dd":              bool( payload.get("use_dd",              True)),
    }


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
    if not token:
        raise ValueError(
            "IBM Quantum token required. Set IBM_QUANTUM_TOKEN or pass token explicitly."
        )

    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)

    if backend_name:
        backend = service.backend(backend_name)
        if backend.num_qubits < n_qubits:
            raise ValueError(
                f"backend {backend.name} has {backend.num_qubits} qubits; "
                f"{n_qubits} are required"
            )
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
    if not counts:
        raise ValueError("sampler returned no measurement counts")
    best = max(counts, key=counts.get)
    total = sum(counts.values())
    prob = counts[best] / total if total else 0.0
    return best, prob