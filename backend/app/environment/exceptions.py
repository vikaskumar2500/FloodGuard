"""Typed exceptions for the environmental provider layer."""

from __future__ import annotations


class ProviderUnavailable(Exception):
    """Provider could not be reached (network error, DNS failure, etc.)."""


class ProviderTimeout(Exception):
    """Provider did not respond within the configured timeout."""


class ProviderRateLimited(Exception):
    """Provider returned HTTP 429 Too Many Requests.

    Attributes:
        retry_after_seconds: Hint from Retry-After header, or None if absent.
    """

    def __init__(
        self, message: str = "rate limited", retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderAuthenticationError(Exception):
    """Provider rejected the request due to missing or invalid credentials."""


class ProviderInvalidResponse(Exception):
    """Provider returned a response that could not be parsed or is semantically invalid."""
