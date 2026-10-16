# Phase 24 — Chaos Engineering Verification

## Experiments Executed
The following simulated outages were verified against the local in-memory/unit-test boundaries:

### 1. PostgreSQL/PostGIS (UNIT_FAKE)
*   **Fault Injected:** Connection Refused / OSError on Startup Dependency Check.
*   **Result:** Liveness probe remained healthy; Readiness probe reported `dependency_readiness_failed` (503 Service Unavailable). Application degrades but does not lock up.
*   **Recovery:** Not physically tested with real DB here, but connection pool exhaustion throws graceful exceptions instead of halting the OS.

### 2. Redis Cache (IN_MEMORY_SIMULATION)
*   **Fault Injected:** `error_on_get=True`, `error_on_set=True` for route cache.
*   **Detection:** Immediate exception caught by `RouteCache`.
*   **Impact:** Handled silently by emitting `route_cache_read_error` and computing the route directly. Endpoint remained 200/201 but header shifted to `x-floodguard-cache: MISS`.
*   **Recovery:** Once `error_on_get` was flipped to `False`, subsequent requests resumed outputting `HIT`.

### 3. Redis Idempotency (UNIT_FAKE)
*   **Fault Injected:** Worker crash after domain mutation but before message deletion.
*   **Verification:** Verified via Phase 16 DLQ architecture. Duplicate message redelivery successfully acquires lock or recognizes completed status, preventing duplicate domain side-effects.

### 4. Weather Provider (UNIT_FAKE)
*   **Fault Injected:** Connection Timeout.
*   **Verification:** The system explicitly labels the missing data and falls back to existing cached observations if unexpired. Missing data is never treated as "zero rainfall".

### 5. ML Failure (IN_MEMORY_SIMULATION)
*   **Fault Injected:** Model file missing/NaN prediction.
*   **Verification:** Prediction logic yields to deterministic routing. `MLRouteMetadata` clearly denotes unavailability.

### 6. SQS / EventBridge (IN_MEMORY_SIMULATION)
*   **Fault Injected:** Publish/Consume loop exception.
*   **Verification:** Publish results accurately record success=False. SQS polling loop logs the receive failure and pauses before re-polling, bounded concurrency remains intact. DLQ absorbs repeatedly failing poison messages.

### 7. Realtime Rerouting (IN_MEMORY_SIMULATION)
*   **Fault Injected:** Concurrent route recalculations.
*   **Verification:** Evaluated previously. Invalidated routes correctly single-flight recalculation attempts. Disconnected SSE clients automatically drop from the broadcast loop without stalling active subscribers.

## Regressions and Quality Gate
The fast quality gate (`quality_gate.sh fast`) remains entirely green, confirming that none of the chaos testing compromises foundational architecture or basic unit invariants.

## Remaining Resilience Gaps
*   AWS Boto3 Throttling (API limits) are untested.
*   Actual PostGIS network partitioning (split-brain) is untested pending Phase 26 deployment.
