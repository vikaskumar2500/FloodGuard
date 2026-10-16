"""AWS SQS long-polling consumer with bounded concurrency, idempotency, and retry safety."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.messaging.consumer import HandlerRegistry
from app.messaging.eventbridge.adapter import EventBridgeSqsMessageAdapter
from app.messaging.idempotency import IdempotencyStatus, RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics
from app.messaging.serializer import (
    DeserializationError,
    EventSerializer,
    UnsupportedVersionError,
)
from app.messaging.sqs.client import SqsClientInterface

logger = logging.getLogger("floodguard.messaging.sqs.consumer")


class SqsEventConsumer:
    """Consumes and dispatches domain events from an AWS SQS queue."""

    def __init__(
        self,
        client: SqsClientInterface,
        queue_url: str,
        registry: HandlerRegistry,
        idempotency: RedisIdempotencyStore | None = None,
        serializer: EventSerializer | None = None,
        metrics: MessagingMetrics | None = None,
        poll_wait_seconds: int = 20,
        max_messages: int = 10,
        visibility_timeout: int = 60,
        concurrency: int = 5,
        *,
        idempotency_store: RedisIdempotencyStore | None = None,
        wait_time_seconds: int | None = None,
        message_adapter: EventBridgeSqsMessageAdapter | None = None,
    ) -> None:
        self.client = client
        self.queue_url = queue_url
        self.registry = registry
        self.idempotency = idempotency or idempotency_store or RedisIdempotencyStore(None)
        self.serializer = serializer or EventSerializer()
        self.metrics = metrics or MessagingMetrics()
        self.message_adapter = message_adapter or EventBridgeSqsMessageAdapter(
            self.serializer, self.metrics
        )
        wait = wait_time_seconds if wait_time_seconds is not None else poll_wait_seconds
        self.poll_wait_seconds = max(0, min(20, wait))
        self.max_messages = max(1, min(10, max_messages))
        self.visibility_timeout = visibility_timeout
        self.concurrency = concurrency

        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_poll_at: datetime | None = None
        self._last_processed_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_poll_at(self) -> datetime | None:
        return self._last_poll_at

    @property
    def last_processed_at(self) -> datetime | None:
        return self._last_processed_at

    def start(self) -> asyncio.Task[None]:
        """Start background consumer task."""
        if self._running:
            raise RuntimeError("Consumer is already running")
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="sqs_event_consumer")
        logger.info(
            "SQS consumer started on queue %s (concurrency=%d, max_messages=%d, wait=%ds)",
            self.queue_url,
            self.concurrency,
            self.max_messages,
            self.poll_wait_seconds,
        )
        return self._task

    async def stop(self) -> None:
        """Gracefully stop consumer loop and await pending messages."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SQS consumer stopped cleanly.")

    async def poll_once(self) -> int:
        """Execute one long-poll cycle. Returns number of messages processed."""
        self._last_poll_at = datetime.now(UTC)
        try:
            raw_messages = await self.client.receive_messages(
                queue_url=self.queue_url,
                max_number_of_messages=self.max_messages,
                wait_time_seconds=self.poll_wait_seconds,
                visibility_timeout=self.visibility_timeout,
            )
        except Exception as err:
            self.metrics.record_consumer_loop_error()
            logger.error("SQS receive_messages failed on queue %s: %s", self.queue_url, err)
            return 0

        if not raw_messages:
            return 0

        self.metrics.record_received(len(raw_messages))

        # Process received messages concurrently with bounded semaphore
        tasks = [asyncio.create_task(self._process_message_guarded(msg)) for msg in raw_messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed_count = sum(1 for r in results if r is True)
        return processed_count

    async def _run_loop(self) -> None:
        """Continuous polling loop."""
        while self._running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as err:
                self.metrics.record_consumer_loop_error()
                logger.error("Unexpected error in SQS consumer loop: %s", err)
                await asyncio.sleep(1.0)

    async def _process_message_guarded(self, sqs_msg: dict[str, Any]) -> bool:
        """Process a message within the concurrency semaphore."""
        async with self._semaphore:
            return await self._process_single_message(sqs_msg)

    async def _process_single_message(self, sqs_msg: dict[str, Any]) -> bool:
        """Process one raw SQS message, validating envelope, idempotency, and executing handler."""
        import asyncio
        import uuid

        from app.core.config import get_settings
        from app.messaging.dlq import DeadLetterPublisher, compute_retry_visibility_timeout
        from app.messaging.errors import (
            EventProcessingError,
            FailureCategory,
            NonRetryableEventError,
            RetryableEventError,
        )

        settings = get_settings()
        message_id = sqs_msg.get("MessageId", "unknown")
        receipt_handle = sqs_msg.get("ReceiptHandle", "")
        body = sqs_msg.get("Body", "")
        attributes = sqs_msg.get("Attributes", {})
        receive_count = int(attributes.get("ApproximateReceiveCount", 1))

        # Quarantine helper
        async def quarantine(
            reason: str,
            category: FailureCategory,
            exception_type: str | None = None,
            event_id: str | None = None,
            correlation_id: str | None = None,
        ):
            if settings.sqs_dlq_url:
                dlq = DeadLetterPublisher(self.client, settings.sqs_dlq_url)
                await dlq.publish(
                    original_body=body,
                    reason=reason,
                    category=category,
                    receive_count=receive_count,
                    exception_type=exception_type,
                    correlation_id=correlation_id,
                    event_id=event_id,
                )
            # Acknowledge & delete poison message from primary queue
            if receipt_handle:
                try:
                    await self.client.delete_message(self.queue_url, receipt_handle)
                    self.metrics.record_deleted()
                except Exception:
                    pass
            # Mark dead lettered in idempotency
            if event_id:
                try:
                    await self.idempotency.mark_dead_lettered(event_id, correlation_id)
                except AttributeError:
                    pass  # test mock fallback

        # 1. Deserialization & validation
        try:
            adapted = self.message_adapter.deserialize(body)
            envelope = adapted.envelope
        except DeserializationError as err:
            self.metrics.record_deserialization_error()
            logger.error(
                "Malformed message body in message %s: %s",
                message_id,
                err,
                extra={"message_id": message_id, "receive_count": receive_count},
            )
            await quarantine(
                "Malformed message body", FailureCategory.NON_RETRYABLE, "DeserializationError"
            )
            return False

        except UnsupportedVersionError as err:
            self.metrics.record_unsupported_version()
            logger.error(
                "unsupported_event_version: %s in message %s",
                err,
                message_id,
                extra={"message_id": message_id, "version": getattr(err, "version", None)},
            )
            await quarantine(
                "Unsupported event version",
                FailureCategory.NON_RETRYABLE,
                "UnsupportedVersionError",
            )
            return False

        event = envelope.to_domain()
        trace = {
            "domain_event_id": event.event_id,
            "eventbridge_event_id": adapted.eventbridge_event_id,
            "sqs_message_id": message_id,
        }

        # 2. Handler lookup
        handler = self.registry.get(event.event_type)
        if handler is None:
            self.metrics.record_unknown_event_type()
            logger.warning(
                "Unknown event type '%s' in event %s; deleting unhandled message",
                event.event_type,
                event.event_id,
                extra={
                    "event_id": event.event_id,
                    **trace,
                    "event_type": event.event_type,
                    "correlation_id": event.correlation_id,
                    "message_id": message_id,
                },
            )
            await quarantine(
                "Unknown event type",
                FailureCategory.NON_RETRYABLE,
                "UnknownEventTypeError",
                event.event_id,
                event.correlation_id,
            )
            return False

        worker_token = str(uuid.uuid4())

        # 3. Idempotency Check
        try:
            idempotency_status = await self.idempotency.try_acquire(
                event.event_id, correlation_id=event.correlation_id, token=worker_token
            )
        except TypeError:
            # tests using older mock
            idempotency_status = await self.idempotency.try_acquire(
                event.event_id, correlation_id=event.correlation_id
            )
        except Exception:
            # Idempotency store failure means we should retry later rather than risk duplicates
            logger.warning(
                "Idempotency store failed for event %s, treating as RETRYABLE", event.event_id
            )
            if receipt_handle:
                try:
                    delay = compute_retry_visibility_timeout(
                        receive_count,
                        settings.sqs_retry_base_delay_seconds,
                        settings.sqs_retry_max_delay_seconds,
                        settings.sqs_retry_jitter,
                    )
                    await self.client.change_message_visibility(
                        self.queue_url, receipt_handle, delay
                    )
                except Exception:
                    pass
            return False

        if idempotency_status in (
            IdempotencyStatus.ALREADY_COMPLETED,
            IdempotencyStatus.IN_PROGRESS,
        ):
            self.metrics.record_duplicate()
            logger.info(
                "sqs_duplicate_suppressed",
                extra={
                    "event_id": event.event_id,
                    **trace,
                    "event_type": event.event_type,
                    "correlation_id": event.correlation_id,
                    "message_id": message_id,
                    "receive_count": receive_count,
                    "status": idempotency_status.value,
                },
            )
            if receipt_handle and idempotency_status == IdempotencyStatus.ALREADY_COMPLETED:
                try:
                    await self.client.delete_message(self.queue_url, receipt_handle)
                    self.metrics.record_deleted()
                except Exception:
                    pass
            return False

        # 4. Measure queue delay
        now = datetime.now(UTC)
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        queue_delay_ms = max(0.0, (now - occurred).total_seconds() * 1000.0)

        logger.info(
            "sqs_message_processing_start",
            extra={
                "event_id": event.event_id,
                **trace,
                "event_type": event.event_type,
                "event_version": event.event_version,
                "correlation_id": event.correlation_id,
                "causation_id": event.causation_id,
                "message_id": message_id,
                "receive_count": receive_count,
                "queue_delay_ms": round(queue_delay_ms, 3),
            },
        )

        # 5. Handler Execution
        t0_handler = time.perf_counter()
        try:
            timeout = settings.event_handler_timeout_seconds
            await asyncio.wait_for(handler.handle(event), timeout=timeout)
            elapsed_handler_ms = (time.perf_counter() - t0_handler) * 1000.0

            # 6. Mark Completed & Delete Message
            try:
                await self.idempotency.mark_completed(
                    event.event_id, event.correlation_id, token=worker_token
                )
            except TypeError:
                await self.idempotency.mark_completed(event.event_id, event.correlation_id)

            if receipt_handle:
                await self.client.delete_message(self.queue_url, receipt_handle)
                self.metrics.record_deleted()

            self._last_processed_at = datetime.now(UTC)
            self.metrics.record_processed(elapsed_handler_ms, queue_delay_ms)

            logger.info(
                "sqs_message_processed_success",
                extra={
                    "event_id": event.event_id,
                    **trace,
                    "event_type": event.event_type,
                    "correlation_id": event.correlation_id,
                    "message_id": message_id,
                    "receive_count": receive_count,
                    "handler_latency_ms": round(elapsed_handler_ms, 3),
                    "queue_delay_ms": round(queue_delay_ms, 3),
                },
            )
            return True

        except TimeoutError:
            err = RetryableEventError("Handler execution timed out")
            return await self._handle_processing_error(
                err,
                event,
                trace,
                message_id,
                receipt_handle,
                receive_count,
                t0_handler,
                settings,
                worker_token,
                quarantine_func=quarantine,
            )
        except NonRetryableEventError as err:
            return await self._handle_processing_error(
                err,
                event,
                trace,
                message_id,
                receipt_handle,
                receive_count,
                t0_handler,
                settings,
                worker_token,
                quarantine_func=quarantine,
            )
        except Exception as err:
            if not isinstance(err, EventProcessingError):
                err = RetryableEventError(str(err))
            return await self._handle_processing_error(
                err,
                event,
                trace,
                message_id,
                receipt_handle,
                receive_count,
                t0_handler,
                settings,
                worker_token,
                quarantine_func=quarantine,
            )

    async def _handle_processing_error(
        self,
        err,
        event,
        trace,
        message_id,
        receipt_handle,
        receive_count,
        t0_handler,
        settings,
        worker_token,
        quarantine_func=None,
    ):
        from app.messaging.dlq import compute_retry_visibility_timeout
        from app.messaging.errors import FailureCategory

        elapsed_handler_ms = (time.perf_counter() - t0_handler) * 1000.0
        self.metrics.record_handler_error()

        category = getattr(err, "category", FailureCategory.RETRYABLE)

        logger.error(
            "sqs_message_handler_failed",
            extra={
                "event_id": event.event_id,
                **trace,
                "event_type": event.event_type,
                "correlation_id": event.correlation_id,
                "message_id": message_id,
                "receive_count": receive_count,
                "error": str(err),
                "category": category.value,
                "handler_latency_ms": round(elapsed_handler_ms, 3),
            },
        )

        # Release idempotency lease so message can be retried immediately upon redelivery
        try:
            await self.idempotency.release(event.event_id, token=worker_token)
        except TypeError:
            await self.idempotency.release(event.event_id)

        if category == FailureCategory.NON_RETRYABLE and quarantine_func:
            await quarantine_func(
                str(err), category, type(err).__name__, event.event_id, event.correlation_id
            )
        elif receipt_handle:
            try:
                delay = compute_retry_visibility_timeout(
                    receive_count,
                    settings.sqs_retry_base_delay_seconds,
                    settings.sqs_retry_max_delay_seconds,
                    settings.sqs_retry_jitter,
                )
                await self.client.change_message_visibility(self.queue_url, receipt_handle, delay)
                logger.info(
                    "event_processing_failed",
                    extra={
                        "category": "RETRYABLE",
                        "receive_count": receive_count,
                        "retry_delay": delay,
                    },
                )
            except Exception:
                pass
        return False
