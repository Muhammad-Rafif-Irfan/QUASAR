"""Local/CI smoke tests for the experimental IBM SDVRP runners.

Requires qiskit-aer. GAS is skipped by default because the reversible
threshold oracle needs more qubits than a laptop simulator can handle.
"""

import pytest

qiskit_aer = pytest.importorskip("qiskit_aer")

from . import ibm_falqon  # noqa: E402
from . import ibm_gas  # noqa: E402
from . import ibm_qaoa  # noqa: E402
from . import ibm_qaoa_plus  # noqa: E402
from .ibm_falqon import run_falqon_ibm  # noqa: E402
from .ibm_gas import run_gas_ibm  # noqa: E402
from .ibm_qaoa import run_qaoa_ibm  # noqa: E402
from .ibm_qaoa_plus import run_qaoa_plus_ibm  # noqa: E402
from qiskit.transpiler.preset_passmanagers import (  # noqa: E402
    generate_preset_pass_manager,
)
from qiskit_aer import AerSimulator  # noqa: E402
from qiskit_aer.primitives import EstimatorV2, SamplerV2  # noqa: E402


for module in [ibm_qaoa, ibm_qaoa_plus, ibm_falqon, ibm_gas]:
    module.get_backend = lambda *args, **kwargs: AerSimulator()
    module.get_pass_manager = (
        lambda backend, opt: generate_preset_pass_manager(
            optimization_level=0, backend=backend
        )
    )
    module.get_estimator = lambda *args, **kwargs: EstimatorV2()
    module.get_sampler = lambda *args, **kwargs: SamplerV2()


def get_base_payload():
    """Return a tiny CVRP payload suitable for smoke testing."""
    return {
        "matrix": [
            [0, 10, 15],
            [10, 0, 8],
            [15, 8, 0],
        ],
        "demands": [0, 1, 1],
        "capacities": [5],
        "starting_nodes": [0],
        "shots": 100,
        "token": "DUMMY_TOKEN_FOR_CI",
        "backend_name": "aer_simulator",
        "optimization_level": 1,
        "resilience_level": 0,
        "use_dd": False,
        "alpha": 10.0,
        "beta": 10.0,
        "lambda_scale": 10.0,
        "demand_priority": False,
    }


@pytest.fixture
def base_payload():
    return get_base_payload()


def _assert_valid_result(result, algorithm):
    assert isinstance(result, dict)
    assert result["algorithm"] == algorithm
    assert "bitstring" in result
    assert "energy" in result
    assert "routes" in result
    assert isinstance(result["valid"], bool)
    if result["valid"]:
        assert result["route_cost"] is not None
        assert result["route_cost"] > 0


def test_qaoa_smoke(base_payload):
    payload = base_payload.copy()
    payload.update({"p": 1, "maxiter": 2})
    result = run_qaoa_ibm(payload)
    assert "cost_history" in result
    _assert_valid_result(result, "QAOA")


def test_qaoa_plus_smoke(base_payload):
    payload = base_payload.copy()
    payload.update({"p": 1, "maxiter": 2})
    result = run_qaoa_plus_ibm(payload)
    assert "cost_history" in result
    _assert_valid_result(result, "QAOA+")
    assert result["valid"] is True, "QAOA+ must preserve constraint feasibility"


def test_falqon_smoke(base_payload):
    payload = base_payload.copy()
    payload.update({"n_layers": 2, "dt": 0.1})
    result = run_falqon_ibm(payload)
    assert "betas" in result
    assert "energy_history" in result
    _assert_valid_result(result, "FALQON")


@pytest.mark.skip(
    reason=(
        "GAS threshold oracle needs extra ancilla qubits beyond laptop "
        "simulator capacity for the CVRP encoding."
    )
)
def test_gas_smoke(base_payload):
    payload = base_payload.copy()
    payload.update({"iterations": 2})
    result = run_gas_ibm(payload)
    assert "threshold" in result
    assert "cost_history" in result
    _assert_valid_result(result, "GAS")


if __name__ == "__main__":
    print("Manual smoke testing...\n")
    payload = get_base_payload()

    print("1. Testing QAOA...")
    test_qaoa_smoke(payload)
    print("   -> QAOA OK!\n")

    print("2. Testing QAOA+...")
    test_qaoa_plus_smoke(payload)
    print("   -> QAOA+ OK!\n")

    print("3. Testing FALQON...")
    test_falqon_smoke(payload)
    print("   -> FALQON OK!\n")

    print("4. GAS smoke skipped on laptop-scale simulators.")
    print("Testing successful without error!")
