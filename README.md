# QUASAR (Quantum-Accelerated Supply-chain And Routing) 🚀

QUASAR is a classical-quantum hybrid logistics orchestration system designed to tackle NP-hard Vehicle Routing Problems (VRP) and Traveling Salesperson Problems (TSP) using a cutting-edge **Quantum Annealing-Inspired (QAI) + Higher-Order Binary Optimization (HOBO)** architecture.

Developed as part of the **QC4SG Hackathon 2026** (Team 23).

## 👥 Contributors (Team 23)

* **Muhammad Rafif Irfan** - Tech Lead (Quantum Mechanics & Optimization Algorithm)
* **Trịnh Hoàng Tú** - Tech Lead (System Architecture, DevSecOps & Security Hardening)
* **Aga Ucu Fradana** - Core Research & Cryptography Engineer
* **Trần Văn Hội** - Backend Engineer & Core Infrastructure

---

## 🏗️ System Architecture

Unlike standard rigid quantum solutions, QUASAR implements a **Hybrid Asynchronous Computational Pipeline** built for production-grade reliability:

```
[ Client JSON Input ] ──> [ FastAPI Endpoint ] ──> [ Return Run ID Instantly ]
                                                           │
                                                           │ (Asynchronous Worker)
                                                           ▼
                                               [ Dynamic Distance Matrix ] (OSMnx/Haversine)
                                                           │
                                                           ▼
                                               [ Classical Warm-Start ] (Google OR-Tools)
                                                           │
                                                           ▼
                                               [ Quantum Execution ] (IBM Cloud QPU / Simulator)
                                                           │
                                                           ▼
                                               [ Async Callback & DB Write ] (SQLAlchemy/SQLite)
```

### Key Technical Hardening:
* **Non-Blocking Execution Async Path**: Replaced the dangerous `job.result()` anti-pattern in the main thread with asynchronous task processing via FastAPI `BackgroundTasks`, preventing backend thread exhaustion during cloud QPU queue wait times.
* **Dynamic Geolocation Routing Engine**: Snaps coordinate JSON inputs to actual road networks via OSMnx. Implements a robust 5-second connection timeout that falls back to Haversine great-circle distances if offline or blocked.
* **Deterministic Tour Validation**: Integrates a validation layer checking that the tour visits every location exactly once, does not repeat nodes, and strictly begins and ends at the designated depot to eliminate quantum sampling anomalies.
* **Database Tracing**: Creates three tables using SQLAlchemy (`benchmark_runs`, `quantum_jobs`, and `benchmark_results`) to record full execution metadata, job IDs, approximation ratios relative to OR-Tools, and actual IBM QPU quantum execution time in seconds.
* **Fallback Simulator**: Automatically triggers a local Qiskit simulator (`qiskit.primitives.StatevectorSampler`) when the `IBM_QUANTUM_TOKEN` environment variable is not configured.

---

## 🛠️ Tech Stack
* **Quantum Core**: Qiskit 1.x, Qiskit IBM Runtime (127-Qubit Hardware Pipeline)
* **Backend Framework**: FastAPI (Asynchronous Python Web Server)
* **Classical Solver**: Google OR-Tools (Guided Local Search Baseline)
* **Geospatial Processing**: OSMnx, NetworkX, Folium, OpenStreetMap
* **Database & Mapping**: SQLAlchemy ORM, SQLite/PostgreSQL

---

## 📁 Project Structure

```
QUASAR/
├── app/
│   ├── __init__.py
│   ├── database.py              # SQLAlchemy database engine and session
│   ├── main.py                  # FastAPI controllers and routes
│   ├── models.py                # Database tracing tables
│   ├── schemas.py               # Pydantic validation schemas
│   └── services/
│       ├── __init__.py
│       ├── quantum_driver.py    # Qiskit QAOA / QAI-HOBO loops & OR-Tools solver
│       └── routing.py           # OSMnx snapping, distance matrix, and Folium maps
├── core/                        # Team's standalone mathematical solver modules
│   ├── base_solver.py           # Core base solver classes
│   └── solver_qai_hobo.py       # Standalone QAI + HOBO solver logic
├── services/
│   └── classical_solver.py      # Standalone OR-Tools solver logic
├── requirements.txt             # Project requirements
├── test_quasar.py               # Complete test verification suite
└── README.md                    # Project documentation
```

---

## 🚀 Getting Started

### 1. Installation
Clone the repository and install the production dependencies within a virtual environment:

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate      # On Windows
source .venv/bin/activate    # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory (ignored by git) or export your IBM Quantum token:
```bash
export IBM_QUANTUM_TOKEN="your_ibm_quantum_api_key_here"
```

### 3. Launching the Server
Spin up the Uvicorn ASGI server:
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Running the Verification Suite
Execute the automated test script to verify database migrations, tour validation, fallbacks, and classical-quantum optimization routines:
```bash
python test_quasar.py
```

---

## 🛰️ Production API Specification

### Optimize Route Location
* **Endpoint**: `POST /api/v1/optimize`
* **Content-Type**: `application/json`
* **Payload Structure**:
```json
{
  "depot": {"name": "Depot Pusat", "lat": 16.0544, "lon": 108.2022},
  "stops": [
    {"name": "Pelabuhan", "lat": 16.0650, "lon": 108.2200},
    {"name": "Pasar Con", "lat": 16.0450, "lon": 108.2100},
    {"name": "Bandara", "lat": 16.0438, "lon": 108.1990}
  ]
}
```
* **Response Structure (Instant Sync Return)**:
```json
{
  "run_id": "b3fca21a-4298-4c8d-8012-9c425da722ea",
  "status": "PENDING",
  "message": "Optimization pipeline triggered successfully on IBM Quantum (with simulator fallback)."
}
```

### Poll Status and Results
* **Endpoint**: `GET /api/v1/optimize/{run_id}`
* **Response Structure**:
```json
{
  "run_id": "b3fca21a-4298-4c8d-8012-9c425da722ea",
  "status": "COMPLETED",
  "created_at": "2026-06-20T12:00:00",
  "updated_at": "2026-06-20T12:01:00",
  "error_message": null,
  "depot_name": "Depot Pusat",
  "depot_lat": 16.0544,
  "depot_lon": 108.2022,
  "stops_count": 3,
  "results": [
    {
      "algorithm": "OR-Tools",
      "tour": [0, 3, 2, 1, 0],
      "distance_meters": 7114.0,
      "is_valid": true,
      "validation_error": null,
      "approximation_ratio": 1.0,
      "execution_time_ms": 3000.0,
      "created_at": "2026-06-20T12:00:05"
    },
    {
      "algorithm": "QUBO+QAOA",
      "tour": [0, 1, 2, 3, 0],
      "distance_meters": 7114.0,
      "is_valid": true,
      "validation_error": null,
      "approximation_ratio": 1.0,
      "execution_time_ms": 37.2,
      "created_at": "2026-06-20T12:00:45"
    }
  ],
  "quantum_jobs": [
    {
      "job_id": "sim-qaoa-1-849c38ee",
      "algorithm": "QAOA-Iter-1",
      "backend_name": "Local Statevector Simulator",
      "status": "COMPLETED",
      "qpu_time_seconds": 0.0,
      "created_at": "2026-06-20T12:00:10"
    }
  ]
}
```
