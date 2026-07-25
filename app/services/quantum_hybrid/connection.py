"""Safe IBM Quantum Runtime helpers for QUASAR QAOA+ XY Hybrid.

Credentials are read only from ``IBM_QUANTUM_TOKEN``.  They are never accepted
from an optimization payload, logged, or returned in result metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeConfig:
    """Validated, non-sensitive IBM Runtime configuration."""

    backend_name: str | None = None
    optimization_level: int = 2
    resilience_level: int = 1
    use_dynamical_decoupling: bool = True
    max_shots: int = 4096
    max_qubits: int = 24


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field} must be a boolean.")


def parse_runtime_config(
    options: Mapping[str, Any] | None = None,
) -> RuntimeConfig:
    """Validate IBM Runtime options and reject credentials in requests."""
    values = dict(options or {})
    forbidden = {
        "token",
        "ibm_token",
        "ibm_quantum_token",
        "IBM_QUANTUM_TOKEN",
    }.intersection(values)
    if forbidden:
        raise ValueError(
            "IBM credentials must be configured through IBM_QUANTUM_TOKEN, "
            "never through an algorithm payload."
        )

    config = RuntimeConfig(
        backend_name=(
            str(values["backend_name"]).strip()
            if values.get("backend_name")
            else None
        ),
        optimization_level=int(values.get("optimization_level", 2)),
        resilience_level=int(values.get("resilience_level", 1)),
        use_dynamical_decoupling=_as_bool(
            values.get(
                "use_dynamical_decoupling",
                values.get("use_dd", True),
            ),
            "use_dynamical_decoupling",
        ),
        max_shots=int(values.get("max_shots", 4096)),
        max_qubits=int(values.get("max_qubits", 24)),
    )
    if not 0 <= config.optimization_level <= 3:
        raise ValueError("optimization_level must be between 0 and 3.")
    if not 0 <= config.resilience_level <= 2:
        raise ValueError("resilience_level must be between 0 and 2.")
    if config.max_shots < 1:
        raise ValueError("max_shots must be positive.")
    if config.max_qubits < 1:
        raise ValueError("max_qubits must be positive.")
    return config


def get_runtime_service():
    """Create an authenticated IBM Runtime service using the environment token."""
    token = os.getenv("IBM_QUANTUM_TOKEN")
    if not token:
        raise RuntimeError(
            "IBM_QUANTUM_TOKEN is required when executor='ibm'."
        )

    from qiskit_ibm_runtime import QiskitRuntimeService

    # Current IBM Quantum Platform channel.  Keep the credential server-side.
    return QiskitRuntimeService(
        channel="ibm_quantum_platform",
        token=token,
    )


def get_backend(config: RuntimeConfig, required_qubits: int):
    """Return an operational backend with sufficient qubits."""
    if required_qubits < 1:
        raise ValueError("required_qubits must be positive.")
    if required_qubits > config.max_qubits:
        raise ValueError(
            f"Candidate register needs {required_qubits} qubits; "
            f"configured server limit is {config.max_qubits}."
        )

    service = get_runtime_service()
    if config.backend_name:
        backend = service.backend(config.backend_name)
        status = backend.status()
        if not status.operational:
            raise RuntimeError(
                f"IBM backend '{backend.name}' is not operational."
            )
        if backend.num_qubits < required_qubits:
            raise ValueError(
                f"IBM backend '{backend.name}' has only "
                f"{backend.num_qubits} qubits; {required_qubits} are required."
            )
        return backend

    return service.least_busy(
        simulator=False,
        operational=True,
        min_num_qubits=required_qubits,
    )


def get_pass_manager(backend: Any, optimization_level: int):
    """Create a preset pass manager for the selected backend."""
    from qiskit.transpiler.preset_passmanagers import (
        generate_preset_pass_manager,
    )

    return generate_preset_pass_manager(
        optimization_level=optimization_level,
        backend=backend,
    )


def get_primitives(backend: Any, config: RuntimeConfig):
    """Create Runtime V2 Estimator and Sampler primitives."""
    from qiskit_ibm_runtime import EstimatorV2, SamplerV2
    from qiskit_ibm_runtime.options import EstimatorOptions, SamplerOptions

    sampler_options = SamplerOptions()
    estimator_options = EstimatorOptions()
    estimator_options.resilience_level = config.resilience_level

    if config.use_dynamical_decoupling:
        sampler_options.dynamical_decoupling.enable = True
        sampler_options.dynamical_decoupling.sequence_type = "XX"
        estimator_options.dynamical_decoupling.enable = True
        estimator_options.dynamical_decoupling.sequence_type = "XX"

    return (
        EstimatorV2(mode=backend, options=estimator_options),
        SamplerV2(mode=backend, options=sampler_options),
    )


def safe_job_id(job: Any) -> str | None:
    """Return a Runtime job ID without exposing other job attributes."""
    if job is None:
        return None
    value = getattr(job, "job_id", None)
    try:
        return str(value() if callable(value) else value) if value else None
    except Exception:
        return None


def backend_name(backend: Any) -> str | None:
    """Read a backend name across Qiskit backend versions."""
    if backend is None:
        return None
    value = getattr(backend, "name", None)
    try:
        result = value() if callable(value) else value
    except Exception:
        result = None
    return str(result) if result else None


def circuit_metadata(
    circuit: Any,
    *,
    backend: Any | None = None,
    job_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return non-sensitive circuit and execution metadata."""
    operations = circuit.count_ops() if hasattr(circuit, "count_ops") else {}
    two_qubit_names = {
        "cx",
        "cz",
        "ecr",
        "swap",
        "rzz",
        "rxx",
        "ryy",
    }
    return {
        "backend": backend_name(backend),
        "job_ids": list(job_ids or []),
        "transpiled_circuit_depth": (
            int(circuit.depth()) if hasattr(circuit, "depth") else None
        ),
        "two_qubit_gate_count": int(
            sum(
                int(value)
                for name, value in operations.items()
                if str(name) in two_qubit_names
            )
        ),
    }
