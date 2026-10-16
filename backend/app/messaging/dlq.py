import argparse
import asyncio
import json
import logging

from app.messaging.errors import DeadLetterEnvelope, FailureCategory
from app.messaging.sqs.client import Boto3SqsClient

logger = logging.getLogger("floodguard.messaging.dlq")


class DeadLetterPublisher:
    """Publishes failed/quarantined messages to the DLQ."""

    def __init__(self, sqs_client, dlq_url: str) -> None:
        self.client = sqs_client
        self.dlq_url = dlq_url

    async def publish(
        self,
        original_body: str | dict,
        reason: str,
        category: FailureCategory,
        receive_count: int,
        exception_type: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        """Wrap the failed message in a DLQ envelope and send it."""
        dlq_payload = DeadLetterEnvelope.create(
            original_message=original_body,
            reason=reason,
            category=category,
            receive_count=receive_count,
            exception_type=exception_type,
            correlation_id=correlation_id,
            event_id=event_id,
        )
        try:
            await self.client.send_message(self.dlq_url, json.dumps(dlq_payload))
            logger.info("Message quarantined to DLQ", extra={"event_id": event_id})
        except Exception as e:
            logger.error("Failed to publish to DLQ: %s", e)


def compute_retry_visibility_timeout(
    receive_count: int, base_delay: int, max_delay: int, jitter: bool
) -> int:
    """Compute exponential backoff visibility timeout."""
    delay = base_delay * (2 ** max(0, receive_count - 1))
    delay = min(delay, max_delay)
    if jitter:
        import random

        delay = int(delay * random.uniform(0.8, 1.2))
    return max(0, delay)


async def _inspect_dlq(dlq_url: str, limit: int = 10):
    client = Boto3SqsClient()
    print(f"Inspecting DLQ: {dlq_url} (limit: {limit})")
    messages = await client.receive_messages(
        dlq_url, max_number_of_messages=limit, wait_time_seconds=5
    )
    print(f"Found {len(messages)} messages in DLQ")
    for m in messages:
        try:
            payload = json.loads(m["Body"])
            print(f"Message ID: {m['MessageId']}")
            print(f"Reason: {payload.get('reason')}")
            print(f"Category: {payload.get('category')}")
            print(f"Original Event ID: {payload.get('eventId')}")
            print("---")
        except:
            print(f"Message ID: {m['MessageId']} (Unparseable body)")


async def _replay_dlq(dlq_url: str, target_queue: str, limit: int = 10, dry_run: bool = False):
    client = Boto3SqsClient()
    messages = await client.receive_messages(
        dlq_url, max_number_of_messages=limit, wait_time_seconds=5
    )
    print(f"Found {len(messages)} messages for replay")

    for m in messages:
        body = m["Body"]
        msg_id = m["MessageId"]
        receipt = m.get("ReceiptHandle")
        try:
            payload = json.loads(body)
            original_body = payload.get("originalMessage", body)
            if isinstance(original_body, dict):
                original_body = json.dumps(original_body)
        except Exception:
            original_body = body

        if dry_run:
            print(f"[DRY-RUN] Would replay msg {msg_id} to {target_queue} and delete from DLQ.")
        else:
            await client.send_message(target_queue, original_body)
            if receipt:
                await client.delete_message(dlq_url, receipt)
            print(f"Replayed msg {msg_id} successfully.")


def main():
    parser = argparse.ArgumentParser(description="FloodGuard DLQ Operator CLI")
    parser.add_argument("action", choices=["inspect", "dry-run", "replay"])
    parser.add_argument("--dlq", required=True, help="DLQ URL")
    parser.add_argument("--target", help="Target queue URL for replay")
    parser.add_argument("--limit", type=int, default=10, help="Max messages to process")

    args = parser.parse_args()

    if args.action == "inspect":
        asyncio.run(_inspect_dlq(args.dlq, args.limit))
    elif args.action == "dry-run":
        if not args.target:
            parser.error("--target is required for dry-run/replay")
        asyncio.run(_replay_dlq(args.dlq, args.target, args.limit, dry_run=True))
    elif args.action == "replay":
        if not args.target:
            parser.error("--target is required for dry-run/replay")
        asyncio.run(_replay_dlq(args.dlq, args.target, args.limit, dry_run=False))


if __name__ == "__main__":
    main()
