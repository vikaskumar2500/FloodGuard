# Phase 6 verification

## Automated results

- Risk-engine tests: 6 passed.
- Phase 5 routing tests: 7 passed.
- Route API tests: 2 passed.
- Phase 4 ingestion tests: 4 passed.
- Backend non-integration suite: 50 passed; 50 integration tests deselected.
- Frontend tests: 21 passed.
- Backend Ruff lint and formatting: passed.
- Frontend type-check, lint, formatting, and build: passed.

## Deterministic route fixture

The synthetic risk graph has a short top corridor `A -> B -> C -> D` and a slower lower corridor `A -> E -> F -> D`. Severe active flood-zone evidence is associated with the top corridor.

The critical test uses an explicit balanced penalty of 1 second per unit risk:

| Mode | Path | Baseline ETA | Risk |
| --- | --- | ---: | ---: |
| FASTEST | A -> B -> C -> D | 3 s | 0.75, HIGH |
| BALANCED | A -> B -> C -> D | 3 s | 0.75, HIGH |
| SAFEST | A -> E -> F -> D | 6 s | 0.00, LOW, confidence 0 |

The default service configuration uses a larger balanced penalty of 120 seconds and a safest penalty of 900 seconds. It is intentionally configurable rather than embedded in A* or Dijkstra.

## Infrastructure

The real PostGIS/Redis integration suite remains unavailable. The previous integration attempt produced 4 infrastructure failures and 46 database setup errors because PostgreSQL was unreachable on `localhost:5432` and Redis was unavailable. No real regional graph or live evidence scenario was persisted.

Pure scoring, normalization, freshness, missing evidence, no-alternative severe risk, risk-aware costs, and A*/Dijkstra correctness are covered without infrastructure.
