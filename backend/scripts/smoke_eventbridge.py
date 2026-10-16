"""Explicit dev-only AWS smoke: accepted weather event with no affected road edges."""

import argparse
import asyncio
import json
import time

import boto3

from app.messaging.eventbridge.adapter import EventBridgeSqsMessageAdapter
from app.messaging.eventbridge.client import Boto3EventBridgeClient
from app.messaging.eventbridge.publisher import EventBridgeEventPublisher
from app.messaging.models import create_weather_observed_event


async def smoke(args):
    if "dev" not in args.bus_name.split("-") or "dev" not in args.queue_url.rsplit("/", 1)[
        -1
    ].split("-"):
        raise ValueError("Smoke test requires explicit dev bus and dev queue names")
    sqs = boto3.client("sqs", region_name=args.region)
    event = create_weather_observed_event(0, 0, 0, road_edge_ids=[], producer="phase15.smoke")
    result = await EventBridgeEventPublisher(
        Boto3EventBridgeClient(args.region),
        args.bus_name,
    ).publish(event)
    if not result.success:
        raise RuntimeError(f"FAIL: PutEvents rejected: {result.error_code}")
    deadline = time.monotonic() + 30
    adapter = EventBridgeSqsMessageAdapter()
    while time.monotonic() < deadline:
        response = await asyncio.to_thread(
            sqs.receive_message, QueueUrl=args.queue_url, WaitTimeSeconds=2, MaxNumberOfMessages=10
        )
        found = None
        for message in response.get("Messages", []):
            try:
                adapted = adapter.deserialize(message["Body"])
                is_test = adapted.envelope.event_id == event.event_id
            except Exception:
                is_test = False
            if is_test:
                found = message
                await asyncio.to_thread(
                    sqs.delete_message,
                    QueueUrl=args.queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
            else:
                await asyncio.to_thread(
                    sqs.change_message_visibility,
                    QueueUrl=args.queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                    VisibilityTimeout=0,
                )
        if found:
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "domain_event_id": event.event_id,
                        "eventbridge_event_id": result.eventbridge_event_id,
                        "sqs_message_id": found["MessageId"],
                    }
                )
            )
            return
    raise RuntimeError("FAIL: test event not observed in SQS within 30 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-name", required=True)
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--region", required=True)
    asyncio.run(smoke(parser.parse_args()))


if __name__ == "__main__":
    main()
