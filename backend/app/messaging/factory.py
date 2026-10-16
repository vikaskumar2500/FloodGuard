"""Composition boundary: domain producers only depend on EventPublisher."""

from app.core.config import Settings
from app.messaging.eventbridge.client import Boto3EventBridgeClient
from app.messaging.eventbridge.publisher import EventBridgeEventPublisher
from app.messaging.metrics import MessagingMetrics
from app.messaging.publisher import EventPublisher, InMemoryEventPublisher
from app.messaging.sqs.client import Boto3SqsClient
from app.messaging.sqs.publisher import SqsEventPublisher


def create_event_publisher(
    settings: Settings,
    metrics: MessagingMetrics | None = None,
) -> EventPublisher:
    if settings.event_transport == "EVENTBRIDGE":
        return EventBridgeEventPublisher(
            Boto3EventBridgeClient(settings.aws_region, settings.eventbridge_endpoint_url),
            settings.eventbridge_bus_name,
            settings.eventbridge_source,
            metrics,
        )
    if settings.event_transport == "SQS" and settings.sqs_enabled:
        return SqsEventPublisher(
            Boto3SqsClient(region_name=settings.aws_region, endpoint_url=settings.sqs_endpoint_url),
            settings.sqs_environment_queue_url,
            metrics=metrics,
        )
    return InMemoryEventPublisher()
