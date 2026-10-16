"""Explicitly distinguish direct canonical SQS messages from EventBridge deliveries."""

import json
from dataclasses import dataclass
from datetime import datetime

from app.messaging.envelope import TransportEnvelope
from app.messaging.metrics import MessagingMetrics
from app.messaging.serializer import DeserializationError, EventSerializer, UnsupportedVersionError


@dataclass(frozen=True)
class AdaptedMessage:
    envelope: TransportEnvelope
    eventbridge_event_id: str | None = None


class EventBridgeSqsMessageAdapter:
    def __init__(
        self,
        serializer: EventSerializer | None = None,
        metrics: MessagingMetrics | None = None,
    ) -> None:
        self.serializer = serializer or EventSerializer()
        self.metrics = metrics or MessagingMetrics()

    def deserialize(self, body: str) -> AdaptedMessage:
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Message must be an object")
            outer_keys = {"version", "detail-type", "detail", "source", "resources", "account"}
            if not outer_keys.intersection(data):
                if not {"eventId", "eventType", "occurredAt"}.issubset(data):
                    raise ValueError("Unrecognized message shape")
                return AdaptedMessage(self.serializer.deserialize(body))
            required_strings = ("id", "source", "detail-type", "account", "region", "time")
            if data.get("version") != "0" or any(
                not isinstance(data.get(key), str) or not data[key] for key in required_strings
            ):
                raise ValueError("Invalid EventBridge metadata")
            timestamp = datetime.fromisoformat(data["time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("EventBridge time requires timezone")
            if not isinstance(data.get("resources"), list) or not all(
                isinstance(item, str) for item in data["resources"]
            ):
                raise ValueError("Invalid EventBridge resources")
            detail = data.get("detail")
            required = {
                "eventId",
                "eventType",
                "eventVersion",
                "occurredAt",
                "producer",
                "correlationId",
                "causationId",
                "payload",
            }
            if not isinstance(detail, dict) or not required.issubset(detail):
                raise ValueError("EventBridge detail must contain the canonical envelope")
            if "eventId" in data or detail["eventType"] != data["detail-type"]:
                raise ValueError("Ambiguous or mismatched EventBridge envelope")
            if (
                any(
                    not isinstance(detail[key], str) or not detail[key]
                    for key in ("eventId", "eventType", "occurredAt", "producer", "correlationId")
                )
                or type(detail["eventVersion"]) is not int
            ):
                raise ValueError("Invalid canonical metadata")
            if not isinstance(detail["payload"], dict) or (
                detail["causationId"] is not None and not isinstance(detail["causationId"], str)
            ):
                raise ValueError("Invalid canonical detail")
            envelope = self.serializer.deserialize(json.dumps(detail))
            return AdaptedMessage(envelope, data["id"])
        except UnsupportedVersionError:
            self.metrics.increment("eventbridge_adapter_errors_total")
            raise
        except (ValueError, TypeError, DeserializationError) as error:
            self.metrics.increment("eventbridge_adapter_errors_total")
            raise DeserializationError("Invalid SQS canonical/EventBridge message") from error
