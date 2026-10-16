# Phase 2 verification

Recorded 7 October 2026. Scope: SQLAlchemy/PostGIS models, reviewed async Alembic migration, deterministic synthetic seed, focused repositories, schema/spatial verification and regression checks. No routing algorithm, map, domain API, risk engine, ML inference, event bus, authentication or AWS work was added.

## Executed results

| Check | Result |
| --- | --- |
| Backend Ruff format and lint | Passed; 35 files formatted, no lint errors |
| Backend unit/API suite | 31 passed, 48 integration tests deselected |
| Disposable real-PostGIS database suite | 45 passed |
| Complete backend suite against development PostgreSQL/PostGIS and Redis | 79 passed: 31 unit/API plus 48 integration |
| Frontend Vitest | 8 passed in 2 files |
| Frontend Prettier, ESLint and strict TypeScript | Passed |
| Main and disposable Compose configuration | `docker compose ... config --quiet` passed |
| Backend image rebuild with locked Alembic/GeoAlchemy dependencies | Passed |
| Complete Compose stack startup/wait | PostgreSQL, Redis, backend and frontend healthy |
| Development migration | Upgraded from base to `0001_database_foundation` |
| First development seed | Inserted 23 deterministic rows |
| Second development seed | Inserted zero rows in every table |
| Development verifier | Passed: PostGIS 3.5, revision at head, 12 tables, 11 spatial columns, 94 constraints and 25 explicit secondary indexes |
| Migration round trip | On database created from `template0`: upgrade, seed/verify, downgrade base, verify removal, upgrade, drift check, seed/verify passed |

The passing backend suite still emits the existing Starlette test-client deprecation warning. It is not hidden or counted as a failure.

## Migration isolation and reversibility

The migration round-trip ran against random databases named `floodguard_test_<uuid>` created by the test process inside the dedicated `floodguard-dbcheck` Compose project. Its PostgreSQL data directory is tmpfs and it does not mount the development `postgres_data` volume. Each database was dropped by the creating test after engine disposal. The existing development volume was never removed.

The test started from `template0` and confirmed PostGIS was absent before `alembic upgrade head`. Upgrade installed only `postgis` in addition to built-in `plpgsql`. It then created all application objects, seeded and verified them. Downgrade removed all application tables and the `floodguard_set_updated_at` function while deliberately retaining PostGIS. A second upgrade, Alembic schema-drift check and verification succeeded.

## Seed evidence

The first development run inserted:

| Table | Rows |
| --- | ---: |
| `users` | 1 |
| `regions` | 1 |
| `graph_versions` | 1 |
| `road_nodes` | 4 |
| `road_edges` | 8 |
| `flood_zones` | 1 |
| `sensor_events` | 1 |
| `weather_observations` | 1 |
| `flood_predictions` | 1 |
| `incidents` | 1 |
| `routes` | 1 |
| `route_segments` | 2 |

The second run reported zero inserted rows for all tables. Fixed UUIDv5 identities, a transaction-level advisory lock and `ON CONFLICT` on each reserved primary key make the fixture safely repeatable without overwriting data. The fixture represents four nodes A/B/C/D, eight separately directed edges and a manually authored A→B→D saved calculation with segment sequences 0 and 1. PostGIS computed edge meters. This is persistence data, not routing or prediction output.

## Spatial evidence

The verifier and tests executed real PostGIS operations:

- `PostGIS_Version()` returned `3.5 USE_GEOS=1 USE_PROJ=1 USE_STATS=1`.
- Catalog queries checked the declared typmod type and SRID 4326 for all 11 spatial columns.
- `ST_DWithin(location::geography, point::geography, 150)` returned the expected three nearby nodes.
- `ST_Distance` ordered bounded nearest-node candidates with deterministic UUID tie-breaking.
- `ST_Intersects` found the seeded flood zone for edge A→B.
- `ST_Covers` confirmed the seeded point lies within the zone.
- `ST_Length(geography)` produced edge lengths in meters during seed creation.
- Wrong SRID, out-of-range point, empty geometry, invalid polygon and unsupported prediction LineString cases were rejected.
- Prediction targets accepted both Point and MultiPolygon geometry, as well as edge-only association.

`EXPLAIN (ANALYZE, BUFFERS)` used `ix_road_nodes_location_geography` for the meter-radius query in the natural plan and in an index-eligibility plan. The natural fixture execution returned three rows. This is structural/query evidence only; 4 nodes cannot support a performance claim.

## Constraints exercised

Integration tests intentionally caused PostgreSQL to reject:

- probabilities, confidence and risk scores outside `[0,1]`, including probability NaN;
- negative or infinite distance, negative travel time, depth, rain and wind;
- nonpositive speed, forecast horizon and invalid segment sequence;
- humidity above 100;
- invalid temporal ordering for zone validity, route/prediction expiry and incident verification;
- invalid user role, non-normalized email and duplicate email;
- invalid incident status;
- duplicate graph-scoped OSM node identity and graph/way/segment/direction edge identity;
- partial OSM edge identity;
- duplicate `(route_id, sequence)`;
- duplicate sensor `(producer, external_event_id)` and weather `(provider, external_id)`;
- missing source/target node, cross-graph node/edge and route/segment associations;
- self-loop edge, missing prediction target and incompatible prediction geometry;
- deleting referenced nodes/edges.

Tests also confirmed route deletion cascades to its segments, user deletion nulls route/incident ownership, referenced topology remains restricted, raw SQL updates advance database-managed `updated_at`, and nullable/non-OSM nodes insert successfully.

## Phase 1 regression

The full Docker stack returned healthy after the backend image rebuild. The combined integration suite passed live PostgreSQL/PostGIS, Redis and API readiness tests. Health endpoints remain seed-independent: their implementation still checks only PostgreSQL connectivity, PostGIS availability and Redis according to the existing Phase 1 contract. Frontend behavior and all eight frontend tests passed. No CRUD/domain routes were added, so Swagger remains focused on health endpoints.

The pre-existing macOS/Colima localhost-forwarding debt remains unchanged. Docker-network checks and service health work; this phase did not restart or reconfigure the host runtime.

## Environment note

One final redundant Docker command was not executed because automatic approval review hit the account usage limit. It was intended only to repeat `alembic upgrade head` against the already-migrated disposable service. This does not change the recorded migration result: the isolated 45-test suite had already completed the full upgrade → downgrade → upgrade cycle, and the development migration, seed, verifier, full 79-test suite and healthy-stack checks had all completed successfully.
