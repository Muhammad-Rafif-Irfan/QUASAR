# QUASAR (Quantum-Accelerated Supply-chain And Routing) 🚀

QUASAR is a classical-quantum hybrid logistics orchestration system for small, auditable Traveling Salesperson Problem (TSP) experiments alongside a classical routing baseline. Its quantum path is a bounded cost-Hamiltonian QAOA demonstration, not a claim of quantum advantage.

Developed as part of the **QC4SG Hackathon 2026** (Team 23).

## 👥 Contributors (Team 23)

* **Muhammad Rafif Irfan** - Tech Lead (Quantum Mechanics & Optimization Algorithm)
* **Trịnh Hoàng Tú** - Backend & Optimization Algorithms Engineer
* **Aga Ucu Fradana** - Core Research & Cryptography Engineer
* **Trần Văn Hội** - Frontend & Product Integration Engineer

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
├── app/                      # FastAPI API (production)
├── core/                     # Bounded cost-Hamiltonian QAOA solver (wired into API)
├── services/                 # OR-Tools classical solver
├── frontend/                 # React + Vite UI
├── research/ibm_sdvrp/       # Experimental IBM SDVRP runners (not in API image)
├── research/archive/         # Legacy scratch scripts
├── tests/                    # Unit + integration tests
├── docs/                     # Design / quantum review notes
├── scripts/dev.ps1|.sh       # Local uvicorn + frontend launcher
├── Dockerfile                # API image
├── docker-compose.yml        # API + frontend stack
└── requirements.txt
```

---

## 🔒 Security Hardening & Middleware Stack

QUASAR implements a **defense-in-depth** security architecture with layered middleware:

```
Client Request → ErrorSanitization → SecurityHeaders → RequestSizeLimit
             → RateLimit → RequestTracing → CORS → Route Handler
```

### Middleware Components:

| Layer | Module | Purpose |
|-------|--------|---------|
| **Security Headers** | `app/middleware/security.py` | OWASP headers (HSTS, CSP, X-Frame-Options, nosniff) |
| **Request Size Limit** | `app/middleware/security.py` | Rejects payloads > 512KB (configurable) |
| **Error Sanitization** | `app/middleware/security.py` | Hides internal stack traces in production |
| **Rate Limiting** | `app/middleware/rate_limiter.py` | Sliding window: 20 req/60s global, 5 req/60s for `/optimize` |
| **Request Tracing** | `app/middleware/observability.py` | Correlation ID (X-Request-ID), structured JSON logging, perf metrics |
| **CORS** | FastAPI built-in | Configurable origins via `ALLOWED_ORIGINS` env var |

### Environment Configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `QUASAR_ENV` | `production` | Environment mode (`production` / `development`) |
| `IBM_QUANTUM_TOKEN` | — | IBM Quantum Platform API key |
| `RATE_LIMIT_MAX_REQUESTS` | `20` | Max API requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window duration |
| `OPTIMIZE_BURST_LIMIT` | `5` | Max optimization requests per window |
| `MAX_REQUEST_BODY_KB` | `512` | Maximum request body size in KB |
| `MAX_OPTIMIZATION_STOPS` | `15` | Maximum stops for a classical demo run; QAOA remains separately capped at 3 |
| `MAX_QAOA_STOPS` | `3` | Maximum stops for the verified QAOA encoding; larger runs must be classical |
| `QAOA_SIMULATOR_MAXITER` | `8` | COBYLA iterations for simulator QAOA runs |
| `QAOA_HARDWARE_MAXITER` | `4` | COBYLA iterations for hardware QAOA runs; each adds a queued job |
| `OSMNX_DEADLINE_SECONDS` | `8` | End-to-end deadline for road-network download before Haversine fallback |
| `DATABASE_URL` | `sqlite:///./data/quasar.db` | SQLAlchemy database URL |
| `ALLOWED_ORIGINS` | Local frontend origins | Comma-separated CORS origins |
| `TRUST_PROXY_HEADERS` | `false` | Set only behind a trusted reverse proxy to honor `X-Forwarded-For` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 🐳 Deployment (Docker)

### Quick Start with Docker Compose:
```bash
# Build and run API + frontend
docker compose up --build -d

# Frontend → http://localhost:8080
# API docs  → http://localhost:8000/docs

# View logs
docker compose logs -f quasar-api quasar-frontend

# Stop
docker compose down
```

### Manual Docker Build:
```bash
docker build -t quasar-api:latest .
docker run -d -p 8000:8000 \
  -e IBM_QUANTUM_TOKEN="your_token_here" \
  -e QUASAR_ENV=production \
  --name quasar \
  quasar-api:latest
```

### Production Docker Features:
- **Multi-stage build** — minimal attack surface (~200MB final image)
- **Non-root execution** — runs as `quasar` user (UID/GID isolation)
- **Health checks** — built-in `HEALTHCHECK` via `/health` endpoint
- **Resource limits** — 2GB RAM / 2 CPU cores (configurable in compose)
- **Log rotation** — JSON file driver, 10MB max, 3 file rotation

---

## ⚙️ CI/CD Pipeline (GitHub Actions)

Automated pipeline triggers on push to `main` or `feature/*` branches:

```
┌─────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Lint   │ ──> │   Test   │ ──> │   Security   │ ──> │ Docker Build │
│ Flake8  │     │ test_quasar│    │  pip-audit   │     │  Buildx      │
│ Bandit  │     │  .py      │    │  (CVE scan)  │     │  (verify)    │
└─────────┘     └──────────┘     └──────────────┘     └──────────────┘
```

- **Flake8**: Code style enforcement (PEP 8, max-line 120)
- **Bandit**: Static security analysis (Python-specific vulnerabilities)
- **pip-audit**: Dependency CVE scanning against advisory databases
- **Docker Buildx**: Image build verification with layer caching

---

## 📊 Observability & Monitoring

### Structured Logging:
- **Production**: JSON format (machine-parseable, ELK/CloudWatch compatible)
- **Development**: Human-readable colored output with timestamps

### Request Tracing:
Every request receives a correlation ID (`X-Request-ID`) that propagates through:
```
API Receipt → Distance Matrix → OR-Tools → Cost-Hamiltonian QAOA → DB Write
```

### Performance Headers:
- `X-Request-ID` — Unique trace identifier
- `X-Response-Time-Ms` — Server-side processing time
- `X-RateLimit-Remaining` — Remaining requests in current window

### Health Check Endpoint:
```
GET /health → { status, database, quantum_backend, environment }
```

---

## 🚀 Getting Started

### Option A — Local (uvicorn + frontend)

```bash
# Windows
.\scripts\dev.ps1

# Linux / macOS
bash scripts/dev.sh
```

- API: http://127.0.0.1:8000/docs
- Frontend: http://127.0.0.1:5173 (Vite proxies `/api` → backend)

API only: `.\scripts\dev.ps1 -SkipFrontend` or `SKIP_FRONTEND=1 bash scripts/dev.sh`

### Inspect (how the app runs)

With the API up:

```bash
# Windows
.\scripts\inspect.ps1

# Linux / macOS
bash scripts/inspect.sh
```

Or open: http://127.0.0.1:8000/api/v1/inspect

### Option B — Docker Compose (API + frontend)

```bash
docker compose up --build
```

- Frontend (nginx): http://localhost:8080
- API direct: http://localhost:8000/docs

### Manual API (without script)

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

set QUASAR_ENV=development
set ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
uvicorn app.main:app --reload --port 8000
```

Optional env: `IBM_QUANTUM_TOKEN` (omit → local simulator).

### Tests

```bash
python -m compileall -q app core services research tests
python -m unittest discover -s tests -v
python tests/test_quasar.py
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
      "algorithm": "QAOA (cost Hamiltonian)",
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
      "algorithm": "QAOA-CostHamiltonian-Iter-1",
      "backend_name": "Local Statevector Simulator",
      "status": "COMPLETED",
      "qpu_time_seconds": 0.0,
      "created_at": "2026-06-20T12:00:10"
    }
  ]
}
```
