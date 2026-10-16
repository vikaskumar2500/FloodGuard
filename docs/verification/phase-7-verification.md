# Phase 7 verification

## Executed results

- Simulator tests: 7 passed.
- Flash-flood dry run: 8 events generated with seed 42.
- JSONL file output: passed.
- JSONL replay: 8 events replayed.
- Risk/routing integration: included in simulator tests and passed.
- Backend non-integration suite: previously 50 passed; Phase 7 does not change production backend code.
- Frontend suite: previously 21 passed; Phase 7 does not change frontend code.

## Flash-flood timeline

Fixed start: `2026-10-07T00:00:00+00:00`.

| Simulation time | Event | Value |
|---|---|---|
| 00:00 | Sensor health | ONLINE |
| 00:00 | Rainfall | 0 mm/hour |
| 00:05 | Rainfall | 37 mm/hour with seed 42 |
| 00:10 | Water depth | 14 cm with seed 42 |
| 00:15 | Flood zone activated | HIGH, risk 0.78 |
| 00:20 | Water depth | 33 cm with seed 42 |
| 00:20 | Flood zone updated | SEVERE, risk 0.95 |
| 00:25 | Incident reported | HIGH waterlogging |

## Risk and route verification

The simulator test feeds the generated event stream into the Phase 6 risk functions at fixed timestamps. Before flooding, SAFEST selects the top corridor `A -> B -> C -> D`; at the 20-minute flash-flood snapshot, the targeted top edges are high risk and SAFEST selects the lower corridor `A -> E -> F -> D`. Recovery lowers the affected top-edge risk after zone clearance and incident resolution. The route bridge performs synchronous calculation only; it does not implement automatic rerouting.

The sensor outage test observes nonzero confidence before the offline transition and lower confidence after the transition, without treating missing readings as safe evidence.

## Infrastructure

No simulator database persistence was attempted. PostgreSQL/PostGIS and Redis remain unavailable. BackendSink is implemented as an explicit HTTP/callback adapter and was not sent to a live backend endpoint.

## Performance

No performance benchmark was taken. The test suite uses immediate clock mode and does not sleep.
