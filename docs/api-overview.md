# FloodGuard API overview

Status: proposed Phase 0 contracts, with current Phase 1 health behavior noted below. Examples are illustrative contract fixtures, not measured routes or weather observations. Use [system-design.md](system-design.md) for orchestration and [events.md](events.md) for async outcomes.

Phase 1 implementation note (7 October 2026): metadata `/health`, liveness `/health/live` and `/api/v1/health/live`, and readiness `/api/v1/health` and `/api/v1/health/ready` are implemented. Current readiness uses `healthy`/`degraded`/`unavailable`, a `ready` boolean and sanitized `dependencies` for postgres/postgis/redis; required dependency failures return 503. Swagger is available at `/docs`, OpenAPI at `/api/v1/openapi.json`. These current contracts supersede the illustrative Phase 0 health example below. All other endpoint rows remain proposed; see [the README](../README.md) for runnable commands.

## Transport and versioning

Phase 2 adds database persistence and operational migration/seed/verification commands only. It adds no domain HTTP endpoints; Swagger and the Phase 1 health contracts remain unchanged. See [database.md](database.md).

Serve HTTPS JSON under `/api/v1`. Keep `/health` as an unversioned deployment probe. Publish a reviewed OpenAPI schema at `/api/v1/openapi.json` and interactive docs at `/api/v1/docs`; access to production documentation can be restricted. Frontend client types derive from the schema in CI.

The URL carries the major contract version. Adding optional response fields or new endpoints can remain v1; removing/renaming fields, changing units/meaning, tightening previously valid inputs or expanding enums consumed exhaustively requires compatibility review and often v2. Keep old and new versions available for a documented migration window, publish deprecation dates and test both. Database schema, event schema, graph, risk policy, feature and model versions are separate and must not be inferred from `/v1`.

Use explicit `{longitude, latitude}` request objects and WGS84 GeoJSON `[longitude, latitude]` responses. Longitude must be finite and within `[-180,180]`, latitude within `[-90,90]`. Physical units appear in names, such as `distance_m`, `eta_seconds`, `water_depth_m`, `rainfall_mm`, `rainfall_mm_per_hour`. Times use RFC 3339 UTC. API bounds on radius, viewport, pagination, body size and route complexity are configuration with published defaults, not unlimited queries.

Propagate `X-Request-ID` and `X-Correlation-ID`, after validation, and return them with errors/responses. Treat client IDs as trace labels, never identities. `Idempotency-Key` is supported for route creation and accepted writes: scope it to actor/session plus method/path, hash the validated body, return the original response for the same body, and return 409 for conflicting reuse. Retain keys for a documented retry window, initially proposed as 24 hours. Sensor source-event deduplication is durable independently of this HTTP retention.

Anonymous public reads/calculations use a scoped session for route ownership. Authenticated mutations use OIDC-issued access JWTs or the server-side browser session, following [architecture.md](architecture.md). Cookie-authenticated writes require CSRF protection. Check authorization in service functions too, so worker/assistant entrypoints cannot bypass it. Administrative roles never come from a client-supplied field.

## Endpoint inventory

Each row identifies its first implementation phase. Later endpoints are contracts for future work, not claims of current availability.

| Method and path | Purpose and response | Access | Phase |
| --- | --- | --- | --- |
| `GET /health` | Liveness: process can answer; 200 | Public minimal body | 1 |
| `GET /api/v1/health` | Bounded PostgreSQL/PostGIS and Redis connectivity checks; 200 ready/degraded, 503 unavailable | Public status only; detailed errors restricted | 1 |
| `GET /api/v1/regions` | Enabled regional coverage, graph/risk status and freshness | Public, paginated | 2–4 |
| `POST /api/v1/routes/calculate` | Create owned route and initial revision; 201 | Anonymous scoped session or USER | 5 |
| `GET /api/v1/routes/{route_id}` | Current revision, status and comparison metadata; 200 | Owner or explicitly authorized operator | 5/8 |
| `GET /api/v1/routes/{route_id}/risk` | Revision risk explanation with evidence/versions; 200 | Route owner | 6 |
| `GET /api/v1/flood-zones?bbox=...` | Bounded/aggregated GeoJSON with snapshot/zone versions; 200 | Public | 6 |
| `GET /api/v1/risk?longitude=...&latitude=...` | Published area/nearby-road assessment, quality and age; 200 | Public | 6 |
| `POST /api/v1/sensor-events` | Validate and persist typed observation; 202 receipt | Device ingestion scope or approved operator | 7 |
| `POST /api/v1/admin/simulations` | Start deterministic scenario job; 202 job | OPERATOR in explicitly enabled demo/staging environment | 7 |
| `GET /api/v1/jobs/{job_id}` | Pending/running/succeeded/failed plus outcome reference; 200 | Owner or authorized operator | 7/8 |
| `GET /api/v1/routes/{route_id}/events` | Owned SSE stream with replay cursor | Route owner | 8 |
| `DELETE /api/v1/routes/{route_id}/subscription` | Stop automatic journey monitoring; 204 | Route owner | 8 |
| `GET /api/v1/weather?longitude=...&latitude=...` | Cached published observations, never hidden stale data; 200 | Public | 10 |
| `POST /api/v1/assistant/messages` | Grounded explanation and tool evidence; 200 | USER or separately quota-limited demo session | 18 |
| `GET /api/v1/incidents?bbox=...` | Bounded incidents, confidence and verification; 200 | Public redacted data | 19 |
| `POST /api/v1/incidents` | Accepted report and verification-pending state; 202 | USER | 19 |
| `POST /api/v1/admin/incidents/{incident_id}/verification` | Commit operator decision/reason; 202 until risk applied | OPERATOR or ADMIN | 19/20 |
| `POST /api/v1/admin/graph-imports` | Stage region import job; 202 | ADMIN | 20; earlier CLI uses operator credentials |
| `POST /api/v1/admin/models/{model_version}/promotion` | Approve compatible manifest and future inference version; 202 | ADMIN | 20/32 |
| `GET /api/v1/admin/operations` | Bounded queue/worker/sensor/model status | OPERATOR or ADMIN | 21/29 |

Do not expose training execution, queue replay, arbitrary SQL or shell execution as public generic endpoints. Use controlled CLI/pipeline operations with audit records. `get_nearby_safe_locations` is an internal tool port until a verified safe-location dataset and endpoint exist.

## Health contract

`GET /health` tests liveness without dependency calls. `GET /api/v1/health` independently checks a bounded DB query, installed PostGIS extension and Redis PING. Return only concise public component statuses. Phase 1 treats missing required DB/Redis connectivity as not ready. From Phase 9 onward, Redis can be configured optional for readiness because cache loss supports fallback; report `degraded` and `redis: unavailable` explicitly.

Production uses `/health` for container liveness and `/api/v1/health` for ALB readiness. Do not restart healthy processes just because an external weather provider or Bedrock is unavailable. Worker readiness additionally checks access to its required queue/database and records last successful progress.

```json
{
  "status": "ready",
  "components": {
    "database": "available",
    "postgis": "available",
    "redis": "available"
  },
  "request_id": "req-fixture"
}
```

## Route calculation

`POST /api/v1/routes/calculate`

```json
{
  "source": {"longitude": 72.8777, "latitude": 19.0760},
  "destination": {"longitude": 72.8900, "latitude": 19.0900},
  "mode": "BALANCED",
  "algorithm": "ASTAR",
  "region_id": "mumbai-demo"
}
```

`source` and `destination` are required; default mode is BALANCED and default algorithm ASTAR. Dijkstra is also available as `DIJKSTRA`. `region_id` is optional only when coordinates map unambiguously to one enabled region. Initially reject cross-region journeys rather than silently assemble disconnected graphs. Origin equal to destination uses a documented zero-distance result after coverage/snap validation; it does not enter graph traversal.

Illustrative 201 response:

```json
{
  "route_id": "11111111-1111-4111-8111-111111111111",
  "revision": 1,
  "status": "ACTIVE",
  "region_id": "mumbai-demo",
  "mode": "BALANCED",
  "algorithm_used": "ASTAR",
  "distance_m": 2300.0,
  "eta_seconds": 420.0,
  "path_geometry": {
    "type": "LineString",
    "coordinates": [[72.8777, 19.0760], [72.8840, 19.0800], [72.8900, 19.0900]]
  },
  "source_snap": {
    "node_id": 101,
    "coordinate": {"longitude": 72.8777, "latitude": 19.0760},
    "offset_m": 0.0
  },
  "destination_snap": {
    "node_id": 205,
    "coordinate": {"longitude": 72.8900, "latitude": 19.0900},
    "offset_m": 0.0
  },
  "risk": {
    "length_weighted_score": 0.18,
    "maximum_edge_score": 0.31,
    "high_risk_length_m": 0.0,
    "assessment_method": "DETERMINISTIC",
    "data_quality": "DEMO",
    "unknown_length_m": 0.0,
    "evidence_ids": ["sensor-fixture-1"],
    "warnings": ["Synthetic contract fixture; not an assessed journey."]
  },
  "versions": {
    "graph": "graph-fixture-1",
    "risk": 7,
    "policy": "policy-fixture-1",
    "model": null,
    "feature": null
  },
  "freshness": {
    "evaluated_at": "2026-10-06T12:00:00Z",
    "oldest_relevant_observation_at": "2026-10-06T11:59:30Z",
    "risk_processing_lag_seconds": 2.0,
    "stale": false
  },
  "cache": {"calculation_hit": false},
  "request_id": "req-fixture",
  "correlation_id": "corr-fixture"
}
```

Production values come only from graph/evidence computation. Geometry endpoints are snapped nodes; any off-road connectors are separately labeled display aids, not validated traversable paths. ETA excludes live traffic unless a future provider supports it. Risk scores are policy estimates, not guaranteed route-flood probabilities. A same-node zero-distance journey uses a Point geometry, with `distance_m=0` and `eta_seconds=0`; the frontend handles that explicitly.

`GET /routes/{id}` returns the same current route shape plus prior-revision comparison when available. Route status is ACTIVE, INVALIDATED, UNAVAILABLE or EXPIRED. A revision stream may advertise invalidation before the replacement is ready. The frontend must show that interval. Route IDs remain stable; revisions increase monotonically and are immutable. Every revision stores graph/risk/policy/model lineage.

Calculation starts a bounded journey-monitoring subscription and returns `monitoring_expires_at` once Phase 8 is implemented. Initial proposal: 30 minutes, configurable and renewable through an owned `POST /api/v1/routes/{route_id}/subscription` endpoint. SSE connections do not silently grant infinite monitoring. Expired/unsubscribed routes retain their stored as-of assessment until privacy retention removes them, but no longer trigger reroute work. Precise location/history retention is configurable and must be finalized before production deployment.

## Evidence intake and async receipts

`POST /api/v1/sensor-events` accepts a discriminated observation schema:

```json
{
  "source_event_id": "demo-seed-42-step-17-sensor-3",
  "sensor_id": "demo-water-3",
  "region_id": "mumbai-demo",
  "kind": "WATER_DEPTH",
  "location": {"longitude": 72.8840, "latitude": 19.0800},
  "value": 0.32,
  "unit": "m",
  "observed_at": "2026-10-06T12:00:00Z",
  "source_sequence": 17,
  "quality": "SIMULATED"
}
```

Allow specific kind/unit combinations and bounded values; producer identity comes from authentication, not the body. Validate sensor registration/location, plausible timestamps and sequence behavior. Reject malformed inputs with 422 and conflicting source IDs with 409. Identical retry deliveries return the same accepted resource/event identity. Separate schemas represent rainfall intensity/accumulation, zone revision and sensor status; a failed sensor is a quality/status event, not a fabricated zero-depth reading.

```json
{
  "resource_id": "22222222-2222-4222-8222-222222222222",
  "event_id": "33333333-3333-4333-8333-333333333333",
  "status": "ACCEPTED",
  "risk_application_status": "PENDING",
  "correlation_id": "corr-fixture"
}
```

A 202 means the observation and publication intent are durable. It does not mean downstream risk or routes have been updated. Operator tooling observes processing watermarks/event status. Simulation job receipts use a job ID and status URL; the seeded simulator sends the same observation contracts and never edits Redis/weights directly. Simulation mode must be explicitly enabled and tagged so demo evidence does not blend into a production assessment.

Incident reports contain a validated location, type, description, observed time, severity and optional pre-authorized private object reference. Persist the original report and expose PENDING confidence/verification; later corroboration can affect risk. Image references are owned S3 keys from a controlled upload workflow, not arbitrary external URLs.

## SSE route changes

`GET /api/v1/routes/{route_id}/events` returns `text/event-stream`, disables proxy buffering/cache, sends heartbeats and supports `Last-Event-ID`. A fetch-based streaming client sends auth headers or same-origin cookies without query-string tokens. Check ownership on connection and revalidate expiring sessions during long streams. Limit simultaneous streams per session and task.

The feed cursor is per-route monotonic sequence, distinct from domain event UUID and route revision. Example frames:

```text
id: 41
event: route.invalidated
data: {"route_id":"11111111-1111-4111-8111-111111111111","revision":1,"target_risk_version":8,"affected_edge_ids":[3002],"reason":"verified_water_depth","correlation_id":"corr-fixture"}

id: 42
event: route.recalculated
data: {"route_id":"11111111-1111-4111-8111-111111111111","previous_revision":1,"revision":2,"risk_version":8,"eta_delta_seconds":90,"risk_score_reduction":0.15,"route_url":"/api/v1/routes/11111111-1111-4111-8111-111111111111","correlation_id":"corr-fixture"}

: heartbeat
```

The browser fetches the authorized route URL to obtain full geometry and rejects responses older than its current revision. `route.unavailable` means no eligible alternative. `resync_required` means the cursor is expired/invalid; fetch current state and resume from a fresh supplied cursor. On Redis failure gateways periodically read the durable feed; on disconnect the UI displays stale status and polls while reconnecting with bounded jitter. A stream notification is not a substitute for fetching authoritative route state.

## Assistant contract

`POST /api/v1/assistant/messages` accepts bounded message text and an optional owned route/location context. Return explanation, uncertainty, tool outcomes, evidence references/timestamps and versions. Do not return internal prompts, raw private provider payloads, credentials or arbitrary tool instructions.

| Internal tool | Validated inputs | Authoritative result |
| --- | --- | --- |
| `get_current_weather` | Covered point, bounded variables | Observation IDs, values/units, provider, age and unknown/stale state |
| `get_flood_risk` | Covered point | Snapshot/policy, risk, evidence/quality and freshness |
| `calculate_safe_route` | Source/destination, mode, optional region | Route service result; same eligibility and ownership rules |
| `get_nearby_incidents` | Point and bounded radius | Redacted incident evidence with confidence/verification |
| `get_route_risk` | Owned route ID and optional revision | Stored route evidence and current validity |
| `get_nearby_safe_locations` | Covered point and bounded radius | Verified dataset entries and freshness; unavailable if no dataset |

Use fixed JSON schemas with unknown fields rejected and explicit enum/range limits. Backend dispatch is an allowlisted mapping to service functions; no model-generated URL, SQL, code, shell, AWS operation or generic execution tool. Every tool applies caller permissions. Limit total deadline, rounds, tokens, result count and geographic scope. Ground answer statements in returned evidence IDs that the client can inspect. Tools failing/returning stale data cannot become confident safety claims.

## Errors and degradation

Use `application/problem+json` with stable machine-readable `code`, human-readable `detail`, trace IDs and optional validated field errors. Do not leak SQL, infrastructure identifiers, tokens or raw dependency exceptions.

```json
{
  "type": "urn:floodguard:problem:no-route",
  "title": "No eligible route",
  "status": 422,
  "code": "NO_ELIGIBLE_ROUTE",
  "detail": "No directed path remains under the current closure policy.",
  "request_id": "req-fixture",
  "correlation_id": "corr-fixture"
}
```

| Status | Examples |
| --- | --- |
| 400 | Invalid bounding box/cursor syntax |
| 401 | Missing, expired or invalid authentication |
| 403 | Role/scope/CSRF violation |
| 404 | Unknown or non-owned private resource, to avoid existence leakage |
| 409 | Idempotency payload conflict, incompatible requested revision |
| 422 | Invalid coordinates, region not covered, snap beyond limit, no eligible directed route |
| 429 | Actor/IP/device quota or concurrency admission rejected; include retry guidance |
| 503 | Database unavailable, evidence too stale, routing capacity exhausted, repeated version churn, assistant provider unavailable |
| 504 | Admitted operation exceeded its end-to-end deadline |

Dependency degradation can still produce a successful route when deterministic risk and authoritative DB snapshots are usable. Include `data_quality`, `stale`, `assessment_method` and warnings rather than hiding fallback. Route risk lookup must indicate when its stored revision no longer matches current published risk. Health, OpenAPI and API tests are implemented in later phases; this specification defines their expected behavior.
