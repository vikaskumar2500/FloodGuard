"""JSON serializer and schema validator for transport envelopes."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.messaging.envelope import TransportEnvelope

logger = logging.getLogger("floodguard.messaging.serializer")

CURRENT_EVENT_VERSION = 1


class MessagingSerializationError(Exception):
    """Base exception for serialization failures."""


class DeserializationError(MessagingSerializationError):
    """Raised when JSON parsing or envelope schema validation fails."""


class UnsupportedVersionError(MessagingSerializationError):
    """Raised when envelope carries an incompatible event version."""

    def __init__(self, version: int, supported: int = CURRENT_EVENT_VERSION) -> None:
        super().__init__(f"Unsupported event version {version}; currently supported is {supported}")
        self.version = version
        self.supported = supported


class _DualMethod:
    def __init__(self, fn: Any) -> None:
        self.fn = fn
        self.__doc__ = getattr(fn, "__doc__", "")

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        target = obj if obj is not None else objtype
        return lambda *args, **kwargs: self.fn(target, *args, **kwargs)


class EventSerializer:
    """Serializes and deserializes TransportEnvelope to and from JSON."""

    supported_version: int = CURRENT_EVENT_VERSION

    def __init__(self, supported_version: int = CURRENT_EVENT_VERSION) -> None:
        self.supported_version = supported_version

    @_DualMethod
    def serialize(self_or_cls: Any, envelope: TransportEnvelope) -> str:
        """Serialize a TransportEnvelope into a canonical JSON string."""
        try:
            return json.dumps(envelope.to_dict(), separators=(",", ":"), ensure_ascii=False)
        except Exception as err:
            raise MessagingSerializationError(f"Failed to serialize envelope: {err}") from err

    @_DualMethod
    def deserialize(self_or_cls: Any, raw_json: str) -> TransportEnvelope:
        """Parse raw JSON string into a validated TransportEnvelope."""
        if not raw_json or not isinstance(raw_json, str):
            raise DeserializationError("Empty or non-string message body received")

        try:
            data: Any = json.loads(raw_json)
        except json.JSONDecodeError as err:
            raise DeserializationError(f"Malformed JSON in message body: {err}") from err

        if not isinstance(data, dict):
            raise DeserializationError(
                f"Expected JSON object in message body, got {type(data).__name__}"
            )

        # Validate mandatory envelope attributes
        required_fields = ("eventId", "eventType", "occurredAt")
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise DeserializationError(f"Missing required envelope field(s): {', '.join(missing)}")

        supported = getattr(self_or_cls, "supported_version", CURRENT_EVENT_VERSION)
        version = int(data.get("eventVersion", 1))
        if version > supported or version < 1:
            raise UnsupportedVersionError(version=version, supported=supported)

        try:
            return TransportEnvelope.from_dict(data)
        except Exception as err:
            raise DeserializationError(f"Invalid envelope contents: {err}") from err
