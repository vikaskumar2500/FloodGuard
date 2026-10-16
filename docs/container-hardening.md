# Container Hardening

## Overview
Phase 25 focused on production container hardening for the FloodGuard application. This includes creating optimized Dockerfiles and ensuring the development workflow remains untouched.

## Security Improvements
- **Non-root Users**: Both backend and frontend containers now run as dedicated non-root users (`appuser` and `nextjs`).
- **Base Images**: Base images are pinned to specific digest SHAs and slim distributions (e.g., `python:3.13-slim-bookworm` and `node:24-bookworm-slim`) to minimize surface area.
- **Dependency Locking**: The backend uses `uv sync --locked --no-dev` to ensure reproducible builds without installing development tools.
- **Dockerignore**: Comprehensive `.dockerignore` files prevent local environment variables, caches, logs, and development artifacts from being copied into the images.

## Performance and Size Reductions
- **Multi-stage Builds**: Both frontend and backend utilize multi-stage builds.
  - The backend separates `uv` dependencies out of the final runtime.
  - The frontend uses Next.js `output: "standalone"` to strip out unused Node.js modules from the final image.
- **Image Size Improvements**: The frontend image size was drastically reduced by using the standalone mode, and the backend utilizes `uv` without dev dependencies.

## Lifecycle Management
- **Graceful Shutdown**: The backend `Dockerfile.prod` utilizes an un-shellified `CMD ["uvicorn", ...]` so that standard POSIX signals (SIGINT/SIGTERM) pass directly to the process, allowing existing cleanup routines for Redis, PostgreSQL, SQS, and EventBridge to run smoothly.
- **Resource Constraints**: The `docker-compose.prod.yml` defines CPU and memory limits for all services to ensure fair resource allocation and avoid container-OOM cascading failures.

## Health Checks
- Production compose services depend strictly on healthchecks. The backend healthcheck verifies readiness rather than just liveness.

## Vulnerability Scans
- Tooling for `trivy` / `docker scout` was not available in this environment. Scans and SBOM generation are marked as **BLOCKED** and should be configured in the CI pipeline.

## Future Recommendations
- Implement continuous vulnerability scanning (e.g., Trivy or Grype) on every push to the default branch.
- Consider Distroless or Chainguard images for further security.

