import sys
import os
import json
import numpy as np

# Ensure app package is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, SessionLocal, Base
from app.models import BenchmarkRun, QuantumJob, BenchmarkResult
from app.services.quantum_driver import (
    validate_tour, 
    solve_or_tools, 
    solve_qaoa, 
    solve_qai_hobo, 
    run_optimization_pipeline, 
    get_quantum_backend_and_sampler
)
from app.services.routing import calculate_distance_matrix

def run_tests():
    print("=========================================================")
    # Initialize DB schema
    print("[1] Initializing SQLite database schema...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("    -> Database initialized successfully.")

    # 2. Test Tour Validation
    print("\n[2] Testing validate_tour function...")
    # Valid tour for n=4
    v_ok, err = validate_tour([0, 2, 1, 3, 0], 4)
    print(f"    - Valid tour check [0,2,1,3,0] (n=4): is_valid={v_ok}, error={err}")
    assert v_ok is True, "Valid tour failed validation"

    # Invalid: no depot end
    v_ok, err = validate_tour([0, 2, 1, 3, 2], 4)
    print(f"    - Invalid tour check [0,2,1,3,2] (n=4): is_valid={v_ok}, error={err}")
    assert v_ok is False, "Invalid tour passed validation"

    # Invalid: missing stop
    v_ok, err = validate_tour([0, 2, 2, 3, 0], 4)
    print(f"    - Invalid tour check [0,2,2,3,0] (n=4): is_valid={v_ok}, error={err}")
    assert v_ok is False, "Invalid tour passed validation"

    # Invalid: incorrect length
    v_ok, err = validate_tour([0, 2, 1, 0], 4)
    print(f"    - Invalid tour check [0,2,1,0] (n=4): is_valid={v_ok}, error={err}")
    assert v_ok is False, "Invalid tour passed validation"
    print("    -> Tour validation tests passed successfully.")

    # 3. Dynamic OSMnx Routing & Distance Matrix
    print("\n[3] Testing dynamic distance matrix calculation (Da Nang coords)...")
    depot = {"name": "Depot Pusat", "lat": 16.0544, "lon": 108.2022}
    stops = [
        {"name": "Pelabuhan", "lat": 16.0650, "lon": 108.2200},
        {"name": "Pasar Con", "lat": 16.0450, "lon": 108.2100},
        {"name": "Bandara", "lat": 16.0438, "lon": 108.1990}
    ]
    
    dist_matrix, G, nodes = calculate_distance_matrix(depot, stops)
    print(f"    - Points count: {len(stops) + 1}")
    print(f"    - Distance Matrix shape: {dist_matrix.shape}")
    print("    - Matrix contents:")
    print(dist_matrix)
    
    assert dist_matrix.shape == (4, 4), "Distance matrix shape mismatch"
    assert np.all(dist_matrix >= 0), "Negative distances found"
    print("    -> Dynamic distance matrix calculation passed successfully.")

    # 4. Classical Solver (OR-Tools)
    print("\n[4] Testing classical solver (OR-Tools)...")
    ort_tour, ort_dist, ort_time_ms = solve_or_tools(dist_matrix)
    print(f"    - OR-Tools Tour: {ort_tour}")
    print(f"    - OR-Tools Distance: {ort_dist} m")
    print(f"    - Execution Time: {ort_time_ms:.2f} ms")
    
    v_ok, err = validate_tour(ort_tour, 4)
    assert v_ok is True, f"OR-Tools tour invalid: {err}"
    print("    -> Classical solver testing passed successfully.")

    # 5. Quantum Solver (QAOA & QAI+HOBO in local simulator mode)
    print("\n[5] Testing Quantum Solvers (QAOA & QAI+HOBO) on local simulator...")
    backend, sampler, pm, is_simulator = get_quantum_backend_and_sampler()
    print(f"    - Backend Simulator mode: {is_simulator}")
    assert is_simulator is True, "Expected simulator mode since IBM_QUANTUM_TOKEN is not set"

    run_id = "test-run-1234"
    db = SessionLocal()
    
    # Pre-add run to DB to satisfy foreign keys
    test_run = BenchmarkRun(
        id=run_id,
        status="PENDING",
        depot_name=depot["name"],
        depot_lat=depot["lat"],
        depot_lon=depot["lon"],
        stops_count=len(stops),
        stops_data=json.dumps(stops)
    )
    db.add(test_run)
    db.commit()

    print("    - Executing QAOA simulator run...")
    qaoa_tour, qaoa_dist, qaoa_qpu_sec = solve_qaoa(dist_matrix, backend, sampler, pm, is_simulator, run_id, db)
    print(f"      QAOA Best Tour: {qaoa_tour}")
    print(f"      QAOA Distance: {qaoa_dist} m")
    
    print("    - Executing QAI+HOBO simulator run...")
    qai_tour, qai_dist, qai_qpu_sec = solve_qai_hobo(dist_matrix, backend, sampler, pm, is_simulator, ort_tour, run_id, db)
    print(f"      QAI+HOBO Best Tour: {qai_tour}")
    print(f"      QAI+HOBO Distance: {qai_dist} m")

    db.close()
    print("    -> Quantum solvers simulation tests passed.")

    # 6. Entire Pipeline Execution & DB Trace Verification
    print("\n[6] Testing full pipeline execution (run_optimization_pipeline)...")
    run_id_pipeline = "pipeline-run-5678"
    db = SessionLocal()
    
    new_run = BenchmarkRun(
        id=run_id_pipeline,
        status="PENDING",
        depot_name=depot["name"],
        depot_lat=depot["lat"],
        depot_lon=depot["lon"],
        stops_count=len(stops),
        stops_data=json.dumps(stops)
    )
    db.add(new_run)
    db.commit()
    db.close()

    # Trigger pipeline
    run_optimization_pipeline(run_id_pipeline, depot, stops)

    # Verify database contents
    db = SessionLocal()
    pipeline_run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id_pipeline).first()
    
    print(f"    - Pipeline Run Status: {pipeline_run.status}")
    assert pipeline_run.status == "COMPLETED", f"Expected COMPLETED, got {pipeline_run.status}"
    
    print(f"    - Results stored in DB ({len(pipeline_run.results)} records):")
    for r in pipeline_run.results:
        print(f"      * {r.algorithm}: Distance={r.distance_meters}m, Valid={r.is_valid}, Ratio={r.approximation_ratio:.3f}, Time={r.execution_time_ms:.1f}ms")
    
    print(f"    - Quantum jobs logged in DB ({len(pipeline_run.quantum_jobs)} records):")
    for j in pipeline_run.quantum_jobs:
        print(f"      * {j.algorithm}: Job ID={j.job_id}, Backend={j.backend_name}, Status={j.status}, QPU Time={j.qpu_time_seconds}s")
        
    assert len(pipeline_run.results) == 3, "Expected 3 results (OR-Tools, QAOA, QAI+HOBO)"
    # QAOA loop runs 3 iterations (can evaluate 4 times), QAI runs 3 temperatures -> total 6 or 7 quantum jobs should be logged
    assert len(pipeline_run.quantum_jobs) in [6, 7], f"Expected 6 or 7 quantum jobs, got {len(pipeline_run.quantum_jobs)}"

    db.close()
    print("    -> Full pipeline test passed successfully!")
    print("\n=========================================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY! QUASAR BACKEND IS READY! 🎉")
    print("=========================================================")

if __name__ == "__main__":
    run_tests()
