# Failure Recovery & Dead-Letter Queues (Phase 16)

FloodGuard’s asynchronous messaging pipeline ensures resilient processing by handling transient errors, poison messages, and service outages gracefully.

## Failure Taxonomy

We classify event processing failures into two categories to determine recovery behavior:

1. **Retryable Failures (`RetryableEventError`)**: Transient issues like database timeouts, external API rate limits, or Redis connection drops.
2. **Non-Retryable Failures (`NonRetryableEventError`)**: Poison messages, validation errors, unsupported versions, or permanent unhandled exceptions.

## Recovery Mechanisms

### 1. Exponential Backoff (SQS Visibility Timeout)

When a retryable error occurs, the consumer adjusts the SQS message's `VisibilityTimeout`. This puts the message back in the queue for later processing. The delay grows exponentially based on the receive count, with optional jitter to prevent thundering herds.

### 2. Idempotency Lock Release

To ensure messages can be reprocessed immediately on redelivery, the idempotency lock is safely released on failure. A unique worker token is used during acquisition and release via Lua script in Redis. This prevents race conditions where a delayed worker releases a lock acquired by a retry worker.

### 3. DLQ Quarantine (Redrive & Poison)

Messages are quarantined to the Dead-Letter Queue (DLQ) in two scenarios:
1. **Redrive Policy Exceeded**: A message exceeds the `max_receive_count` defined in the SQS Redrive Policy.
2. **Immediate Quarantine**: A `NonRetryableEventError` occurs, bypassing the retry loop.

Messages in the DLQ are wrapped in a `DeadLetterEnvelope` containing:
- The original payload
- The failure reason and exception type
- Correlation and causation IDs
- Receive count at failure

## Operator CLI for DLQ Replay

Operators can manage the DLQ using the CLI embedded in `dlq.py`.

```bash
# Inspect the top 10 messages in the DLQ
python -m app.messaging.dlq inspect --dlq https://sqs.../dlq

# Dry-run replay of messages
python -m app.messaging.dlq dry-run --dlq https://sqs.../dlq --target https://sqs.../events

# Replay messages back to the main queue
python -m app.messaging.dlq replay --dlq https://sqs.../dlq --target https://sqs.../events
```

