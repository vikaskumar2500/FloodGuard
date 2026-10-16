# Phase 5 verification

## Automated checks

- Routing algorithm tests: 6 passed.
- Phase 4 ingestion tests: 4 passed.
- Route API unit tests: 2 passed.
- Backend non-integration suite: 43 passed, 50 integration tests deselected.
- Frontend suite: 21 passed.
- Backend Ruff lint and formatting: passed.
- Frontend strict TypeScript, ESLint, formatting, and build: passed.

## Benchmark

The fixture benchmark is `backend/scripts/benchmark_routing.py` and runs 20 iterations per algorithm over the same in-memory fixture graph. Execute it with:

```sh
cd backend
uv run --locked python -m scripts.benchmark_routing
```

Measured on the local Python 3.13 environment:

| Graph | Algorithm | Cost (s) | Expanded nodes | Median time (ms) | Runs |
| --- | --- | ---: | ---: | ---: | ---: |
| tiny fixture (8 nodes, 12 edges) | Dijkstra | 63.3811957270 | 6 | 0.0123125 | 20 |
| tiny fixture (8 nodes, 12 edges) | A* | 63.3811957270 | 6 | 0.0181670 | 20 |

Both algorithms found the same route and equal cost. A* did not expand fewer nodes on this tiny graph; no performance advantage is claimed.

## Database and real graph status

The PostGIS/Redis integration attempt produced 4 failed infrastructure checks and 46 database setup errors because PostgreSQL was unreachable on `localhost:5432` and Redis was unavailable. No real regional OSM graph was available or persisted. Phase 4's real-persistence and real-region debt therefore remains open.

The Phase 5 route persistence test is present in the integration suite and covers graph-version filtering, spatial geometry, route rows, ordered segments, and nullable risk fields when infrastructure is available.
