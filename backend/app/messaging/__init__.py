"""FloodGuard messaging package for durable asynchronous event processing (Phase 14)."""

from app.messaging.consumer import DomainEventHandler, HandlerRegistry
from app.messaging.envelope import TransportEnvelope
from app.messaging.idempotency import (
    IdempotencyStatus,
    IdempotencyStoreUnavailableError,
    RedisIdempotencyStore,
)
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import (
    EVENT_FLOOD_ZONE_UPDATED,
    EVENT_INCIDENT_REPORTED,
    EVENT_RISK_EDGES_CHANGED,
    EVENT_SENSOR_HEALTH,
    EVENT_SENSOR_WATER_DEPTH,
    EVENT_SIMULATION_EMITTED,
    EVENT_WEATHER_OBSERVED,
    DomainEvent,
    create_risk_edges_changed_event,
    create_sensor_water_depth_event,
    create_simulation_emitted_event,
    create_weather_observed_event,
)
from app.messaging.publisher import (
    EventPublisher,
    InMemoryEventPublisher,
    PublishResult,
)
from app.messaging.serializer import (
    CURRENT_EVENT_VERSION,
    DeserializationError,
    EventSerializer,
    MessagingSerializationError,
    UnsupportedVersionError,
)
from app.messaging.sqs.client import (
    Boto3SqsClient,
    InMemorySqsTransport,
    SqsClientInterface,
)
from app.messaging.sqs.consumer import SqsEventConsumer
from app.messaging.sqs.publisher import SqsEventPublisher

__all__ = [
    "CURRENT_EVENT_VERSION",
    "EVENT_FLOOD_ZONE_UPDATED",
    "EVENT_INCIDENT_REPORTED",
    "EVENT_RISK_EDGES_CHANGED",
    "EVENT_SENSOR_HEALTH",
    "EVENT_SENSOR_WATER_DEPTH",
    "EVENT_SIMULATION_EMITTED",
    "EVENT_WEATHER_OBSERVED",
    "Boto3SqsClient",
    "DeserializationError",
    "DomainEvent",
    "DomainEventHandler",
    "EventPublisher",
    "EventSerializer",
    "HandlerRegistry",
    "IdempotencyStatus",
    "IdempotencyStoreUnavailableError",
    "InMemoryEventPublisher",
    "InMemorySqsTransport",
    "MessagingMetrics",
    "MessagingSerializationError",
    "PublishResult",
    "RedisIdempotencyStore",
    "SqsClientInterface",
    "SqsEventConsumer",
    "SqsEventPublisher",
    "TransportEnvelope",
    "UnsupportedVersionError",
    "create_risk_edges_changed_event",
    "create_sensor_water_depth_event",
    "create_simulation_emitted_event",
    "create_weather_observed_event",
]
