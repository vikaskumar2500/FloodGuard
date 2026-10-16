# Realtime rerouting

Phase 8 uses process-local components. `InMemoryEventBus` is the internal domain boundary,
`RuntimeRiskState` owns the monotonically increasing material-risk revision, and
`ActiveRouteRegistry` indexes active routes by stable road-edge identity. These components are
deliberately replaceable by distributed infrastructure in a later phase.

## Architecture and runtime pipeline

The running application executes this exact pipeline without intermediate manual steps:

```text
Phase 7 Simulator (CLI / Scenario / BackendSink)
        ↓ HTTP POST /api/v1/dev/simulation/events
Development Simulation Endpoint (SimulationEvent validation & deduplication)
        ↓
SimulationEnvironmentalAdapter (FixtureEnvironment / Evidence mutation)
        ↓
RuntimeRiskState.apply(event) (Material threshold >= 0.30 or level transition)
        ↓
risk revision + affected edge IDs
        ↓
InMemoryEventBus ("risk.edges_changed")
        ↓
RealtimeRerouteCoordinator (single-flight asyncio.Lock per route & pending queue)
        ↓
ActiveRouteRegistry (edge index lookup & route state)
        ↓
Current-route reassessment (evaluate existing path first)
        ↓
Reroute policy (FASTEST / BALANCED / SAFEST with hysteresis & cooldown)
        ↓
RoutingService / A* recalculation (distinct candidate route identity)
        ↓
RealtimePublisher (bounded subscriber queue with monotonic sequence)
        ↓
FastAPI SSE endpoint (GET /api/v1/routes/{route_id}/events)
        ↓
Browser EventSource client (subscribeToRoute)
        ↓
Frontend lifecycle reducer (routeLifecycleReducer)
        ↓
MapLibre GL dual-layer (previous muted dashed layer + active route layer) & Comparison UI
```

### Application Runtime Container (`FloodGuardRuntime`)

The application state is maintained cleanly in `app.state.runtime = FloodGuardRuntime.create(config)` constructed inside the FastAPI lifespan context manager. It wires:
- `event_bus`: `InMemoryEventBus`
- `route_registry`: `ActiveRouteRegistry` with TTL expiration
- `realtime_publisher`: `RealtimePublisher` with non-blocking overflow drop
- `runtime_risk_state`: `RuntimeRiskState` tracking risk revisions
- `reroute_coordinator`: `RealtimeRerouteCoordinator` executing single-flight reroute orchestration
- `fixture`: `FixtureEnvironment` deterministic topology and risk snapshot adapter

Dependency access functions (`get_runtime`, `get_route_registry`, `get_realtime_publisher`) provide clean test overrides without global module singletons.

## Route event stream

`GET /api/v1/routes/{route_id}/events` is a route-scoped Server-Sent Events endpoint. The route ID
must be a UUID and must identify an active route. Responses use `text/event-stream`, disable proxy
buffering and caching, send a heartbeat every 15 seconds, and remove the subscriber queue after
disconnect. Each subscriber has a 16-item queue. Publishing never waits for a consumer; when a
queue fills, stale heartbeats or risk updates are removed before critical lifecycle events.

Every event has one envelope: `eventId`, `eventType`, `routeId`, `sequence`, `occurredAt`,
`riskRevision`, and typed `data`. Sequences start at one and increase independently for each route.
The frontend ignores non-heartbeat events whose sequence is not newer than its accepted sequence.

## Risk revisions and material changes

The runtime revision increases only if an edge changes risk level, changes critical status, or its
normalized score changes by at least `RISK_CHANGE_THRESHOLD=0.30`. Replaying a simulation event ID
does nothing. An active route records `evaluated_risk_revision`; a revision is never evaluated twice.
The 0.30 threshold filters measurement noise while the level and critical-status clauses preserve
meaningful boundary changes.

The intended adapter chain is simulation event → environmental adapter → risk assessment →
material edge set → internal risk-edges-changed event → edge index → current-route reevaluation.
The simulator and SSE publisher do not call rerouting directly.

## Policies

All policies reevaluate the current path before searching for an alternative.

- **FASTEST:** reroutes for SEVERE risk, or HIGH risk when a LOW/MODERATE candidate adds no more
  than 10% ETA.
- **BALANCED:** requires at least 0.10 risk reduction (unless SEVERE) and at least 10% improvement
  in `ETA × (1 + risk)`.
- **SAFEST:** requires a latched unsafe route, at least 0.10 risk reduction (unless SEVERE), and an
  alternative within 50% of the current ETA.

Unsafe hysteresis enters at risk 0.70 (or HIGH/SEVERE level) and clears at risk 0.55. The development
cooldown is 30 seconds. SEVERE updates may bypass cooldown. Clocks are injectable in policy tests.

## Concurrency and failure

Each route has one asynchronous lock. Updates received during a calculation are unioned into one
pending edge set at the newest revision and evaluated once after the active calculation. Duplicate
revisions are skipped. A replacement gets a new route ID; the old route is unregistered only after
the replacement is ready. Failure emits `route.reroute_failed` with a public reason and preserves
the current path.

## Frontend state machine

The reducer supports IDLE, CALCULATING, ACTIVE, RISK_UPDATED, INVALIDATED, REROUTING, REROUTED,
REROUTE_FAILED, STREAM_RECONNECTING, and ERROR. A dedicated realtime client owns `EventSource`.
Changing or clearing a route closes the old stream; unmount cleanup does the same. Reconnection
keeps route geometry visible. Recalculation keeps the old path as a muted dashed MapLibre layer,
installs the new path as the primary layer, and displays the actual ETA and risk comparison. The
old comparison is held in state and can be removed without rebuilding the map.

This is intentionally process-local. A future distributed phase can replace the event bus and
publisher with SQS/EventBridge or another broker while retaining the envelope and coordinator
boundaries.
