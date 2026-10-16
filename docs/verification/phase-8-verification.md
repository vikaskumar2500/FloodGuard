# Phase 8 verification

Verified on 2026-10-07 using the end-to-end automated Chrome DevTools Protocol pipeline, running FastAPI with `FloodGuardRuntime`, live Next.js UI on `http://127.0.0.1:3000`, and the `FLASH_FLOOD` scenario simulator.

## End-to-end live flow metrics

| Measurement | Result |
|---|---|
| Initial calculated route | `A → B → C → D` (top corridor, 0.3 km, 3 min ETA, LOW risk 0.0) |
| Active SSE stream | `GET /api/v1/routes/{route_id}/events` established (`text/event-stream`, 200 OK) |
| Environmental trigger | `FLASH_FLOOD` scenario emitted via `POST /api/v1/dev/simulation/events` |
| Affected road edges | `fixture-top-1`, `fixture-top-2`, `fixture-top-3` identified by edge index |
| Invalidation event | `route.invalidated` emitted (risk evaluated to HIGH / 0.51 > 0.3 threshold) |
| Real-time transition | `route.rerouting` emitted (status banner: "Finding a safer route…") |
| Single-flight lock | Exactly 1 A* recalculation initiated during simulation |
| Replacement route | `A → E → F → D` (bottom corridor, 0.6 km, 4 min ETA, LOW risk 0.0) |
| Recalculation payload | `route.recalculated` with complete geometry, riskSegments, and comparison metrics |
| Browser reaction | Zero manual clicks; EventSource received event and switched active subscription |
| UI route comparison | `Route updated due to flood risk` (Old: 3 min · HIGH, New: 4 min · LOW, +30 sec, Risk reduced by 0.51) |
| MapLibre presentation | Previous flooded route preserved as muted dashed line (`#64748b`); new route rendered solid |
| Route TTL & Expiration | Stale routes purged from index; streams terminate cleanly; reconnects return 404 |

## Verified test counts

| Component | Test Suite | Result |
|---|---|---|
| Backend | `pytest` (unit & lifecycle) | **69 passed**, 50 skipped (PostGIS integration) |
| Simulator | `pytest ../simulations/tests/test_simulator.py` | **7 passed** |
| Frontend | `vitest run --run` | **23 passed across 7 files** |
| Real Browser CDP | `scripts/verify_browser_flow.py` | **PASS** (Zero manual clicks, full SSE event pipeline) |

## Artifacts

- Browser initial state: `docs/assets/phase-8-route-initial.png`
- Verified log output: `docs/assets/phase-8-verification.log`

