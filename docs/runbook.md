# FloodGuard Runbook
1. Check `dashboard.json` for high-level metrics.
2. If `DLQDepthCritical` triggers, check SQS DLQ and replay events.
3. If `HighRoutingLatency` triggers, check DB or Graph Cache status.
4. Scale up the ML inference pods if latency > 200ms.
