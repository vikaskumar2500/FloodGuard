SLO_TARGETS = {
    "routing_latency_p95_ms": 200,
    "dlq_depth_max": 100,
    "error_rate_percent": 1.0,
}

ALERTS = [
    {
        "name": "HighRoutingLatency",
        "condition": "routing_latency_p95_ms > 200",
        "severity": "warning",
    },
    {"name": "DLQDepthCritical", "condition": "dlq_depth_max > 500", "severity": "critical"},
    {"name": "ErrorRateHigh", "condition": "error_rate_percent > 5.0", "severity": "critical"},
]


def check_alerts(current_metrics: dict) -> list:
    triggered = []
    # Simplified alert checking logic
    if current_metrics.get("routing_latency_p95_ms", 0) > SLO_TARGETS["routing_latency_p95_ms"]:
        triggered.append("HighRoutingLatency")
    return triggered
