"""Telemetry and observability metrics for asynchronous messaging."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class MessagingMetrics:
    """Thread-safe counters and latency statistics for SQS publisher and consumer."""

    sqs_messages_published_total: int = 0
    sqs_publish_errors_total: int = 0
    sqs_messages_received_total: int = 0
    sqs_messages_processed_total: int = 0
    sqs_messages_deleted_total: int = 0
    sqs_handler_errors_total: int = 0
    sqs_duplicates_total: int = 0
    sqs_deserialization_errors_total: int = 0
    sqs_unsupported_version_total: int = 0
    consumer_loop_errors_total: int = 0
    unknown_event_type_total: int = 0
    idempotency_redis_unavailable_total: int = 0

    eventbridge_publish_total: int = 0
    eventbridge_publish_success_total: int = 0
    eventbridge_publish_failure_total: int = 0
    eventbridge_partial_failure_total: int = 0
    eventbridge_events_routed_total: int = 0
    eventbridge_unmatched_total: int = 0
    eventbridge_fanout_total: int = 0
    eventbridge_adapter_errors_total: int = 0
    eventbridge_oversized_total: int = 0
    eventbridge_target_errors_total: int = 0

    # Latency tracking
    last_publish_latency_ms: float = 0.0
    last_queue_delay_ms: float = 0.0
    last_handler_latency_ms: float = 0.0
    last_end_to_end_latency_ms: float = 0.0

    _publish_latencies: list[float] = field(default_factory=list, repr=False)
    _queue_delays: list[float] = field(default_factory=list, repr=False)
    _handler_latencies: list[float] = field(default_factory=list, repr=False)
    _end_to_end_latencies: list[float] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def increment(self, name: str, count: int = 1) -> None:
        if not name.startswith("eventbridge_") or name not in self.__dataclass_fields__:
            raise ValueError(f"Unknown EventBridge metric: {name}")
        with self._lock:
            setattr(self, name, getattr(self, name) + count)

    def record_published(self, latency_ms: float) -> None:
        with self._lock:
            self.sqs_messages_published_total += 1
            self.last_publish_latency_ms = latency_ms
            self._publish_latencies.append(latency_ms)

    def record_publish_error(self) -> None:
        with self._lock:
            self.sqs_publish_errors_total += 1

    def record_received(self, count: int = 1) -> None:
        with self._lock:
            self.sqs_messages_received_total += count

    def record_processed(self, handler_latency_ms: float, queue_delay_ms: float = 0.0) -> None:
        with self._lock:
            self.sqs_messages_processed_total += 1
            self.last_handler_latency_ms = handler_latency_ms
            self._handler_latencies.append(handler_latency_ms)
            if queue_delay_ms >= 0:
                self.last_queue_delay_ms = queue_delay_ms
                self._queue_delays.append(queue_delay_ms)

    def record_deleted(self, count: int = 1) -> None:
        with self._lock:
            self.sqs_messages_deleted_total += count

    def record_handler_error(self) -> None:
        with self._lock:
            self.sqs_handler_errors_total += 1

    def record_duplicate(self) -> None:
        with self._lock:
            self.sqs_duplicates_total += 1

    def record_deserialization_error(self) -> None:
        with self._lock:
            self.sqs_deserialization_errors_total += 1

    def record_unsupported_version(self) -> None:
        with self._lock:
            self.sqs_unsupported_version_total += 1

    def record_consumer_loop_error(self) -> None:
        with self._lock:
            self.consumer_loop_errors_total += 1

    def record_unknown_event_type(self) -> None:
        with self._lock:
            self.unknown_event_type_total += 1

    def record_end_to_end(self, latency_ms: float) -> None:
        with self._lock:
            self.last_end_to_end_latency_ms = latency_ms
            self._end_to_end_latencies.append(latency_ms)

    def snapshot(self) -> dict[str, float | int]:
        """Return a point-in-time dictionary snapshot of metrics."""
        with self._lock:
            avg_pub = (
                sum(self._publish_latencies) / len(self._publish_latencies)
                if self._publish_latencies
                else 0.0
            )
            avg_delay = (
                sum(self._queue_delays) / len(self._queue_delays) if self._queue_delays else 0.0
            )
            avg_handler = (
                sum(self._handler_latencies) / len(self._handler_latencies)
                if self._handler_latencies
                else 0.0
            )
            return {
                **{
                    name: getattr(self, name)
                    for name in self.__dataclass_fields__
                    if name.startswith("eventbridge_")
                },
                "sqs_messages_published_total": self.sqs_messages_published_total,
                "sqs_publish_errors_total": self.sqs_publish_errors_total,
                "sqs_messages_received_total": self.sqs_messages_received_total,
                "sqs_messages_processed_total": self.sqs_messages_processed_total,
                "sqs_messages_deleted_total": self.sqs_messages_deleted_total,
                "sqs_handler_errors_total": self.sqs_handler_errors_total,
                "sqs_duplicates_total": self.sqs_duplicates_total,
                "sqs_deserialization_errors_total": self.sqs_deserialization_errors_total,
                "sqs_unsupported_version_total": self.sqs_unsupported_version_total,
                "consumer_loop_errors_total": self.consumer_loop_errors_total,
                "unknown_event_type_total": self.unknown_event_type_total,
                "sqs_messages_processed": self.sqs_messages_processed_total,
                "sqs_messages_deleted": self.sqs_messages_deleted_total,
                "sqs_messages_duplicated": self.sqs_duplicates_total,
                "sqs_messages_failed": (
                    self.sqs_handler_errors_total
                    + self.sqs_deserialization_errors_total
                    + self.sqs_unsupported_version_total
                ),
                "avg_publish_latency_ms": round(avg_pub, 3),
                "avg_queue_delay_ms": round(avg_delay, 3),
                "avg_handler_latency_ms": round(avg_handler, 3),
                "last_end_to_end_latency_ms": round(self.last_end_to_end_latency_ms, 3),
            }

    get_snapshot = snapshot
