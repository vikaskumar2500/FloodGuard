# Phase 7 simulator

Phase 7 provides deterministic environmental simulation without real sensors, external weather APIs, WebSockets, or distributed event infrastructure. The package lives under `simulations/` and does not modify the production risk engine.

## CLI

```sh
uv run python -m simulations list
uv run python -m simulations run --scenario flash_flood --seed 42 --dry-run
uv run python -m simulations run --scenario severe_rain --seed 42 --sink file --output recordings/severe-rain.jsonl
uv run python -m simulations replay --file recordings/severe-rain.jsonl
```

Scenario names are `NORMAL`, `MODERATE_RAIN`, `SEVERE_RAIN`, `FLASH_FLOOD`, `SENSOR_OUTAGE`, and `RECOVERY`; lowercase CLI names are accepted. The default start time is fixed UTC `2026-10-07T00:00:00+00:00`, making command output reproducible. Use `--start-time` to choose another timezone-aware timestamp.

## Architecture

- `models.py`: typed scenario steps, sensors, event types, and validation
- `clock.py`: immediate and timed simulation clock
- `scenarios/catalog.py`: declarative scenario timelines and seeded variation
- `engine.py`: deterministic event generation and ordering
- `sinks/`: memory, JSONL file, and explicit backend adapter
- `replay.py`: JSONL validation and replay
- `integration.py`: optional in-memory adapter to Phase 6 `EdgeEvidence`, risk snapshots, and synchronous route calculation

The simulator owns its `random.Random(seed)` instance. Scenario ID is `scenario-name:seed`; event IDs are UUIDv5 values derived from scenario ID and sequence, so repeated runs are deduplicable.

## Event model

Each event contains:

```json
{
  "event_id": "stable UUID",
  "scenario_id": "flash_flood:42",
  "sequence": 4,
  "event_type": "FLOOD_ZONE_ACTIVATED",
  "occurred_at": "2026-10-07T00:15:00+00:00",
  "payload": {}
}
```

Sequences are contiguous and ordered. Timestamps are timezone-aware and nondecreasing. Payloads use millimeters/hour for rainfall and centimeters for water depth. Coordinates are WGS84 longitude/latitude fields and are validated before emission.

## Clock modes

Immediate mode emits without sleeping and is used by tests and CI. Timed mode maps simulated elapsed seconds to wall-clock seconds divided by `--speed`; `--speed 10` runs ten simulated seconds per real second. Correctness never depends on sleeping.

## Sensors and outages

Synthetic sensors include rain gauges and water-level sensors. Health states are `ONLINE`, `DEGRADED`, and `OFFLINE`. Offline sensors do not emit valid readings. The in-memory risk adapter removes active sensor readings when an outage event occurs, reducing confidence without automatically declaring low risk.

## Scenarios

- `NORMAL`: zero rainfall, zero depth, healthy sensors
- `MODERATE_RAIN`: moderate rain and limited accumulation
- `SEVERE_RAIN`: heavy rain, high depth, high flood-zone activation
- `FLASH_FLOOD`: staged rainfall, depth increase, zone activation/update, and incident
- `SENSOR_OUTAGE`: normal readings followed by degraded/offline health
- `RECOVERY`: severe baseline followed by declining rain/depth, zone reduction/clearance, and incident resolution

## Sinks and replay

`MemorySink` preserves events for tests and ignores duplicate event IDs. `FileSink` writes one JSON object per JSONL line and also ignores duplicate IDs. `BackendSink` is an explicit HTTP adapter or injectable sender callback; it fails clearly when the endpoint is unavailable and never silently falls back to local persistence. No simulation event table or migration is introduced.

Replay validates unique IDs, contiguous sequence, ordered timestamps, and payload structure before emitting events to a sink.

## Risk and route integration

`simulations.integration.events_to_evidence()` maps generated events to Phase 6 `EdgeEvidence` using configured edge aliases. It calls `evaluate_graph()` with the simulation timestamp, then `build_edge_costs()` and the existing Dijkstra/A* implementation. This is synchronous recalculation after applying a scenario state, not automatic rerouting.

The fixture flash-flood path uses `fixture-top-1`, `fixture-top-2`, and `fixture-top-3` as the affected corridor. Normal events produce low/unknown risk, flood-zone and depth events raise risk, outage events reduce confidence, and recovery events lower active zone risk.

## Boundaries and limitations

There is no WebSocket/SSE, automatic route invalidation, SQS/EventBridge, ML, Redis cache, weather provider, or AWS integration. BackendSink is deliberately an adapter boundary for a future controlled development endpoint or distributed transport. Real PostGIS persistence remains an environment-dependent integration concern.
