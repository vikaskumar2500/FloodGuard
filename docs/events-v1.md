# FloodGuard Domain Events Specification (v1)

**Document Version**: 1.0.0  
**Phase**: Phase 14 — AWS SQS for Asynchronous Event Processing  
**Status**: Production Active  
**Canonical Schema Version**: `1`  

---

## 1. Overview & Architectural Role

FloodGuard uses event-driven asynchronous processing to decouple real-world and synthetic observation ingress from the central routing and risk assessment pipelines.

### Critical Invariants

1. **CRITICAL INVARIANT 1**: SQS delivery is **AT-LEAST-ONCE**. Every handler must be strictly idempotent via Redis deduplication (`floodguard:v1:idempotency:{event_id}`).
2. **CRITICAL INVARIANT 2**: SQS messages are deleted **ONLY AFTER** successful processing by the registered handler.
3. **CRITICAL INVARIANT 3**: The transport envelope is **provider-neutral**. Domain logic remains agnostic to whether an event arrived via AWS SQS, LocalStack, or the in-memory test harness.
4. **CRITICAL INVARIANT 4**: SQS does **NOT** replace Server-Sent Events (SSE). SQS handles backend asynchronous ingress; SSE pushes realtime reactive updates to browser clients.
5. **CRITICAL INVARIANT 5**: **Out-of-order events must NEVER regress environmental or risk state**. Handlers track monotonic timestamps per entity and discard delayed arrivals that carry older timestamps than the active state.

---

## 2. Canonical Transport Envelope

All asynchronous domain events published over SQS, EventBridge (Phase 15), or local pipelines conform to the **v1 Transport Envelope**.

### JSON Envelope Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "FloodGuardTransportEnvelopeV1",
  "type": "object",
  "required": [
    "eventId",
    "eventType",
    "eventVersion",
    "occurredAt",
    "producer",
    "correlationId",
    "payload"
  ],
  "properties": {
    "eventId": {
      "type": "string",
      "format": "uuid",
      "description": "Globally unique, immutable event identifier assigned by the producer."
    },
    "eventType": {
      "type": "string",
      "pattern": "^[a-z0-9_]+(\\.[a-z0-9_]+)+$",
      "description": "Dotted lowercase namespace and event name, e.g. environment.weather_observed."
    },
    "eventVersion": {
      "type": "integer",
      "minimum": 1,
      "maximum": 1,
      "description": "Envelope and payload schema version. Currently fixed at 1."
    },
    "occurredAt": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 UTC timestamp of when the underlying observation or fact occurred."
    },
    "producer": {
      "type": "string",
      "description": "Identifier of the service or subsystem that emitted the event (e.g. environment.weather_provider)."
    },
    "correlationId": {
      "type": "string",
      "description": "End-to-end trace ID linking all events in an ingestion or simulation workflow."
    },
    "causationId": {
      "type": ["string", "null"],
      "description": "ID of the specific event or request that immediately triggered this event."
    },
    "payload": {
      "type": "object",
      "description": "Typed, schema-validated event payload specific to eventType."
    }
  },
  "additionalProperties": false
}
```

### Python Data Model

Defined in [`backend/app/messaging/envelope.py`](file:///Users/vikaskumar0205/Downloads/projects/FloodGaurd/backend/app/messaging/envelope.py):

```python
@dataclass(frozen=True)
class TransportEnvelope:
    event_id: str
    event_type: str
    event_version: int
    occurred_at: datetime
    producer: str
    correlation_id: str
    causation_id: str | None
    payload: dict[str, Any]
```

---

## 3. Event Catalog & Payload Specifications

### 3.1 `environment.weather_observed`

Emitted when weather stations or external APIs (e.g., OpenMeteo) provide fresh rainfall and atmospheric observations.

- **Producer**: `environment.weather_provider` / `environment.polling_service`
- **Consumer**: [`WeatherObservedHandler`](file:///Users/vikaskumar0205/Downloads/projects/FloodGaurd/backend/app/messaging/handlers.py)

```json
{
  "eventId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "eventType": "environment.weather_observed",
  "eventVersion": 1,
  "occurredAt": "2026-10-08T14:30:00Z",
  "producer": "environment.open_meteo",
  "correlationId": "c1a0c4f8-1d2a-43cf-9f1e-f3e9c719ef32",
  "causationId": null,
  "payload": {
    "latitude": 19.0760,
    "longitude": 72.8777,
    "rainfallRateMmPerHour": 28.5,
    "rainfallAccum1hMm": 24.0,
    "temperatureC": 27.2,
    "observationTime": "2026-10-08T14:30:00Z",
    "roadEdgeIds": ["edge-mumbai-south-01", "edge-mumbai-south-02"]
  }
}
```

### 3.2 `sensor.water_depth_observed`

Emitted by IoT ultrasonic or pressure water-level depth sensors mounted on bridges and culverts.

- **Producer**: `sensors.ingestion`
- **Consumer**: [`SensorObservationHandler`](file:///Users/vikaskumar0205/Downloads/projects/FloodGaurd/backend/app/messaging/handlers.py)

```json
{
  "eventId": "8b51d459-7f30-4e58-8b9a-4e2a868cb6f1",
  "eventType": "sensor.water_depth_observed",
  "eventVersion": 1,
  "occurredAt": "2026-10-08T14:31:00Z",
  "producer": "sensors.ingestion",
  "correlationId": "c1a0c4f8-1d2a-43cf-9f1e-f3e9c719ef32",
  "causationId": null,
  "payload": {
    "sensorId": "sensor-bridge-04",
    "roadEdgeId": "edge-mumbai-south-01",
    "waterDepthCm": 38.5,
    "rainfallMmPerHour": 32.0,
    "quality": "GOOD",
    "observedAt": "2026-10-08T14:31:00Z"
  }
}
```

### 3.3 `simulation.event_emitted`

Emitted by the deterministic simulation engine or scenario runners into SQS for asynchronous replay.

- **Producer**: `simulation.engine`
- **Consumer**: [`SimulationEventHandler`](file:///Users/vikaskumar0205/Downloads/projects/FloodGaurd/backend/app/messaging/handlers.py)

```json
{
  "eventId": "3c9b7b22-5555-4444-9999-111122223333",
  "eventType": "simulation.event_emitted",
  "eventVersion": 1,
  "occurredAt": "2026-10-08T14:32:00Z",
  "producer": "simulation.engine",
  "correlationId": "sim-run-flash-flood-01",
  "causationId": null,
  "payload": {
    "simulationEventId": "3c9b7b22-5555-4444-9999-111122223333",
    "scenarioId": "flash-flood-scenario",
    "simEventType": "FLOOD_ZONE_UPDATED",
    "sequence": 4,
    "data": {
      "zone_id": "south-basin",
      "severity": "SEVERE",
      "risk_score": 0.95,
      "confidence": 0.9,
      "target_edge_ids": ["edge-mumbai-south-01", "edge-mumbai-south-02"]
    }
  }
}
```

### 3.4 `risk.edges_changed`

Emitted on the backend internal event bus when material risk revisions occur.

- **Producer**: `runtime.risk_state` / Domain Handlers
- **Consumer**: `RealtimeRerouteCoordinator`

```json
{
  "eventType": "risk.edges_changed",
  "riskRevision": 14,
  "edgeIds": ["edge-mumbai-south-01", "edge-mumbai-south-02"],
  "sourceEventId": "8b51d459-7f30-4e58-8b9a-4e2a868cb6f1",
  "correlationId": "c1a0c4f8-1d2a-43cf-9f1e-f3e9c719ef32",
  "causationId": "8b51d459-7f30-4e58-8b9a-4e2a868cb6f1"
}
```

---

## 4. Idempotency Architecture

To satisfy **CRITICAL INVARIANT 1**, deduplication is managed via Redis using atomic leases.

### Key Schema

```
floodguard:v1:idempotency:{event_id}
```

### State Machine

```
[Incoming SQS Message]
        |
        v
  Redis.SET(NX, ex=120s, "PROCESSING")
        |
   +----+--------------------------+
   |                               |
   v (Success)                     v (Key Exists)
[ACQUIRED Lease]           Check Current Value
   |                               |
   v                               +---> "COMPLETED"   --> [Duplicate: Delete from SQS]
Execute Domain Handler             +---> "PROCESSING"  --> [In-Progress: Skip]
   |
   +--------------------+
   |                    |
   v (Success)          v (Exception)
Redis.SET(ex=86400s)  Redis.DELETE(key)
"COMPLETED"           Release visibility to 0s
Delete SQS Message    (Redelivery retry)
```

1. **Processing Lease (`PROCESSING`)**: Set atomically with `SET ... NX EX 120`. If another worker attempts to process the exact same message concurrently, it receives `IN_PROGRESS` and defers.
2. **Completion Marker (`COMPLETED`)**: On handler success, the key is updated to `COMPLETED` with a 24-hour TTL (`86400` seconds). Any subsequent delivery of this message is treated as a duplicate and immediately deleted from SQS without re-executing business logic.
3. **Lease Release on Failure**: If the handler raises an unhandled exception, `release()` deletes the Redis key, visibility timeout is set to 0, and SQS redelivers the message according to its retry policy.
4. **Degraded Fallback Mode**: If Redis is temporarily unreachable:
   - `DEGRADED_PROCESS` (default for resilience): Processes the event with a structured warning log.
   - `REJECT`: Rejects the message so SQS can retry after Redis recovers.

---

## 5. Traceability & Context Propagation

Every event guarantees full causal lineage through three standard headers:

1. `eventId`: UUID assigned by the originating producer. Never regenerated during transport or retry.
2. `correlationId`: Propagated from external API request, simulation session, or polling batch. Allows aggregating all downstream events in OpenTelemetry / CloudWatch.
3. `causationId`: Directly references the upstream event or command that caused this event to be published.

---

## 6. Contract Evolution & Versioning Rules

1. **Backward Compatibility**:
   - Field additions must be optional (nullable or default-provided).
   - Existing fields must NEVER change type or be removed in version `1`.
2. **Major Version Bumps**:
   - Breaking changes require incrementing `eventVersion` to `2`.
   - Consumers configured for version `1` reject version `2` with `UnsupportedVersionError`, ensuring malformed or future schemas are quarantined rather than corrupting state.


## 7. EventBridge Mapping

When using `EVENT_TRANSPORT=EVENTBRIDGE`, the canonical domain envelope is encapsulated in an AWS EventBridge PutEvents request. The mapping is as follows:

| Domain Field / App Config | EventBridge PutEvents Field |
| --- | --- |
| `eventbridge_source` config | `Source` (Default: `com.floodguard`) |
| `event_type` | `DetailType` (e.g. `environment.weather_observed`) |
| Canonical JSON Envelope | `Detail` (The full Phase 14 `TransportEnvelope`) |
| `eventbridge_bus_name` config | `EventBusName` (e.g. `floodguard-events`) |
| `occurred_at` | `Time` (Optional in PutEvents, EventBridge sets arrival time, but canonical `occurredAt` in `detail` remains authoritative) |

### EventBridge SQS Adapter

EventBridge rules deliver the event to an SQS target. The resulting SQS message body is wrapped in an EventBridge outer envelope. The `EventBridgeSqsMessageAdapter` unwraps this and extracts the canonical `TransportEnvelope` located in the `detail` property.

```json
{
  "version": "0",
  "id": "aws-eventbridge-uuid",
  "detail-type": "environment.weather_observed",
  "source": "com.floodguard",
  "account": "123456789012",
  "time": "2026-10-08T14:30:00Z",
  "region": "ap-south-1",
  "resources": [],
  "detail": {
    "eventId": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "eventType": "environment.weather_observed",
    "eventVersion": 1,
    "occurredAt": "2026-10-08T14:30:00Z",
    "producer": "environment.open_meteo",
    "correlationId": "c1a0c4f8-1d2a-43cf-9f1e-f3e9c719ef32",
    "causationId": null,
    "payload": {
      "latitude": 19.0760,
      "longitude": 72.8777
    }
  }
}
```

- **Domain `eventId`** remains preserved inside `detail.eventId`.
- **EventBridge `id`** is separately observable as `eventbridge_event_id` in telemetry and metrics.
- **SQS MessageId** remains separately observable.
