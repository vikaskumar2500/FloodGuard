"""Deliberately small dev emulator: exact-value patterns, independent targets, no retries."""

import copy
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.messaging.eventbridge.rules import processing_rules
from app.messaging.metrics import MessagingMetrics
from app.messaging.sqs.client import SqsClientInterface

Target = Callable[[dict[str, Any]], Awaitable[None]]


def matches(pattern: dict, event: dict) -> bool:
    for key, expected in pattern.items():
        if key not in event:
            return False
        actual = event[key]
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or not matches(expected, actual):
                return False
        elif isinstance(expected, list):
            if not any(type(actual) is type(value) and actual == value for value in expected):
                return False
        else:
            raise ValueError("Only nested objects and exact-value lists are supported")
    return True


class InMemoryAuditTarget:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(copy.deepcopy(event["detail"]))


class SqsTarget:
    def __init__(self, client: SqsClientInterface, queue_url: str) -> None:
        self.client, self.queue_url = client, queue_url

    async def __call__(self, event: dict) -> None:
        await self.client.send_message(
            queue_url=self.queue_url,
            message_body=json.dumps(event, ensure_ascii=False),
        )


class InMemoryEventBridge:
    def __init__(self, metrics: MessagingMetrics | None = None) -> None:
        self.metrics = metrics or MessagingMetrics()
        self.buses: dict[str, dict[str, tuple[dict, dict[str, Target]]]] = {}
        self.requests: list[list[dict]] = []
        self.deliveries: list[dict] = []
        self.fail_event_ids: set[str] = set()
        self.fail_api = False

    def create_bus(self, name: str) -> None:
        self.buses.setdefault(name, {})

    def put_rule(self, bus: str, name: str, pattern: dict, targets: dict[str, Target]) -> None:
        self.buses[bus][name] = (copy.deepcopy(pattern), dict(targets))

    def configure_processing(
        self, bus: str, sqs: SqsTarget, audit: Target | None = None, source: str = "com.floodguard"
    ) -> None:
        self.create_bus(bus)
        for name, pattern in processing_rules(source).items():
            targets = {"processing-sqs": sqs}
            if audit and name.endswith("environment-events"):
                targets["development-audit"] = audit
            self.put_rule(bus, name, pattern, targets)

    async def put_events(self, *, Entries: list[dict]) -> dict:
        self.requests.append(copy.deepcopy(Entries))
        if self.fail_api:
            raise ConnectionError("Simulated PutEvents outage")
        results = []
        for entry in Entries:
            detail = json.loads(entry["Detail"])
            if detail["eventId"] in self.fail_event_ids:
                results.append({"ErrorCode": "InternalFailure"})
                continue
            event_id = str(uuid4())
            results.append({"EventId": event_id})
            outer = {
                "version": "0",
                "id": event_id,
                "source": entry["Source"],
                "detail-type": entry["DetailType"],
                "detail": detail,
                "time": datetime.now(UTC).isoformat(),
                "account": "000000000000",
                "region": "local",
                "resources": [],
            }
            reached = matched = 0
            for name, (pattern, targets) in self.buses.get(entry["EventBusName"], {}).items():
                if not matches(pattern, outer):
                    continue
                matched += 1
                for target_id, target in targets.items():
                    start = time.perf_counter()
                    try:
                        await target(copy.deepcopy(outer))
                        reached += 1
                        self.deliveries.append(
                            {
                                "domain_event_id": detail["eventId"],
                                "target": target_id,
                                "rule": name,
                                "latency_ms": (time.perf_counter() - start) * 1000,
                            }
                        )
                    except Exception:
                        self.metrics.increment("eventbridge_target_errors_total")
            if not matched:
                self.metrics.increment("eventbridge_unmatched_total")
            self.metrics.increment("eventbridge_events_routed_total", int(reached > 0))
            self.metrics.increment("eventbridge_fanout_total", reached)
        return {"Entries": results, "FailedEntryCount": sum("ErrorCode" in r for r in results)}
