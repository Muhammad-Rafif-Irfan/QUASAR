"""Isolated QUDORA Cloud worker adapter.

The QUDORA SDK pins a Qiskit version that conflicts with IBM Runtime, so this
module deliberately never imports it.  It invokes a separately configured
+Python worker and exchanges only JSON/OpenQASM 2.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping


CANONICAL_BACKENDS = {"Qamelion", "QVLS-Q1 Emulator"}


def _worker_python() -> str:
    configured = os.environ.get("QUDORA_WORKER_PYTHON", "").strip()
    path = Path(configured) if configured else Path.cwd() / ".qudora-worker" / "Scripts" / "python.exe"
    if not path.is_file():
        raise RuntimeError("QUDORA worker is not installed. Run scripts/setup_qudora_worker.ps1 or set QUDORA_WORKER_PYTHON.")
    return str(path)


def _worker_script() -> str:
    return str(Path(__file__).resolve().parents[3] / "scripts" / "qudora_worker.py")


def _run_worker(payload: Mapping[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    if not os.environ.get("QUDORA_API_TOKEN", "").strip():
        raise RuntimeError("QUDORA_API_TOKEN is not configured.")
    try:
        completed = subprocess.run(
            [_worker_python(), _worker_script()],
            input=json.dumps(dict(payload)),
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout_seconds), 90)),
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("QUDORA worker timed out.") from error
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("QUDORA worker returned an invalid response.") from error
    if completed.returncode != 0 or not result.get("ok"):
        raise RuntimeError(str(result.get("error", "QUDORA worker failed.")))
    return dict(result["result"])


def check_connection() -> dict[str, Any]:
    """Read-only token/backend discovery through the isolated worker."""
    env_file_present = Path(".env").is_file()
    token_configured = bool(os.environ.get("QUDORA_API_TOKEN", "").strip())
    try:
        _worker_python()
        worker_configured = True
    except RuntimeError:
        worker_configured = False
    if not token_configured:
        return {
            "status": "not_configured", "env_file_present": env_file_present,
            "token_configured": False, "worker_configured": worker_configured,
            "message": "QUDORA_API_TOKEN is not available to this API process.",
            "backends": [],
        }
    if not worker_configured:
        return {
            "status": "worker_not_configured", "env_file_present": env_file_present,
            "token_configured": True, "worker_configured": False,
            "message": "QUDORA token is configured, but QUDORA_WORKER_PYTHON is missing.",
            "backends": [],
        }
    try:
        result = _run_worker({"action": "check"}, timeout_seconds=20)
        return {
            "status": "connected", "env_file_present": env_file_present,
            "token_configured": True, "worker_configured": True,
            "message": "QUDORA connection verified. No circuit was submitted.",
            "backends": result.get("backends", []),
        }
    except RuntimeError:
        return {
            "status": "connection_failed", "env_file_present": env_file_present,
            "token_configured": True, "worker_configured": True,
            "message": "QUDORA could not verify the token or list available backends.",
            "backends": [],
        }


def run_bound_qasm2(qasm2_program: str, *, shots: int, runtime_options: Mapping[str, Any] | None) -> dict[str, Any]:
    options = dict(runtime_options or {})
    backend_name = str(options.get("backend_name", os.environ.get("QUDORA_BACKEND", "Qamelion"))).strip()
    if backend_name not in CANONICAL_BACKENDS:
        raise ValueError("QUDORA backend must be Qamelion or QVLS-Q1 Emulator.")
    if not 1 <= shots <= 2048:
        raise ValueError("QUDORA warm-start shots must be between 1 and 2048.")
    backend_settings = {
        key: float(options[key])
        for key in (
            "measurement_error_probability", "two_qubit_gate_noise_strength",
            "single_qubit_gate_noise_strength", "dephasing_T2_time",
        )
        if key in options and options[key] is not None
    }
    if any(value < 0 for value in backend_settings.values()):
        raise ValueError("QUDORA noise settings cannot be negative.")
    return _run_worker({
        "action": "run", "qasm2": qasm2_program, "backend_name": backend_name,
        "shots": shots, "backend_settings": backend_settings,
    }, timeout_seconds=int(options.get("timeout_seconds", 60)))
