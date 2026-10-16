# Phase 1 verification

Recorded 7 October 2026. Scope: monorepo, local infrastructure/connectivity, health dashboard, configuration, logging/errors and basic tests. No Phase 2 domain models or later functionality was implemented.

## Status

**PARTIAL: implementation and Docker-network verification pass; this execution host's localhost forwarding remains unavailable.** All four services have run healthy, and a browser inside the Docker VM reached the actual frontend/API. Host requests to `localhost:3000`/`:8000` were refused. That prevents claiming the required host startup experience is fully verified here.

## Environment and decisions

- Backend: Python 3.13, FastAPI factory, Pydantic settings, async SQLAlchemy 2.0/asyncpg and async Redis. uv locks all dependencies in `backend/uv.lock`; Docker installs with `uv sync --locked`.
- Frontend: Next.js 16.4.0, React 19.3.0, strict TypeScript, Tailwind 4.3.3, npm lockfile, Vitest/Testing Library. Docker installs with `npm ci`.
- Images are pinned to observed registry digests. Official PostgreSQL 17/PostGIS 3.5 runs with amd64 emulation on the arm64 Docker VM. Database initialization creates the extension only.
- Readiness requires PostgreSQL, PostGIS and Redis by default. Optional Redis mode is explicit, tested, and returns degraded rather than healthy. Liveness has no dependency calls.
- PostgreSQL has a persistent volume. Redis persistence is disabled because Phase 1 has no cache/business data.
- Browser requests use the host API URL; container connections use service names. All host port bindings are loopback-only. CORS permits the exact configured frontend origin, without credentials/wildcards.
- JSON application logs expose event/request IDs and failure classes, not connection strings. API errors use sanitized Problem Details. `APP_DEBUG` is preferred; `DEBUG` is a legacy fallback only when no namespaced value is configured.

## Commands actually executed

The host has a running Docker daemon socket but `docker compose` was initially undiscovered. Its installed Homebrew plugin was enabled through a temporary config, without changing global settings. **Every Docker command below used this exact prefix:**

```text
docker --config /private/tmp/floodguard-phase1-docker --host unix:///Users/vikaskumar0205/.colima/default/docker.sock
```

The tables list the remaining actual arguments, rather than claiming unprefixed commands worked on this host.

| Directory | Actual command or Docker arguments | Outcome |
| --- | --- | --- |
| Root | `cp .env.example .env` | Local ignored configuration created |
| Backend | `UV_CACHE_DIR=/private/tmp/floodguard-uv-cache UV_PYTHON_INSTALL_DIR=/private/tmp/floodguard-python /private/tmp/floodguard-phase1-tools/bin/uv sync --python 3.13` | Lock generated; 35 packages installed |
| Frontend | `npm install --cache /private/tmp/floodguard-npm-cache --fetch-retries=1 --fetch-timeout=20000` | npm lock generated and dependencies installed |
| Backend | `.venv/bin/ruff format .` | Passed after formatting |
| Backend | `.venv/bin/ruff check .` | Passed |
| Backend | `.venv/bin/pytest -q -m 'not integration' --tb=short` | 31 passed, 3 deselected |
| Frontend | `npm run format` and `npm run format:check` | Passed |
| Frontend | `npm run lint` | Passed, zero warnings after config correction |
| Frontend | `npm run type-check` | Passed |
| Frontend | `npm test` | 8 passed across 2 files |
| Root | `PATH=/private/tmp/floodguard-phase1-tools/bin:$PATH UV_CACHE_DIR=/private/tmp/floodguard-uv-cache sh scripts/check.sh` | Complete core check command passed |
| Docker | `compose config --quiet` | Passed |
| Docker | `compose pull postgres redis` | Passed |
| Docker | `compose build` | Both images built; repeated after final digest pins |
| Docker | `compose up --build -d --wait --wait-timeout 180` | All four containers healthy on initial startup |
| Docker | `compose exec -e RUN_INTEGRATION_TESTS=1 backend uv run --locked pytest -q -m integration` | 3 passed, 31 deselected |
| Docker | `compose exec -e RUN_INTEGRATION_TESTS=1 backend uv run --locked pytest -q` | Final post-recovery full backend run: 34 passed, 1 deprecation warning |
| Docker | `compose exec postgres psql -U floodguard -d floodguard -c 'SELECT PostGIS_Version();'` | Returned `3.5 USE_GEOS=1 USE_PROJ=1 USE_STATS=1` |
| Docker | `compose exec redis redis-cli ping` | `PONG` |
| Docker | `compose exec backend uv run --locked ruff check .` | Passed |
| Docker | `compose exec frontend npm run lint` | Passed |
| Docker | `compose exec frontend npm run type-check` | Passed |
| Docker | `compose exec frontend npm test` | 8 passed |
| Docker | `compose run --rm --no-deps frontend npm run build` | Next.js optimized build and TypeScript passed |
| Docker | `compose up -d --wait --wait-timeout 90` | Final post-cleanup startup: all four services healthy |
| Root | `python3 scripts/smoke_test.py` | Sandbox denied localhost initially; escalated retry got connection refused |
| Docker | `compose exec -T backend python - --api-url http://backend:8000 --frontend-url http://frontend:3000 --origin http://localhost:3000 < scripts/smoke_test.py` | Eight smoke groups passed inside Docker network |
| Frontend | `npm audit --json --cache /private/tmp/floodguard-npm-cache` | Five high development dependency findings |
| Frontend | `npm audit --omit=dev --json --cache /private/tmp/floodguard-npm-cache` | Zero runtime dependency findings |

The temporary uv installer, registry inspections, diagnostic Docker logs/status and disposable browser commands were additional setup/verification operations. No production services or infrastructure were provisioned.

## Test evidence

| Check | Result and scope |
| --- | --- |
| Backend unit/API/config/connectivity tests | 31 passed; infrastructure mocked only in unit tests |
| Live integration tests | 3 passed against real PostgreSQL/PostGIS and Redis; final combined backend suite passed all 34 tests after recovery |
| Frontend tests | 8 passed: main page, cards, dependency failures, malformed health response and retry recovery |
| Core format/lint/type/test command | Passed; integration suite remains explicitly opt-in |
| HTTP smoke | Passed inside Docker: metadata/liveness/readiness, all dependency statuses, configured CORS, Swagger, Next.js page and frontend liveness |
| Desktop browser, 1440×1000 | Actual API fetch, three healthy cards, manual refresh, no horizontal overflow or JavaScript errors |
| Mobile browser, 390×844 | Same checks passed |
| Redis stopped | Readiness 503/degraded, liveness 200 |
| PostgreSQL stopped | Readiness 503/unavailable, liveness 200 |
| Recovery after temporary disk-pressure cleanup | All four services healthy; all 34 backend tests and eight HTTP smoke groups passed again |

Browser checks used temporary Playwright 1.63.0 tooling and a disposable browser container sharing the Docker VM's network. They are additional Phase 1 verification, not a new repository E2E framework. Screenshots: [desktop](assets/phase-1-desktop.png), [mobile](assets/phase-1-mobile.png).

## Failures and limitations

1. **Host forwarding:** host curl/urllib and a host browser could not reach the published localhost ports. Docker inspection showed loopback bindings; Docker-network HTTP and browser requests passed. `colima status` reported not running while the socket daemon identified itself as Colima. No global runtime restart, unrelated container stop, permissive host binding or persistent port proxy was performed. Repair host runtime forwarding and rerun `python3 scripts/smoke_test.py` plus a host-browser check before marking Phase 1 COMPLETE on this machine.
2. **Host build sandbox:** `npm run build` failed on this host with Turbopack's local CSS-worker port creation denied, including the escalated retry. The exact same application build passed in a disposable Docker container. This is recorded as a host execution limitation, not a successful host build.
3. **Development dependency audit:** the five high findings stem from `braces` through the Next.js ESLint configuration chain. The [published advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists no patched version at verification time; registry inspection returned 3.0.3. Runtime-only audit was clean. Do not feed untrusted patterns to lint tooling; track an upstream patch rather than force-downgrade the Next.js lint configuration.
4. **Lint compatibility:** ESLint 9.39.5 is end-of-life according to [the project's support policy](https://eslint.org/version-support/). The installed React lint plugin declares compatibility through ESLint 9, so ESLint 10 was not forced across an unsupported peer boundary. Upgrade the compatible lint dependency set when available.
5. **Test-client warning:** passing backend tests emit Starlette's deprecation warning for the httpx-based test client. No warning was suppressed or counted as a failure.
6. **Temporary disk pressure:** downloading the disposable browser image filled the Docker VM disk and interrupted PostgreSQL restart during the outage recovery check. The browser container/image were removed; application data volumes and unrelated images were preserved. Disk usage inspection then showed available space and PostgreSQL recovered. After cleanup all four services passed their health checks, all 34 backend tests passed, and all eight HTTP smoke groups passed. Avoid downloading large verification images without checking available Docker storage first.

## Acceptance record

The required conditions are evaluated against actual executed checks. Host URL reachability is tracked separately because it is also part of the requested startup experience.

| Condition | Result |
| --- | --- |
| Next.js application starts | PASS in Docker |
| TypeScript strict mode enabled | PASS |
| FastAPI application starts | PASS in Docker |
| PostgreSQL container starts | PASS; real PostGIS queries executed |
| PostGIS extension works | PASS |
| Redis starts | PASS |
| FastAPI connects to PostgreSQL | PASS live integration |
| FastAPI connects to Redis | PASS live integration |
| `/health` works | PASS Docker-network HTTP |
| `/api/v1/health/live` works | PASS Docker-network HTTP and unit tests |
| `/api/v1/health/ready` correctly reports dependency health | PASS healthy and live outage states |
| Frontend displays backend/system health | PASS real desktop/mobile browsers inside Docker |
| Docker Compose starts complete stack | PASS initial and final post-recovery all-service health waits |
| `.env.example` exists | PASS |
| No actual secrets committed | PASS: development placeholders only, env files ignored; no git commits created |
| Backend tests pass | PASS: 31 unit/API plus 3 live integration |
| Required frontend tests pass | PASS: 8 |
| Frontend lint/type-check pass | PASS |
| README contains reproducible startup instructions | PASS: commands and runtime prerequisites documented |
| This host can open the required localhost URLs | FAIL: unresolved runtime forwarding |

## Next phase boundary

Phase 2 — Database and PostGIS Foundation. No Phase 2 work was started.
