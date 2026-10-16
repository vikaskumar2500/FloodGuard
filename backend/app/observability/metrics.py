from collections import defaultdict

_metrics = defaultdict(int)


def record_metric(name: str, value: float = 1.0, tags: dict = None) -> None:
    if tags is None:
        tags = {}

    tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
    key = f"{name}[{tag_str}]"
    _metrics[key] += value


def get_metrics() -> dict:
    return dict(_metrics)


def reset_metrics() -> None:
    _metrics.clear()


class HTTPMetrics:
    @staticmethod
    def record_request(method: str, status: int, latency: float) -> None:
        tags = {"method": method, "status": str(status)}
        record_metric("http_requests_total", 1, tags)
        record_metric("http_request_duration_seconds", latency, tags)


class RoutingMetrics:
    @staticmethod
    def record_calculation(algorithm: str, status: str) -> None:
        tags = {"algorithm": algorithm, "status": status}
        record_metric("routing_calculations_total", 1, tags)


class RiskMetrics:
    @staticmethod
    def record_evaluation(status: str) -> None:
        tags = {"status": status}
        record_metric("risk_evaluations_total", 1, tags)


class QueueMetrics:
    @staticmethod
    def record_enqueue(queue: str, status: str) -> None:
        tags = {"queue": queue, "status": status}
        record_metric("sqs_enqueue_total", 1, tags)


class MLMetrics:
    @staticmethod
    def record_inference(model: str, status: str) -> None:
        tags = {"model": model, "status": status}
        record_metric("ml_inference_total", 1, tags)
