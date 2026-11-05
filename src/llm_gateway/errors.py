from __future__ import annotations


class GatewayError(Exception):
    """An error with a stable HTTP status and machine-readable code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ProviderError(Exception):
    """Base class for provider failures. Messages never contain prompt or response text."""

    retryable = True


class ProviderTimeout(ProviderError):
    """The provider did not answer within the allowed time."""


class ProviderUnavailable(ProviderError):
    """Transport failure, 5xx, 429 or an unusable response."""


class ProviderRejected(ProviderError):
    """The provider refused the request itself (4xx). Falling back would not help."""

    retryable = False
