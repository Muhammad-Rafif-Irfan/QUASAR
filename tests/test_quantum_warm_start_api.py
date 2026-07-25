"""Integration checks for the bounded QAOA+ warm-start endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def _payload() -> dict:
    return {
        "matrix": [
            [0, 10, 1, 10],
            [10, 0, 1, 1],
            [1, 1, 0, 10],
            [10, 1, 10, 0],
        ],
        "demands": [0, 1, 1, 1],
        "capacities": [3],
        "starting_nodes": [0],
        "routes": {"0": [0, 1, 2, 3, 0]},
        "executor": "local",
        "reps": 1,
        "maxiter": 8,
        "shots": 256,
        "max_candidates": 8,
        "polishing_iterations": 5,
        "random_seed": 42,
        "initialization": "w-state",
    }


def test_warm_start_refines_or_keeps_a_valid_classical_seed(monkeypatch) -> None:
    monkeypatch.delenv("IBM_QUANTUM_TOKEN", raising=False)
    monkeypatch.delenv("QISKIT_IBM_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/quantum/warm-start", json=_payload())

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["executor"] == "local"
    assert result["valid"] is True
    assert result["final_cost"] <= result["initial_cost"]
    assert result["backend"] == "statevector"
    assert result["n_qubits"] <= 10


def test_warm_start_refuses_hardware_execution() -> None:
    payload = _payload()
    payload["executor"] = "ibm"
    with TestClient(app) as client:
        response = client.post("/api/v1/quantum/warm-start", json=payload)

    assert response.status_code == 422
