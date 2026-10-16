# Phase 25 Verification

## Goal
Verify the implementation of Phase 25 (Production Container Hardening), ensuring images are secured, optimized, and start correctly in a production-like compose environment without dev mounts.

## Checks Performed

### Dockerfiles
- [x] Backend `Dockerfile.prod` uses multi-stage builds.
- [x] Frontend `Dockerfile.prod` uses Next.js `output: "standalone"`.
- [x] Both backend and frontend run as non-root (`appuser`, `nextjs`).
- [x] Backend uses `uv sync --locked --no-dev`.
- [x] Base images are pinned to digest and slim tags.

### Compose File
- [x] `docker-compose.prod.yml` uses explicit resources (`limits: cpus, memory`).
- [x] Local volume mounts for application code have been removed in `docker-compose.prod.yml`.
- [x] Proper `healthcheck` configurations ensure services wait for dependencies.

### Ignored Files
- [x] `.dockerignore` excludes `node_modules`, `.next`, `.venv`, and `tests/` directories.

### Build and Run Measurements
- **Build**: Encountered `no space left on device` on the local Docker daemon while installing large Python dependencies (e.g. `nvidia-nccl-cu13`) during `uv sync` and npm dependencies. Build measurements are marked as `BLOCKED`.
- **Image Sizes**: Expected ~200-300MB for both images due to multi-stage stripping, but exact metric is `BLOCKED` due to environment disk constraints.

### Vulnerability Scans & SBOM
- Scanning tools (`trivy` and `docker scout`) were unavailable in the environment. Marked as `BLOCKED`.

### Graceful Shutdown
- Backend gracefully handles SIGINT/SIGTERM passed through `uvicorn` and shuts down SQS consumers, EventBridge, Redis, and Postgres connections cleanly as defined in `app.main.lifespan`.

### Quality Gate
- [x] `./scripts/quality_gate.sh fast` succeeds locally, ensuring dev tooling remains pristine.

