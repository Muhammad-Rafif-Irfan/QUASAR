import pytest


import ibm_qaoa
import ibm_qaoa_plus
import ibm_falqon
import ibm_gas


from ibm_qaoa import run_qaoa_ibm
from ibm_qaoa_plus import run_qaoa_plus_ibm
from ibm_falqon import run_falqon_ibm
from ibm_gas import run_gas_ibm

# ==========================================
# MOCKING IBM CONNECTION UNTUK LOKAL / CI
# ==========================================
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import EstimatorV2, SamplerV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


for module in [ibm_qaoa, ibm_qaoa_plus, ibm_falqon, ibm_gas]:
    module.get_backend = lambda *args, **kwargs: AerSimulator()
    module.get_pass_manager = lambda backend, opt: generate_preset_pass_manager(optimization_level=0, backend=backend)
    module.get_estimator = lambda *args, **kwargs: EstimatorV2()
    module.get_sampler = lambda *args, **kwargs: SamplerV2()

def get_base_payload():
    """Fungsi Python biasa untuk mengembalikan dictionary payload."""
    return {
        "matrix": [
            [0, 10, 15],  # Node 0 (Depot)
            [10, 0, 8],   # Node 1 (Customer)
            [15, 8, 0]    # Node 2 (Customer)
        ],
        "demands": [0, 1, 1],
        "capacities": [5],
        "starting_nodes": [0],
        "n_nodes": 3,
        "n_vehicles": 1,
        "shots": 100,
        "token": "DUMMY_TOKEN_FOR_CI",
        "backend_name": "aer_simulator",
        "optimization_level": 1,
        "resilience_level": 0,
        "use_dd": False,
        "alpha": 10.0,
        "beta": 10.0,
        "lambda_scale": 10.0,
        "demand_priority": 10.0
    }

@pytest.fixture
def base_payload():
    return get_base_payload()

def test_qaoa_smoke(base_payload):
    """Smoke test for the standard QAOA algorithm."""
    payload = base_payload.copy()
    payload.update({
        "p": 1,
        "maxiter": 2  # 2 COBYLA iterations are enough for a smoke test
    })
    
    result = run_qaoa_ibm(payload)
    
    assert isinstance(result, dict)
    assert result["algorithm"] == "QAOA"
    assert "bitstring" in result
    assert "energy" in result
    assert "cost_history" in result
    assert "routes" in result
    assert "valid" in result


def test_qaoa_plus_smoke(base_payload):
    """Smoke test for the QAOA+ algorithm (with XY Mixer)."""
    payload = base_payload.copy()
    payload.update({
        "p": 1,
        "maxiter": 2
    })
    
    result = run_qaoa_plus_ibm(payload)
    
    assert isinstance(result, dict)
    assert result["algorithm"] == "QAOA+"
    assert "bitstring" in result
    assert "energy" in result
    assert "cost_history" in result
    assert "routes" in result
    assert "valid" in result


def test_falqon_smoke(base_payload):
    """Smoke test for the FALQON algorithm."""
    payload = base_payload.copy()
    payload.update({
        "n_layers": 2,  # 2 layers are sufficient to verify the feedback law execution
        "dt": 0.1
    })
    
    result = run_falqon_ibm(payload)
    
    assert isinstance(result, dict)
    assert result["algorithm"] == "FALQON"
    assert "bitstring" in result
    assert "energy" in result
    assert "betas" in result
    assert "energy_history" in result
    assert "routes" in result
    assert "valid" in result


def test_gas_smoke(base_payload):
    """Smoke test for the Grover Adaptive Search (GAS) algorithm."""
    payload = base_payload.copy()
    payload.update({
        "iterations": 2  # 2 iterations are sufficient to verify threshold tightening
    })
    
    result = run_gas_ibm(payload)
    
    assert isinstance(result, dict)
    assert result["algorithm"] == "GAS"
    assert "bitstring" in result
    assert "energy" in result
    assert "threshold" in result
    assert "cost_history" in result
    assert "routes" in result
    assert "valid" in result

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
    
    print("4. Testing GAS...")
    test_gas_smoke(payload)
    print("   -> GAS OK!\n")
    
    print("Testing successfull without error!")