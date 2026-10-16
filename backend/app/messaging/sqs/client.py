"""SQS Client abstraction and implementations (boto3 async wrapper & in-memory simulator)."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

logger = logging.getLogger("floodguard.messaging.sqs.client")


class SqsClientError(Exception):
    """Base error for SQS client interactions."""


class QueueDoesNotExistError(SqsClientError):
    """Raised when target queue URL is invalid or does not exist."""


class SqsClientInterface(ABC):
    """Abstract interface for SQS client operations."""

    @abstractmethod
    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a message to the specified queue."""

    @abstractmethod
    async def receive_messages(
        self,
        queue_url: str,
        max_number_of_messages: int = 10,
        wait_time_seconds: int = 20,
        visibility_timeout: int = 60,
    ) -> list[dict[str, Any]]:
        """Receive a batch of messages from the queue using long polling."""

    @abstractmethod
    async def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        """Delete a message from the queue after successful processing."""

    @abstractmethod
    async def change_message_visibility(
        self, queue_url: str, receipt_handle: str, visibility_timeout: int
    ) -> None:
        """Change the visibility timeout of a received message."""


class Boto3SqsClient(SqsClientInterface):
    """Production SQS client wrapping boto3 calls in asyncio.to_thread."""

    def __init__(
        self,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        boto3_client: Any = None,
    ) -> None:
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        if boto3_client is not None:
            self._client = boto3_client
        else:
            import boto3

            self._client = boto3.client(
                "sqs",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )

    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": message_body,
        }
        if message_attributes:
            params["MessageAttributes"] = message_attributes
        try:
            return await asyncio.to_thread(self._client.send_message, **params)
        except Exception as err:
            raise SqsClientError(f"Failed to send SQS message: {err}") from err

    async def receive_messages(
        self,
        queue_url: str,
        max_number_of_messages: int = 10,
        wait_time_seconds: int = 20,
        visibility_timeout: int = 60,
    ) -> list[dict[str, Any]]:
        params = {
            "QueueUrl": queue_url,
            "MaxNumberOfMessages": max(1, min(10, max_number_of_messages)),
            "WaitTimeSeconds": max(0, min(20, wait_time_seconds)),
            "VisibilityTimeout": visibility_timeout,
            "AttributeNames": ["All"],
            "MessageAttributeNames": ["All"],
        }
        try:
            resp = await asyncio.to_thread(self._client.receive_message, **params)
            return resp.get("Messages", [])
        except Exception as err:
            raise SqsClientError(f"Failed to receive SQS messages: {err}") from err

    async def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_message,
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            )
        except Exception as err:
            raise SqsClientError(f"Failed to delete SQS message: {err}") from err

    async def change_message_visibility(
        self, queue_url: str, receipt_handle: str, visibility_timeout: int
    ) -> None:
        try:
            await asyncio.to_thread(
                self._client.change_message_visibility,
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
        except Exception as err:
            raise SqsClientError(f"Failed to change SQS message visibility: {err}") from err


@dataclass
class _InMemoryMessage:
    message_id: str
    body: str
    attributes: dict[str, Any]
    message_attributes: dict[str, Any]
    receipt_handle: str | None = None
    visible_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    receive_count: int = 0


class InMemorySqsTransport(SqsClientInterface):
    """High-fidelity in-memory SQS queue simulator for local unit and integration tests.

    Provides exact SQS visibility timeout, receive count, and receipt handle semantics.
    """

    def __init__(self) -> None:
        self.queues: dict[str, list[_InMemoryMessage]] = {}
        self.redrive_policies: dict[str, dict] = {}
        self.fail_next: bool = False
        self._lock = asyncio.Lock()

    def configure_redrive(self, queue_url: str, dlq_url: str, max_receive_count: int) -> None:
        self.redrive_policies[queue_url] = {
            "dlq_url": dlq_url,
            "max_receive_count": max_receive_count,
        }
        self.create_queue(queue_url)
        self.create_queue(dlq_url)

    def create_queue(self, queue_url: str) -> None:
        if queue_url not in self.queues:
            self.queues[queue_url] = []

    def get_queue_length(self, queue_url: str) -> int:
        return len(self.queues.get(queue_url, []))

    def simulate_failure(self, fail: bool = True) -> None:
        self.fail_next = fail

    async def send_message(
        self,
        queue_url: str | None = None,
        message_body: str | None = None,
        message_attributes: dict[str, Any] | None = None,
        *,
        QueueUrl: str | None = None,
        MessageBody: str | None = None,
        MessageAttributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.fail_next:
            raise SqsClientError("Simulated SQS service unavailable")

        target_queue = queue_url or QueueUrl or ""
        body = message_body if message_body is not None else (MessageBody or "")
        attrs = message_attributes or MessageAttributes

        async with self._lock:
            if target_queue not in self.queues:
                self.queues[target_queue] = []

            msg_id = str(uuid4())
            msg = _InMemoryMessage(
                message_id=msg_id,
                body=body,
                attributes={"ApproximateReceiveCount": "0"},
                message_attributes=attrs or {},
                visible_at=datetime.now(UTC),
            )
            self.queues[target_queue].append(msg)
            return {"MessageId": msg_id}

    async def receive_messages(
        self,
        queue_url: str,
        max_number_of_messages: int = 10,
        wait_time_seconds: int = 0,
        visibility_timeout: int = 60,
    ) -> list[dict[str, Any]]:
        if self.fail_next:
            raise SqsClientError("Simulated SQS service unavailable")

        t_end = time.perf_counter() + (wait_time_seconds if wait_time_seconds > 0 else 0)

        while True:
            async with self._lock:
                now = datetime.now(UTC)
                messages = self.queues.get(queue_url, [])
                ready_msgs = [m for m in messages if m.visible_at <= now]

                if ready_msgs:
                    selected = ready_msgs[:max_number_of_messages]
                    result: list[dict[str, Any]] = []
                    for m in selected:
                        policy = self.redrive_policies.get(queue_url)
                        if policy and m.receive_count >= policy["max_receive_count"]:
                            # Move to DLQ
                            self.queues[queue_url].remove(m)
                            m.receive_count = 0
                            m.visible_at = now
                            m.attributes["ApproximateReceiveCount"] = "0"
                            if policy["dlq_url"] not in self.queues:
                                self.queues[policy["dlq_url"]] = []
                            self.queues[policy["dlq_url"]].append(m)
                            continue

                        m.receive_count += 1
                        m.receipt_handle = str(uuid4())
                        m.visible_at = now + timedelta(seconds=visibility_timeout)
                        m.attributes["ApproximateReceiveCount"] = str(m.receive_count)

                        sqs_envelope = {
                            "MessageId": m.message_id,
                            "ReceiptHandle": m.receipt_handle,
                            "Body": m.body,
                            "Attributes": m.attributes.copy(),
                            "MessageAttributes": m.message_attributes.copy(),
                        }
                        result.append(sqs_envelope)
                    return result

            # If waiting and nothing ready, wait briefly or timeout
            if time.perf_counter() >= t_end:
                return []
            await asyncio.sleep(0.02)

    async def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        if self.fail_next:
            raise SqsClientError("Simulated SQS service unavailable")

        async with self._lock:
            messages = self.queues.get(queue_url, [])
            for idx, m in enumerate(messages):
                if m.receipt_handle == receipt_handle:
                    del messages[idx]
                    return

    async def change_message_visibility(
        self, queue_url: str, receipt_handle: str, visibility_timeout: int
    ) -> None:
        if self.fail_next:
            raise SqsClientError("Simulated SQS service unavailable")

        async with self._lock:
            messages = self.queues.get(queue_url, [])
            now = datetime.now(UTC)
            for m in messages:
                if m.receipt_handle == receipt_handle:
                    m.visible_at = now + timedelta(seconds=visibility_timeout)
                    return
