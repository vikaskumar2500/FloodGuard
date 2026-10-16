import enum


class FailureCategory(enum.StrEnum):
    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"


class EventProcessingError(Exception):
    """Base class for all event processing errors."""

    def __init__(self, message: str, category: FailureCategory = FailureCategory.RETRYABLE):
        super().__init__(message)
        self.category = category


class RetryableEventError(EventProcessingError):
    """Transient failures that should be retried."""

    def __init__(self, message: str):
        super().__init__(message, FailureCategory.RETRYABLE)


class NonRetryableEventError(EventProcessingError):
    """Permanent failures that should be dead-lettered immediately."""

    def __init__(self, message: str):
        super().__init__(message, FailureCategory.NON_RETRYABLE)


class DependencyUnavailableError(RetryableEventError):
    """External dependency (DB, Cache) is unavailable."""

    pass


class EventValidationError(NonRetryableEventError):
    """Event payload is invalid."""

    pass


class UnsupportedEventVersionError(NonRetryableEventError):
    """Event version is unsupported."""

    pass


class DeadLetterEnvelope:
    """Envelope for wrapping failures going to DLQ."""

    @staticmethod
    def create(
        original_message: str | dict,
        reason: str,
        category: FailureCategory,
        receive_count: int,
        consumer: str = "floodguard",
        exception_type: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
    ) -> dict:
        import datetime

        return {
            "originalMessage": original_message,
            "failure": {
                "category": category.value,
                "reason": reason,
                "failedAt": datetime.datetime.now(datetime.UTC).isoformat(),
                "receiveCount": receive_count,
                "consumer": consumer,
                "exceptionType": exception_type,
                "correlationId": correlation_id,
                "eventId": event_id,
            },
        }
