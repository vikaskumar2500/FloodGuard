# AWS SQS Architecture & Ingress Specification

**Document Version**: 1.0.0  
**Phase**: Phase 14 — AWS SQS for Asynchronous Event Processing  
**Status**: Production Active  

---

## 1. Architectural Topology

```
+-------------------------------------------------------------------------------+
|                             PRODUCERS LAYER                                   |
|                                                                               |
|  +--------------------+   +---------------------+   +---------------------+   |
|  | Weather Poller     |   | IoT Sensor Gateway  |   | Simulation Runner   |   |
|  | (OpenMeteo)        |   | (Depth / Pressure)  |   | (SqsSimulationSink) |   |
|  +---------+----------+   +----------+----------+   +----------+----------+   |
|            |                         |                         |              |
+------------|-------------------------|-------------------------|--------------+
             |                         |                         |
             v                         v                         v
+-------------------------------------------------------------------------------+
|                       TRANSPORT LAYER: AWS SQS QUEUE                         |
|                                                                               |
|   Queue: floodguard-events-standard (or InMemorySqsTransport for test)        |
|   - Standard Queue (High throughput, At-least-once delivery)                  |
|   - Visibility Timeout: 60s (Dynamically adjusted for exponential backoff)    |
|   - Dead-Letter Queue: floodguard-events-dlq (MaxReceives=3)                  |
|   - Message Retention: 4 days (345,600s)                                      |
+-------------------------------------------------------------------------------+
                                       |
                                       | Long Polling (wait_time <= 20s, batch <= 10)
                                       v
+-------------------------------------------------------------------------------+
|                      CONSUMER WORKER LAYER (FastAPI / CLI)                    |
|                                                                               |
|    +---------------------------------------------------------------------+    |
|    | SqsEventConsumer                                                    |    |
|    |   +-- Bounded Concurrency Semaphore (default: 5 concurrent workers) |    |
|    |   +-- Deserializer & Envelope Validator (EventSerializer)           |    |
|    |   +-- Redis Idempotency Gate (RedisIdempotencyStore)                |    |
|    |         - floodguard:v1:idempotency:{event_id}                      |    |
|    |         - Safely locked with unique worker token (Phase 16)         |    |
|    |         - PROCESSING (120s) -> COMPLETED (86400s)                   |    |
|    +----------------------------------+----------------------------------+    |
|                                       |                                       |
+---------------------------------------|---------------------------------------+
                                        v
+-------------------------------------------------------------------------------+
|                         DOMAIN HANDLER EXECUTION                              |
|                                                                               |
|   +-----------------------+   +--------------------+   +------------------+   |
|   | WeatherObserved       |   | SensorObservation  |   | SimulationEvent  |   |
|   | Handler               |   | Handler            |   | Handler          |   |
|   +-----------+-----------+   +---------+----------+   +--------+---------+   |
|               |                         |                       |             |
|               +-------------------------+-----------------------+             |
|                                         |                                     |
|                                         v                                     |
|                        +--------------------------------+                     |
|                        | RuntimeRiskState (Apply Edge)  |                     |
|                        | Monotonic timestamp protection |                     |
|                        +----------------+---------------+                     |
|                                         |                                     |
|                                         v                                     |
|                        +--------------------------------+                     |
|                        | InMemoryEventBus               |                     |
|                        | ("risk.edges_changed")         |                     |
|                        +----------------+---------------+                     |
|                                         |                                     |
|                                         v                                     |
|                        +--------------------------------+                     |
|                        | RealtimeRerouteCoordinator     |                     |
|                        | Active route re-evaluation     |                     |
|                        +----------------+---------------+                     |
|                                         |                                     |
|                                         v                                     |
|                        +--------------------------------+                     |
|                        | RealtimePublisher (SSE)        |                     |
|                        | Browser push notification      |                     |
|                        +--------------------------------+                     |
+-------------------------------------------------------------------------------+
```

---

## 2. Standard Queue vs FIFO Queue: Architectural Trade-Off Analysis

A common distributed systems question is whether to use **SQS Standard** or **SQS FIFO**. FloodGuard specifically adopts **SQS Standard** for environmental and telemetry ingest.

### Trade-Off Comparison Matrix

| Evaluation Dimension | SQS Standard (Chosen) | SQS FIFO |
| :--- | :--- | :--- |
| **Throughput Capacity** | **Nearly unlimited** (>10,000 msg/s). | Capped at **300 msg/s** (or 3,000 msg/s with high-throughput batch mode). |
| **Ordering Guarantee** | Best-effort (out-of-order possible). | Strict FIFO per Message Group ID. |
| **Head-of-Line Blocking** | **Zero blocking**. A failing event on edge A never blocks events on edge B. | **High risk**. A single poisoned message halts the entire Message Group ID queue. |
| **Deduplication** | Managed explicitly at application tier via Redis (`floodguard:v1:idempotency`). | Built-in 5-minute deduplication window only (insufficient for 24h replay). |
| **Latency** | Single-digit milliseconds ($< 10\text{ ms}$). | 10–25 ms due to partition lock coordination. |
| **Cost** | \$0.40 per million requests. | \$0.50 per million requests (+25% premium). |

### Justification for SQS Standard in FloodGuard

1. **Environmental Ingress Semantics**:
   - Environmental stations emit telemetry independently across geographic regions. Strict global serialization is unnecessary.
2. **Mitigation of Out-of-Order Delivery (CRITICAL INVARIANT 5)**:
   - Handlers maintain an in-memory high-water mark timestamp (`_latest_occurred_per_edge`) per road edge.
   - If an older weather report ($t_1$) arrives after a newer report ($t_2 > t_1$), the handler discards $t_1$, completely eliminating the possibility of state regression.
3. **Resilience Against Head-of-Line Blocking**:
   - In flood emergencies, thousands of sensor alerts may fire simultaneously. FIFO group locking would stall critical rerouting calculations if any single sensor reading fails or triggers an extended retry.
4. **Idempotency Beyond SQS FIFO's 5-Minute Window**:
   - SQS FIFO deduplicates only within a 5-minute deduplication interval. FloodGuard's Redis idempotency store provides a 24-hour durable window, which is required for operational replay and simulation safety.

---

## 3. Consumer Lifecycle & Reliability Semantics

### 3.1 Long Polling & Batch Receive
The consumer configures `WaitTimeSeconds=20` (maximum SQS long-poll) and `MaxNumberOfMessages=10`. This design:
- Minimizes empty receive calls, reducing AWS API costs by up to 90%.
- Yields immediate message delivery when messages arrive.

### 3.2 Bounded Concurrency Semaphore
Processing burst loads without concurrency limits risks exhausting PostgreSQL database connection pools or CPU cycles during graph recalculations.
- `SqsEventConsumer` enforces concurrency using an `asyncio.Semaphore(concurrency=5)`.
- Up to 10 messages fetched in a single poll batch are executed concurrently up to the semaphore limit without spawning unbounded tasks.

### 3.3 Message Deletion and Failure Redelivery
To guarantee **CRITICAL INVARIANT 2 (Delete ONLY on success)**:
- **On Success**:
  1. `await store.mark_completed(event_id)` transitions Redis lease to `COMPLETED` (TTL 86,400s).
  2. `await client.delete_message(queue_url, receipt_handle)` purges message from SQS.
- **On Handler Failure**:
  1. `await store.release(event_id)` immediately deletes the Redis `PROCESSING` lease.
  2. `await client.change_message_visibility(queue_url, receipt_handle, 0)` sets visibility timeout to 0 seconds so that the message becomes eligible for immediate retry without waiting for the 60-second default timeout.
  3. The message is **NOT deleted**.
- **On Malformed / Poison Message**:
  - Malformed JSON that cannot be parsed is logged as an error and deleted from SQS to avoid infinite poison-pill hot loops.

---

## 4. Standalone Worker Execution

FloodGuard provides a standalone background worker script:

```bash
# Run standalone messaging worker
python -m app.messaging.worker --queue-url "https://sqs.us-east-1.amazonaws.com/123456789012/floodguard-events" --concurrency 5
```

### Health & Telemetry Reporting

The standalone worker maintains live health state accessible via structured logging or monitoring probes:

```json
{
  "started": true,
  "polling": true,
  "last_poll_at": "2026-10-08T18:45:00Z",
  "last_processed_at": "2026-10-08T18:44:58Z",
  "metrics": {
    "sqs_messages_received_total": 450,
    "sqs_messages_processed_total": 448,
    "sqs_messages_deleted_total": 448,
    "sqs_duplicates_total": 2,
    "sqs_handler_errors_total": 0,
    "avg_handler_latency_ms": 1.45,
    "avg_queue_delay_ms": 12.3
  }
}
```

---

## 5. AWS IAM Least-Privilege Policies

### 5.1 Publisher Policy (Weather Poller, Sensor Gateway, Sim Sink)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSQSPublish",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:*:floodguard-*"
    }
  ]
}
```

### 5.2 Consumer Policy (FloodGuard API Worker / Background Task)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSQSConsumeAndAcknowledge",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:*:floodguard-*"
    }
  ]
}
```

