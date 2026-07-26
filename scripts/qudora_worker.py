"""Run inside the isolated QUDORA virtual environment only.

stdin/stdout protocol: one JSON request/response.  Credentials are inherited
from QUDORA_API_TOKEN and are never accepted in the request or emitted.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def _name(value: Any) -> str | None:
    candidate = getattr(value, "name", None)
    return str(candidate() if callable(candidate) else candidate) if candidate else None


def _job_id(job: Any) -> str | None:
    candidate = getattr(job, "job_id", None)
    return str(candidate() if callable(candidate) else candidate) if candidate else None


def _counts(result: Any) -> dict[str, int]:
    getter = getattr(result, "get_counts", None)
    if not callable(getter):
        raise RuntimeError("QUDORA result exposes no get_counts() method.")
    raw = getter()
    if isinstance(raw, list):
        raw = raw[0]
    if not isinstance(raw, dict):
        raise RuntimeError("QUDORA returned an unsupported counts format.")
    return {str(bitstring): int(count) for bitstring, count in raw.items()}


def _provider():
    token = os.environ.get("QUDORA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("QUDORA_API_TOKEN is not configured.")
    from qudora_sdk.qiskit import QUDORAProvider
    return QUDORAProvider(token=token)


def handle(request: dict[str, Any]) -> dict[str, Any]:
    provider = _provider()
    if request.get("action") == "check":
        return {"backends": [{"name": _name(backend)} for backend in provider.backends()]}
    if request.get("action") != "run":
        raise ValueError("Unsupported QUDORA worker action.")
    from qiskit import qasm2
    circuit = qasm2.loads(str(request["qasm2"]))
    backend = provider.get_backend(str(request["backend_name"]))
    job = backend.run(
        circuit,
        job_name="QUASAR QAOA+ warm-start",
        shots=int(request["shots"]),
        backend_settings=dict(request.get("backend_settings") or {}),
    )
    result = job.result(timeout=60)
    return {
        "counts": _counts(result), "backend": _name(backend), "job_ids": [job_id] if (job_id := _job_id(job)) else [],
    }


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        print(json.dumps({"ok": True, "result": handle(request)}))
    except Exception as error:
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
