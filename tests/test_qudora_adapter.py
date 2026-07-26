"""Safety checks for the isolated QUDORA adapter."""

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.quantum_hybrid.qudora import check_connection, run_bound_qasm2
from app.services.quantum_hybrid.warm_start import parse_hybrid_config


def test_qudora_check_reports_missing_token_without_invoking_worker(monkeypatch) -> None:
    monkeypatch.delenv("QUDORA_API_TOKEN", raising=False)
    monkeypatch.delenv("QUDORA_WORKER_PYTHON", raising=False)
    result = check_connection()
    assert result["status"] == "not_configured"
    assert result["token_configured"] is False


def test_qudora_executor_is_accepted_but_invalid_backend_is_rejected() -> None:
    config = parse_hybrid_config({"executor": "qudora"})
    assert config.executor == "qudora"
    with pytest.raises(ValueError, match="QUDORA backend"):
        run_bound_qasm2("OPENQASM 2.0;", shots=32, runtime_options={"backend_name": "unknown"})


def test_qudora_connection_endpoint_is_safe_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("QUDORA_API_TOKEN", raising=False)
    monkeypatch.delenv("QUDORA_WORKER_PYTHON", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/quantum/qudora/connection-check")
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


def test_qudora_handoff_uses_the_qiskit_21_compatible_qasm2_dialect() -> None:
    from qiskit import QuantumCircuit, qasm2, transpile

    circuit = QuantumCircuit(2)
    circuit.rxx(0.25, 0, 1)
    circuit.measure_all()
    program = qasm2.dumps(
        transpile(circuit, basis_gates=["u3", "cx"], optimization_level=0)
    )
    assert "sxdg" not in program
    assert "u3(" in program
