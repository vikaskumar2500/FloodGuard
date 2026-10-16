# FloodGuard Chaos Engineering Architecture

## 1. Overview
FloodGuard's resilience testing employs a lightweight Fault Injection Architecture designed to artificially introduce network faults, timeouts, and resource unavailability within bounded testing boundaries without polluting production paths.

## 2. Fault Injection Architecture
The core is an application-agnostic fault dictionary (implemented as `performance/chaos/controller.py`) mapping target dependencies to `FaultScenario` definitions. Fault actions include:
*   `FAIL_ONCE`
*   `FAIL_N_TIMES`
*   `TIMEOUT`
*   `DELAY`
*   `UNAVAILABLE`

The integration relies on dependency inversion (e.g., passing `ChaosFakeRedis` or `ChaosSqsTransport` in the application state during testing) to simulate outages without altering the domain logic.

## 3. Experiment Matrix
| Scenario | Component | Action | Verification |
|---|---|---|---|
| POSTGRES_OUTAGE | PostgreSQL | `UNAVAILABLE` | Graceful startup failure / healthcheck Liveness=True, Readiness=False |
| REDIS_CACHE_LOSS | Redis | `FAIL_N_TIMES` | Fallback to deterministic routing, log `route_cache_read_error` |
| SQS_PUBLISH_FAIL | SQS Publisher | `FAIL_ONCE` | `record_publish_error` metric emitted, DLQ/retry pipeline handles it |
| BEDROCK_TIMEOUT | LLM Assistant | `TIMEOUT` | Graceful fallback to static reasoning without dropping core routes |
| ML_ARTIFACT_MISSING | ML Prediction | `UNAVAILABLE` | Revert to `SHADOW`/deterministic routing with explicit provenance warning |

## 4. Safety Restrictions
*   All faults MUST NOT target physical production resources.
*   Chaos clients (e.g., `ChaosFakeRedis`) are strictly injected at testing time.
*   Fault scenarios MUST auto-clear or explicitly teardown upon completion.
*   Results are strictly labeled by environment (e.g., `UNIT_FAKE`, `IN_MEMORY_SIMULATION`).

## 5. Recovery Procedures
Every experiment automatically restores the injected fault upon exit via Context Manager or explicit `cleanup()` invocations, ensuring that post-recovery smoke requests succeed to validate application healing.
