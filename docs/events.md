# FloodGuard domain events and asynchronous processing

Status: Production Contract (Updated October 2026). Phase 14 implements AWS SQS asynchronous event processing with the canonical TransportEnvelope. Phase 15 implements AWS EventBridge for event routing and fan-out. See [events-v1.md](events-v1.md) for canonical envelope schemas, [sqs.md](sqs.md) for SQS topology, and [eventbridge.md](eventbridge.md) for routing rules.

## Commands and facts

A command asks a specific owner to do work: `ImportRoadGraph`, `RunSimulation`, `RecalculateRoute`, `TrainModel`, `VerifyIncident`. It can be accepted, rejected or superseded and belongs in a durable job/command queue with status. A domain event states a committed fact: `SensorReadingReceived`, `FloodRiskUpdated`, `RouteRecalculated`. Do not publish `FloodRiskUpdated` before the corresponding snapshot is durable and active.

Request IDs identify individual HTTP attempts; correlation IDs trace the overall workflow; causation IDs identify the immediate triggering event/command. The original correlation ID crosses consumers and resulting events. Operational replay adds an audit/replay ID while preserving original event identity.

## Envelope and schema evolution

Use a Pydantic/JSON Schema discriminator on `(event_type, schema_version)`. Producers validate before writing the outbox, consumers validate before applying effects. All required fields are typed and bounded; timestamps are UTC and data units are explicit. Use the same canonical envelope locally and in AWS:

```json
{
  "event_id": "33333333-3333-4333-8333-333333333333",
  "event_type": "SensorReadingReceived",
  "schema_version": 1,
  "occurred_at": "2026-10-06T12:00:00Z",
  "producer": "floodguard.sensor-api",
  "correlation_id": "corr-fixture",
  "causation_id": "req-fixture",
  "idempotency_key": "device:demo-water-3:demo-seed-42-step-17-sensor-3",
  "aggregate": {"type": "sensor", "id": "demo-water-3", "version": 17},
  "region_id": "mumbai-demo",
  "data": {
    "sensor_event_id": "22222222-2222-4222-8222-222222222222",
    "kind": "WATER_DEPTH",
    "value": 0.32,
    "unit": "m",
    "observed_at": "2026-10-06T12:00:00Z",
    "source_sequence": 17,
    "quality": "SIMULATED"
  }
}
```

This is synthetic fixture data. `event_id` is a stable producer-assigned UUID, preserved across retries. `idempotency_key` identifies the business action and never contains secrets/PII. Where a producer lacks sequence numbers, use explicit source timestamp and stable record identity; do not pretend arrival order is sensor chronology. Aggregate version semantics depend on the event type and must be documented in its schema.

For EventBridge Classic `PutEvents`, set `Source` to the producer, `DetailType` to the event type, `Detail` to the canonical envelope JSON and `Time` to `occurred_at`. EventBridge's transport ID is separate from the domain `event_id`. SQS receives the EventBridge transport wrapper containing this envelope; adapters unwrap it without confusing IDs. Commands sent directly to SQS use a distinct validated command envelope, not an event that falsely claims completion.

Additive compatible fields can stay schema v1 only if deployed readers tolerate unknown optional fields safely. Breaking changes need a new integer version, dual publication or an explicit translator during migration, and consumer contract tests. Consumers reject/quarantine unknown major versions with a reason instead of guessing. Keep fixtures/schemas under a future shared `contracts/events/` directory; event versioning is independent of HTTP and model versions.

Cap event bodies below the minimum configured transport limit, initially 64 KiB. Store large GeoJSON, changed-edge sets, datasets and prediction batches in PostgreSQL or private S3 with version/checksum references. An S3 pointer is an internal approved bucket/key, never an arbitrary URL; consumers validate allowed scope and content before reading it.

## Event catalog and owners

| Event | Publisher and committed fact | Required payload beyond envelope | Consumers |
| --- | --- | --- | --- |
| `SensorReadingReceived` | Ingestion service: new valid immutable sensor reading accepted | Record ID, kind/value/unit, observed time, sequence/quality | Risk aggregator, ML feature/prediction worker |
| `SensorStatusChanged` | Sensor service: quality/availability changed | Sensor ID, prior/new status, effective time, reason | Risk aggregator, operations notifications |
| `WeatherObservationReceived` | Weather ingestion: normalized observation committed | Record ID, provider, location key, interval, observed/expiry times, quality | Risk aggregator, ML feature worker |
| `ObservationFreshnessExpired` | Freshness scheduler: evidence crossed expiry | Evidence references, expiry/effective time | Risk aggregator, operations monitoring |
| `FloodZoneChanged` | Zone service: new zone revision accepted | Zone ID/revision, previous/new geometry reference, validity, severity | Risk aggregator, map notifications |
| `IncidentReported` | Incident service: report committed, still unverified | Incident ID/type, observed time, quality/confidence state | Incident confidence worker; no immediate hard closure |
| `IncidentConfidenceChanged` | Incident worker/operator: corroboration/verification committed | Incident ID, revision, confidence, verification, evidence IDs | Risk aggregator, map/notification consumer |
| `ModelPredictionGenerated` | ML worker: validated versioned prediction stored | Prediction/batch ID, model/feature versions, feature cutoff, horizon/expiry, graph version | Risk aggregator, lifecycle monitoring |
| `FloodRiskUpdated` | Risk worker: new compatible snapshot activated | Previous/new risk versions, graph/policy/model versions, evidence watermark, changed-edge reference/count, freshness | Reroute planner, map/notification consumer, operational metrics |
| `RouteInvalidated` | Reroute planner: current subscribed revision marked stale | Route ID/revision, target risk version, affected edges/reference, reason | SSE wake-up/notification consumers |
| `RouteRecalculated` | Reroute worker: next immutable revision committed | Route ID, prior/new revision, target versions, ETA delta, risk comparison and affected-edge reference | SSE wake-up/notification consumers, operational metrics |
| `RouteUnavailable` | Reroute worker: no eligible replacement under target snapshot | Route ID/revision, target versions, reason and impacted-edge reference | SSE wake-up/notification consumers |
| `RoadGraphActivated` | Import service: validated graph and initial risk snapshot activated | Region, previous/new graph, compatible risk version, import manifest | Graph loaders, regional route invalidation planner |
| `ModelVersionPromoted` | Registry: approved compatible model selection committed | Previous/new model, feature version, manifest reference, approver audit reference | ML loaders, model lifecycle monitoring |

`FloodZoneChanged` describes committed zone evidence, not yet applied edge risk. `ModelPredictionGenerated` similarly precedes risk publication. Reroute consumers subscribe to `FloodRiskUpdated`/`RoadGraphActivated`, not raw observations. Prediction workers subscribe to new observations but not to their own predictions or every risk update, preventing event loops.

Bedrock conversations do not generate flood facts. Notification delivery receipts and cache counters are operational telemetry, not authoritative risk events. Sensitive reporter/session details stay in protected storage rather than broad bus payloads.

Route-state services write durable `route_feed` entries in the same transaction as invalidation/revision changes. Event subscribers may wake gateways or notify users, but must not create a second feed entry for the same change. This avoids making UI delivery depend on a later bus round trip while preserving durable replay.

## Queues, fan-out and workloads

Use standard SQS queues initially and design for duplicate/out-of-order delivery. Version guards solve state ordering at the domain boundary; FIFO transport would not make database side effects exactly once. Independent consumers must receive independent queue copies. [SQS documents at-least-once delivery](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html).

| Queue suffix (environment-prefixed) | EventBridge subscription or command owner | Execution |
| --- | --- | --- |
| `observation-ingest` | Direct validated intake commands from scheduled Lambda adapters; restricted producer IAM | ECS ingestion worker commits observations and domain outbox events |
| `sensor-risk` | Sensor/weather/status/freshness/zone/confidence events plus model predictions | ECS risk worker |
| `prediction` | Sensor/weather events needed by feature pipeline | ECS ML worker |
| `incident` | IncidentReported | ECS confidence worker |
| `reroute-plan` | FloodRiskUpdated, RoadGraphActivated | ECS planner; creates durable route jobs |
| `reroute-work` | Validated RecalculateRoute commands relayed from durable job/outbox records | ECS graph/reroute worker |
| `notifications` | RouteInvalidated/Recalculated/Unavailable, incident/status alerts | Lambda adapter; never exposes private routes broadly |
| `map-updates` | FloodRiskUpdated, FloodZoneChanged, IncidentConfidenceChanged | ECS bounded map/feed update worker |
| `model-lifecycle` | ModelVersionPromoted and prediction metadata | ECS lifecycle worker when Phase 32 requires it |

Queue names are `floodguard-{environment}-{suffix}` with a consumer DLQ for each. Configure separate EventBridge target-delivery DLQs; they handle failed routing to SQS, while consumer DLQs handle failed processing after successful delivery. Classic rule target DLQs are described in [AWS EventBridge documentation](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-dlq.html).

Start with only queues needed by implemented phases. The notification adapter is optional until delivery destinations exist. Metrics can come directly from application/worker logs initially rather than adding a dedicated metrics queue. EventBridge rules match exact source/type/schema and point to only necessary queues. IAM/resource policies restrict sending to these rule/role identities, and all queues/DLQs are encrypted.

## Outbox protocol

1. Validate request/command and source idempotency.
2. In one database transaction, update the owned domain records and insert immutable outbox rows with stable event IDs and canonical payloads. Commit before returning accepted success.
3. An ECS relay leases due rows with a short transaction and `FOR UPDATE SKIP LOCKED`, releases locks, and sends outside the database transaction. Leases have expiry so a crashed relay does not strand work.
4. Inspect per-entry success for batch sends; a successful transport HTTP response is not proof every entry was accepted. Mark only acknowledged entries published. Failed entries retain retry state/reason and use bounded exponential backoff with jitter.
5. A crash after send but before marking published can resend an event. Preserve its ID; consumers deduplicate it.
6. Exhausted relay attempts enter a visible failed/quarantined state with an alarm and operator retry path. Do not delete unpublished rows. Alert on oldest unpublished age and count.

Database outbox state and broker delivery cannot be one transaction; this protocol preserves durable intent and tolerates duplicates. It does not promise exactly-once transport. For durable commands, use the same outbox/relay principle with a validated command destination rather than relying on an API process calling SQS after commit.

## Consumer transaction and acknowledgment

For state-changing workers:

1. Receive and validate envelope/schema/source. Generate processing trace context, preserving event and correlation IDs. Enforce size, version, trusted pointer and payload constraints before effects.
2. Read event/evidence identity and current version. Build expensive computations outside a long database transaction. Multiple deliveries may duplicate calculation work but must not duplicate committed effects.
3. Begin a transaction; acquire the domain's short version/row lock as needed. Insert `(consumer_name, event_id)` into `processed_messages`, protected by a unique constraint. If already committed, skip effects and acknowledge. If a concurrent insert is pending, resolve it through the database constraint, never an in-memory check.
4. Apply only a current/compatible result using compare-and-swap. Store mutations, resulting outbox events, job/feed records and inbox success atomically. If computation was superseded, commit an explicit no-op outcome or a durable latest-version job, rather than overwriting state.
5. Commit. Only then delete the SQS message using its current receipt handle. Lambda handlers return success only after durable completion; configure partial batch failure reporting so successful items are not retried solely because a sibling failed.
6. If validation/transient computation/DB transaction fails, do not acknowledge. Extend the visibility lease for legitimately long active work; crash or heartbeat loss lets the message reappear. [AWS's visibility-timeout documentation](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html) explains this lease behavior.

The inbox insert is rolled back with failed domain effects. A crash after commit but before delete results in a successful deduplicated retry. Separate consumers legitimately handle the same event, so an inbox key cannot be just `event_id`. Source-event uniqueness additionally prevents duplicate observation records arriving through separately minted HTTP/event IDs. Business keys protect notifications/jobs from accidental event-ID regeneration.

External notification delivery cannot share a DB transaction. Use a delivery ledger and provider idempotency key where available. Without provider deduplication, document the possibility of duplicate user notifications; never claim exactly-once email/SMS. Local UI feed writes are database effects and can be transactionally deduplicated.

## Ordering, coalescing and stale work

No global ordering assumption. Consumers use source sequence/observed time for evidence and aggregate versions for state. Keep late historical readings, but a late reading must not replace a newer sensor current value. Risk updates recompute from authoritative latest evidence and commit a new region version only if the candidate graph/evidence watermark still matches.

Per-route jobs target the latest graph/risk version. Use leases and `(route_id, target_risk_version)` uniqueness; coalesce pending older targets. Commit a replacement only if the predecessor route revision and targeted active snapshot still match. SSE feed sequence and route revision are independent monotonic counters, so old notifications cannot roll the UI backward.

Replay of an older FloodRiskUpdated must not reactivate an older snapshot. A processed duplicate does nothing; unprocessed historical delivery can request a latest-version reconciliation rather than run the old plan. An approved new computation uses a new command identity while preserving causation, instead of mutating an existing event to bypass deduplication.

## Retries, poison messages and replay

Proposed initial parameters to tune in staging: 30-second visibility for lightweight handlers, explicit heartbeat extensions for heavy workers, five receive attempts before consumer DLQ, four-day source retention and fourteen-day DLQ retention. Align visibility with actual processing budgets; keep heartbeat intervals well below it. Bound SDK retries and worker retries so nested policies do not amplify an outage. Lambda queue visibility and batch parameters must be checked against that function's actual budget during infrastructure implementation.

Transient failures (throttling, unavailable DB/provider, broker timeout) get bounded backoff/jitter; permanent schema/authorization/pointer failures get a recorded rejection and quarantine path. Either allow configured redrive to DLQ without acknowledgment, or persist a quarantine record and confirm its DLQ send before deleting. Malformed work must not disappear or repeatedly monopolize workers. EventBridge delivery retries, consumer processing retries and outbox retries are distinct policies with distinct alarms.

DLQ tooling is operator-only and requires a concrete queue/event selection, schema validation, root-cause repair, a dry run, bounded batch size/rate and replay audit. Preserve canonical event IDs for ordinary retries so successful side effects remain deduplicated. Failed transactions have no committed inbox record and can succeed after repair. Never automatically delete inbox history or mint new IDs to force side effects. Corrected malformed data is a new validated event with a correction/causation reference, leaving the original auditable.

Do not assume EventBridge target DLQ bodies match consumer DLQ bodies; adapters inspect transport metadata and extract the canonical envelope before resubmission. Confirm replay acceptance and observe downstream outcome before removing selected DLQ records. Keep DLQ retention longer than source retention and alarm on nonempty DLQs/oldest message age. Choose inbox/source-business-key retention to cover the full supported replay horizon; arbitrary ancient replay after dedupe expiry is prohibited without a separate audited reconciliation.

## Local compatibility

Local development does not require AWS. A PostgreSQL-backed dispatcher consumes outbox rows into durable local jobs per subscriber. Workers apply the same event schemas, inbox uniqueness, version checks, retries and quarantine status. Repeated delivery/fault fixtures deliberately test duplicate behavior. Do not use FastAPI BackgroundTasks or Redis pub/sub as the sole durable queue.

The initial Phase 1 Compose has postgres, redis, backend and frontend. From Phase 7/8 a worker service/profile runs local dispatch/risk/reroute loops; AWS adapter parity tests can later use an emulator/test AWS environment. An emulator does not prove production IAM, provider behavior or cloud quotas; staging integration tests must cover those boundaries.

## Trace example and required tests

For a seeded flood demonstration, use one `correlation_id`:

```text
HTTP sensor intake
  -> SensorReadingReceived(event A, causation=request)
  -> FloodRiskUpdated(event B, causation=A, risk version 8)
  -> RouteInvalidated(event C, causation=B, route revision 1)
  -> RecalculateRoute(command D, causation=C, target version 8)
  -> RouteRecalculated(event E, causation=D, route revision 2)
  -> Durable route-feed cursor 42 -> SSE -> updated map
```

This is a designed trace, not a captured execution. Parallel predictions/notifications retain correlation and record their own causation. Risk publication carries source evidence IDs/watermarks when aggregating several events; correlation alone does not establish complete data lineage.

Required later acceptance tests:

| Injection | Observable assertion |
| --- | --- |
| Same reading delivered twice through HTTP and queue | One observation/business identity and one set of committed consumer effects |
| Two workers receive the same event concurrently | Inbox unique constraint prevents duplicate state/outbox/feed |
| Relay crash after broker send | Resend preserves ID; consumer effects remain deduplicated |
| Worker crash before commit | Transaction/inbox roll back; message reappears and succeeds |
| Worker crash after commit, before acknowledgment | Retry is a no-op and message is acknowledged |
| DB temporarily unavailable | Message retained/retried; no successful inbox mark |
| Invalid schema or unknown version | Quarantine/DLQ with reason; valid messages continue |
| Older sensor/risk/route event arrives last | Current evidence/snapshot/revision never rolls backward |
| Partial broker/Lambda batch failure | Only failed entries/items retried |
| Duplicate replay of an already successful event | No extra report, route revision or notification ledger row |
| Redis pub/sub interruption | Durable cursor polling/resync recovers route notifications |
| Every path through a correlated update | Logs link request, evidence, snapshot, route revision and feed cursor |

The Phase 15 fan-out acceptance is independent reroute, map and notification consumers reacting to a committed FloodRiskUpdated without invoking each other. The Phase 16 resilience acceptance is visible failure/replay status and retry-safe state under these injections, not a claim of exactly-once delivery.
