# FloodGuard

Real-Time Flood Intelligence & Safe Routing. FloodGuard is being built to explain flood-aware road routes and update journeys as conditions change.

**Implemented through Phase 14.** The responsive Next.js/MapLibre workspace supports source and destination selection, baseline and deterministic risk-aware routes, real-time SSE rerouting on flood invalidation (Phase 8), Redis caching (Phase 9), real environmental weather adapters (Phase 10), reproducible ML datasets (Phase 11), offline flood models (Phase 12), ML-augmented routing (Phase 13), and AWS SQS asynchronous event processing with Redis idempotency and out-of-order suppression (Phase 14).

## Architecture

Read [architecture](docs/architecture.md), [system design](docs/system-design.md), [API overview](docs/api-overview.md), [event contracts](docs/events-v1.md), [SQS ingress](docs/sqs.md), and [ML inference architecture](docs/ml-inference.md). [Database design](docs/database.md) describes persistence, and [interactive map design](docs/frontend-map.md) describes the frontend boundary.

```text
frontend/        Next.js App Router, strict TypeScript, Tailwind, Vitest
backend/         FastAPI, async SQLAlchemy/asyncpg, GeoAlchemy2, Alembic, Pytest
infrastructure/  Local PostGIS extension initialization only
scripts/         Core checks, cache benchmarks, and read-only HTTP smoke checks
docs/            Architecture and verification evidence
simulations/     Deterministic environmental scenarios and JSONL replay
ml/              Reproducible ML dataset pipelines and model artifacts (floodguard_ml)
workers/, load-tests/  Reserved; no implementation
```

## Prerequisites

For the complete stack, install Docker with a running daemon and the Compose v2+ plugin (`docker compose version`). Docker Desktop includes Compose. This setup uses official PostgreSQL/PostGIS, Redis, Python and Node images. The PostGIS image requires `linux/amd64`; Apple Silicon needs working x86 emulation in Docker Desktop/Colima. It was verified on an arm64 Docker host with emulation.

For running application processes outside Docker, also install **Python 3.13**, **uv** and **Node.js 24 LTS with npm**. Only uv and npm manage dependencies. Commit `backend/uv.lock` and `frontend/package-lock.json`; installs use `uv sync --locked` and `npm ci`. See [uv installation](https://docs.astral.sh/uv/getting-started/installation/).

## Environment setup

From the repository root:

```sh
cp .env.example .env
```

The example contains development-only placeholders. `.env` and frontend `.env.local` are ignored. Replace credentials before using shared infrastructure; never use these local defaults in production. Keep PostgreSQL user/database/password and host `DATABASE_URL` synchronized if changing them. URL-encode special characters in credentials or use URL-safe local values.

| Setting | Purpose |
| --- | --- |
| `APP_NAME`, `APP_ENV`, `APP_VERSION` | API metadata and environment |
| `APP_DEBUG`, `DEBUG`, `LOG_LEVEL` | `APP_DEBUG` is the preferred namespaced debug flag; `DEBUG` remains a fallback. Debug enables DEBUG application logs; client tracebacks stay disabled |
| `DATABASE_URL` | Host backend asyncpg URL; Compose substitutes the `postgres` service host |
| `REDIS_URL` | Host Redis URL; Compose substitutes the `redis` service host |
| `API_V1_PREFIX` | Versioned API path; Compose also passes it to the browser client |
| `FRONTEND_URL` | One exact allowed browser origin for CORS |
| `HEALTH_CHECK_TIMEOUT_SECONDS` | Per-dependency deadline, default 2 seconds |
| `REDIS_REQUIRED` | Default true: Redis outage makes readiness 503; false reports degraded/200 when DB/PostGIS work |
| `ML_ENABLED` | Master toggle for ML flood prediction services (default `true`) |
| `ML_MODE` | ML integration mode: `DISABLED`, `SHADOW` (default: logging & telemetry only), or `ACTIVE` (fused risk penalties) |
| `ML_MODEL_PATH` | Path to persisted model artifacts directory (default `ml/artifacts/xgboost-v1`) |
| `ML_MODEL_VERSION` | Identifier of active model (default `xgboost-v1`) |
| `ML_RISK_WEIGHT` | Blending weight $\alpha$ for ACTIVE fusion (default `0.35`) |
| `EVENT_TRANSPORT` | Ingress transport: `IN_PROCESS` (default for local dev) or `SQS` (asynchronous AWS queues) |
| `SQS_ENABLED` | Toggle for AWS SQS publisher and background consumer (default `false`) |
| `AWS_REGION` | AWS region for SQS client (default `us-east-1`) |
| `SQS_ENDPOINT_URL` | Optional custom SQS endpoint URL (for LocalStack / offline tests) |
| `SQS_ENVIRONMENT_QUEUE_URL` | Target SQS queue URL for weather, sensor, and simulation events |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-reachable backend URL, default `http://localhost:8000` |
| `NEXT_PUBLIC_MAP_STYLE_URL` | Public MapLibre style document; default demo style requires internet access |
| `FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT` | Loopback-published development ports |
| `POSTGIS_PLATFORM` | Default `linux/amd64` for the selected official image |

## Run with Docker

```sh
docker compose up --build
```

Or start in the background and wait for health checks:

```sh
docker compose up --build -d --wait --wait-timeout 180
docker compose ps
```

Open:

- Frontend: [http://localhost:3000](http://localhost:3000)
- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- Readiness: [http://localhost:8000/api/v1/health/ready](http://localhost:8000/api/v1/health/ready)

The map starts in source-selection mode. Click the map or enter coordinates, choose a destination and FASTEST/BALANCED/SAFEST, then calculate a mock preview. It does not follow stored roads or live flood conditions. “Use my location” requests one browser position only after a click and sends nothing to the backend in Phase 3.

All services have health checks. Backend starts after database/cache readiness; frontend starts after backend readiness. Source mounts enable frontend hot reload and Uvicorn reload. Rebuild when dependency manifests/lockfiles or image-level configuration change. PostgreSQL persists in the `postgres_data` volume. Redis is ephemeral, with disk persistence disabled: Phase 1 stores no cache/business data, so a Redis volume would preserve nothing useful.

```sh
docker compose logs -f backend frontend
docker compose down
```

For an intentional database reset, the following command **deletes this stack's persistent database volume**:

```sh
docker compose down -v
```

### Networking

Containers reach PostgreSQL as `postgres:5432` and Redis as `redis:6379`, using Compose's internal network. `localhost` inside a container means that same container. The dashboard fetch runs in the browser, so `NEXT_PUBLIC_API_BASE_URL` uses `http://localhost:8000`, not `http://backend:8000`. Database/cache and application host ports bind only to `127.0.0.1` for local development.

If changing frontend/backend host ports, also update `FRONTEND_URL` and `NEXT_PUBLIC_API_BASE_URL`. Next.js public variables are exposed to the browser; never put secrets in them. They are supplied at development startup; future production builds must configure them at build time. Outside Docker, Next.js reads `frontend/.env.local`, while backend reads root `.env`; shell environment variables take precedence.

## Run services individually

Start infrastructure from the root:

```sh
docker compose up -d --wait postgres redis
```

Backend, in another terminal:

```sh
cd backend
uv sync --locked
uv run --locked uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```sh
cd frontend
cp .env.local.example .env.local
npm ci
npm run dev
```

If overriding `API_V1_PREFIX` outside Compose, also set `NEXT_PUBLIC_API_V1_PREFIX` in `frontend/.env.local`. Run the database migration flow below for domain persistence. Health endpoints remain independent of migration/seed data.

## Database migrations and verification

With the stack running:

```sh
docker compose exec backend uv run --locked alembic upgrade head
docker compose exec backend uv run --locked python -m app.db.seed
docker compose exec backend uv run --locked python -m app.db.verify
docker compose exec backend uv run --locked alembic current --check-heads
docker compose exec backend uv run --locked alembic check
```

From `backend/` with host-reachable PostgreSQL, use the same `uv run --locked ...` commands directly. Migrations run explicitly, never on API startup. Seed is deterministic, development/test only, repeatable, and does not overwrite existing rows. It creates a four-node synthetic square and persistence fixtures, including a manually authored saved path; it does not compute a route or predict flooding.

Fresh-storage database verification uses a separate Compose project with tmpfs storage and no host ports:

```sh
docker compose -f docker-compose.database-test.yml up -d --wait postgres-test
docker compose -f docker-compose.database-test.yml run --rm --build database-check
docker compose -f docker-compose.database-test.yml down
```

Tests create random disposable databases, test upgrade/downgrade/upgrade, constraints and spatial queries, and drop only those databases. The test role needs CREATEDB and PostGIS-extension privileges. The development database volume is never mounted into this test stack. See [database.md](docs/database.md) for every table/index, spatial units, deduplication, deletes and retention decisions.

## Health checks

| URL on port 8000 | Meaning | HTTP behavior |
| --- | --- | --- |
| `/health` | Service metadata only | 200 while process responds; no dependency assurance |
| `/health/live` and `/api/v1/health/live` | Process liveness | 200; no network/DB calls |
| `/api/v1/health` and `/api/v1/health/ready` | Concurrent PostgreSQL/PostGIS and Redis checks | 200 if required dependencies pass, 503 otherwise |

Readiness executes `SELECT 1`, `SELECT PostGIS_Version()` and Redis PING. Database/PostGIS failure is unavailable/503. Redis failure is degraded/503 by default, or degraded/200 with `REDIS_REQUIRED=false`. Connection failures produce sanitized component messages; no hostnames, URLs or credentials are returned. Startup logs dependency results without preventing the liveness endpoint from running; engines and Redis clients are closed at shutdown. All responses have an `X-Request-ID`; API errors use the Phase 0 Problem Details shape.

The frontend polls readiness every 30 seconds, times out requests, and supports manual retry. HTTP 503 is parsed as a dependency-health result. A responding API can be Healthy while PostgreSQL or Redis is Unavailable and overall readiness fails. Missing PostGIS displays PostgreSQL as Degraded. Connectivity status does not assess flood conditions.

Verify infrastructure directly:

```sh
docker compose exec postgres psql -U floodguard -d floodguard -c 'SELECT PostGIS_Version();'
docker compose exec redis redis-cli ping
python3 scripts/smoke_test.py
```

Use your configured database user/name if changed. The smoke script checks HTTP, CORS, dependency readiness, Swagger and Next.js HTML; it is not a substitute for a browser test.

## Testing and code quality

After the locked local installs, run the core suite from the root:

```sh
sh scripts/check.sh
```

Individual backend commands:

```sh
cd backend
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q -m 'not integration'
uv run --locked ruff format .
```

Unit tests mock infrastructure only at explicit boundaries. Live integration tests are opt-in; unavailable infrastructure fails them when selected, rather than pretending connectivity passed:

```sh
cd backend
RUN_INTEGRATION_TESTS=1 uv run --locked pytest -q -m integration
```

With the complete Compose stack running, the equivalent backend commands require no host Python/uv:

```sh
docker compose exec backend uv run --locked ruff check .
docker compose exec backend uv run --locked pytest -q -m 'not integration'
docker compose exec -e RUN_INTEGRATION_TESTS=1 backend uv run --locked pytest -q -m integration
```

Frontend commands:

```sh
cd frontend
npm run lint
npm run type-check
npm test
npm run format:check
npm run format
npm run build
```

Use `docker compose exec frontend npm test` or replace `npm test` with other npm scripts for container execution. Vitest/Testing Library cover the main page, healthy/unavailable/degraded dependency states, malformed results and outage recovery. `npm run build` verifies the Next.js application build; Dockerfiles intentionally run development servers, not a production deployment.

## ML Dataset Pipeline (Phase 11)

Build and inspect reproducible ML datasets for flood risk prediction:

```sh
# Generate synthetic dataset from simulator scenarios
PYTHONPATH=ml:backend backend/.venv/bin/python -m floodguard_ml.cli build-synthetic \
  --scenarios NORMAL,MODERATE_RAIN,SEVERE_RAIN,FLASH_FLOOD,RECOVERY \
  --output data/processed/synthetic-v1

# Inspect dataset metadata and quality report
PYTHONPATH=ml:backend backend/.venv/bin/python -m floodguard_ml.cli inspect-dataset \
  --path data/processed/synthetic-v1
```

See [ML dataset architecture](docs/ml-dataset.md) and [Phase 11 verification](docs/phase-11-verification.md).

## ML Flood Prediction Models (Phase 12)

Train, evaluate, and benchmark flood prediction models (Rule-Based, Logistic Regression, XGBoost):

```sh
# Train and save XGBoost model artifacts
PYTHONPATH=ml:backend backend/.venv/bin/python ml/floodguard_ml/cli.py train \
  --dataset data/processed/synthetic-v1 \
  --model xgboost \
  --output ml/artifacts \
  --min-recall 0.70

# Side-by-side benchmarking of all models with latency profiling
PYTHONPATH=ml:backend backend/.venv/bin/python ml/floodguard_ml/cli.py compare-models \
  --dataset data/processed/synthetic-v1 \
  --output ml/artifacts
```

> **Note**: All current models are trained on synthetic simulation datasets (`SYNTHETIC DATASET EVALUATION`). Real historical dataset training is blocked pending PostGIS historical archive ingestion.

See [ML model architecture](docs/ml-model.md), [Model Card v1](docs/model-card-v1.md), and [Phase 12 verification](docs/phase-12-verification.md).

## ML Integration with Routing (Phase 13)

Integrate trained ML flood predictions into FloodGuard's real-time risk engine and A*/Dijkstra routing pipeline:

- **Safety Invariant**: $R_{\text{fused}} \ge R_{\text{deterministic}}$ (ML can never downgrade physical risk).
- **Graceful Fallback**: Automatic degradation to deterministic routing on inference timeout or error.
- **Batch Precomputation**: Predictions computed prior to graph search ($O(1)$ Dijkstra/A* relaxation lookup).
- **Zero Skew**: Online feature generation via shared Phase 11 feature generators.
- **Redis Caching**: Revision-isolated edge predictions (`ml_prediction_cache_key`).

```sh
# Benchmark Redis ML and route caching performance
PYTHONPATH=backend:ml backend/.venv/bin/python scripts/benchmark_cache.py
```

See [ML inference architecture](docs/ml-inference.md) and [Phase 13 verification](docs/phase-13-verification.md).

## Troubleshooting

- **Database connection refused:** start postgres, inspect `docker compose ps` and `docker compose logs postgres`. Use `postgres` in containers and `localhost` for host processes. Changes to PostgreSQL initialization credentials do not alter an existing volume's accounts; use existing credentials or intentionally reset only disposable data.
- **Missing PostGIS:** check the configured image and `SELECT PostGIS_Version()`. Initialization SQL runs only on a fresh volume; an existing database may need an operator to enable the extension. Do not create domain tables as a workaround.
- **Redis unavailable:** inspect `docker compose logs redis`, run `redis-cli ping`, verify the URL and restart Redis. Readiness should report degraded instead of hiding the failure.
- **Port conflict:** change published ports in `.env`, then synchronize browser API URL/CORS origin. Do not stop unrelated services to reclaim a port.
- **Browser fetch/CORS failure:** the configured origin must match exactly, including port and `localhost` versus `127.0.0.1`. Inspect the actual request URL. Restart frontend after changing public environment variables.
- **Settings validation fails:** root `.env` does not override shell exports for the same key. Use the namespaced `APP_DEBUG` boolean from the example to avoid host-shell `DEBUG` conflicts. Compose passes `APP_DEBUG`; generic `DEBUG` is a backend fallback only.
- **`docker compose` missing on Homebrew:** install/use the Compose plugin and configure `cliPluginsExtraDirs` to include Homebrew's Docker CLI-plugin directory, or use `docker-compose` if available. Docker Desktop needs no such configuration. Verification used a temporary Docker config pointing at `/opt/homebrew/lib/docker/cli-plugins`; no global settings were changed.
- **PostGIS exec-format error on Apple Silicon:** enable amd64 emulation in your Docker runtime; the pinned official PostGIS image is amd64. An alternative multiarch image needs explicit review and verification before changing `POSTGIS_PLATFORM`.
- **Dependency lock mismatch:** intentional updates use `uv lock` or `npm install`; normal startup uses locked installs. Commit the updated lockfile with the manifest. First builds require registry network access.

## Current limitations

This is a development environment with placeholder credentials and reload servers. It is not hardened for public deployment. Routing/maps, auth, ML and AWS remain later-phase work. See [Phase 1 verification](docs/phase-1-verification.md) for the original environment evidence and unresolved dependency warnings, and [Phase 2 verification](docs/phase-2-verification.md) for database checks.

On the execution host, the stack and desktop/mobile browser checks passed inside Docker, but host localhost forwarding did not work. Repair the Docker runtime's host forwarding and rerun the smoke script before treating this machine's startup experience as complete. Host Turbopack builds were also restricted; the application build passed inside Docker. Preview the verified dashboard: [desktop](docs/assets/phase-1-desktop.png), [mobile](docs/assets/phase-1-mobile.png).

## SQS Asynchronous Event Processing (Phases 14, 15, 16)

FloodGuard utilizes AWS SQS and EventBridge for asynchronous, event-driven domain processing:

* **High Throughput Standard Queues**: Ingestion of environmental telemetry (`environment.weather_observed`, `sensor.water_depth`).
* **EventBridge Fan-Out**: Domain events published to SQS and routed to domain handlers.
* **Failure Recovery**: Dead-Letter Queues (DLQ), exponential backoff, and idempotency lock release.
* **Operator CLI**: Embedded CLI for managing DLQ quarantined messages (`inspect`, `dry-run`, `replay`).

```sh
# Run SQS Consumer Worker
PYTHONPATH=backend backend/.venv/bin/python -m app.messaging.worker --queue-url "https://sqs.us-east-1.amazonaws.com/123/floodguard-events"

# Inspect the DLQ for poisoned messages
PYTHONPATH=backend backend/.venv/bin/python -m app.messaging.dlq inspect --dlq "https://sqs.us-east-1.amazonaws.com/123/floodguard-events-dlq"
```

See [SQS documentation](docs/sqs.md), [EventBridge documentation](docs/eventbridge.md), and [Failure Recovery documentation](docs/failure-recovery.md).

## S3 Data & Model Artifact Storage (Phase 17)

FloodGuard utilizes S3-compatible storage for artifacts such as ML datasets and model bundles:
- **Modularity:** Unified `ArtifactStore` with local filesystem and S3 implementations.
- **Checksums:** SHA-256 validation applied on upload and fetch.
- **Commands:** CLI support for publishing/fetching ML models and datasets (`publish-dataset`, `fetch-model`, etc.).
- **Runtime Sync:** Backend loader syncs model from S3 into local cache upon startup, gracefully falling back if unavailable.

See [Phase 17 documentation](docs/artifact-storage.md) and [Phase 17 verification](docs/phase-17-verification.md).
Phase 18 added AI Assistant.

- [x] Phase 19: Incident Reporting, Verification & Trust Scoring

## Infrastructure validation
FloodGuard's cloud deployment is managed via Terraform. See `docs/infrastructure-as-code.md` for full architectural details.

To validate the infrastructure setup (e.g., in a development context):
```bash
cd infra/terraform/environments/dev
terraform init
terraform fmt -check -recursive ../../
terraform validate
# Planning requires AWS credentials:
# terraform plan
```

## CI/CD Pipeline & Automated Deployment (Phase 28)
FloodGuard is integrated with GitHub Actions for automated Quality Gates, Image Building, Vulnerability Scanning, Terraform Validation, and Development Deployment.

To trigger the workflows locally (if using `act`) or simply run the quality gate:
```sh
# Run fast quality gate locally
./scripts/quality_gate.sh fast

# Trigger development deployment manually in GitHub Actions by running the 'Deploy to Development' workflow.
```
See [CI/CD Pipeline Architecture](docs/cicd.md) and [Phase 28 Verification](docs/phase-28-verification.md).

## Production Readiness Review (Phase 29)
Before promoting the system, FloodGuard enforces strict readiness gates encompassing code quality, supply chain security, live deployment verification, and operational recovery. 

See the following Phase 29 compliance reports:
- [Master Release Readiness Matrix](docs/release-readiness-matrix.md)
- [Release Blockers Register](docs/release-blockers.md)
- [Production Readiness Guidelines](docs/production-readiness.md)
- [Phase 29 Verification](docs/phase-29-verification.md)
