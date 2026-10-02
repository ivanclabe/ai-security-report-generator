"""Failures of the LLM Provider Layer and their classification.

classify_error() turns any SDK/HTTP exception (Anthropic, OpenAI, httpx,
asyncio) into a HealthStatus without importing those SDKs' exception classes,
so adding a vendor does not mean touching this module.
"""
import asyncio

from app.llm.types import HealthStatus


class LLMProviderError(RuntimeError):
    """A provider could not serve the request. `message` is safe to show (no secrets)."""

    def __init__(self, provider: str, status: HealthStatus, message: str, model: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.model = model


class NoProviderAvailableError(LLMProviderError):
    def __init__(self, attempts: list, message: str):
        super().__init__("auto", HealthStatus.UNAVAILABLE, message)
        self.attempts = attempts


# Failures that mean "this provider cannot serve now" -> eligible for fallback in AUTO.
FAILOVER_STATUSES = {
    HealthStatus.UNAVAILABLE,
    HealthStatus.AUTH_ERROR,
    HealthStatus.TIMEOUT,
    HealthStatus.MODEL_UNAVAILABLE,
    HealthStatus.CONNECTION_ERROR,
    HealthStatus.SERVER_ERROR,
    HealthStatus.RATE_LIMITED,
    HealthStatus.NOT_CONFIGURED,
    HealthStatus.DISABLED,
}


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def classify_error(exc: BaseException) -> HealthStatus | None:
    """HealthStatus for provider-level failures; None for anything else (e.g. the model
    answered but its output did not match the schema -- not a reason to switch provider)."""
    if isinstance(exc, LLMProviderError):
        return exc.status
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return HealthStatus.TIMEOUT
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return HealthStatus.TIMEOUT
    if "connect" in name or isinstance(exc, ConnectionError):
        return HealthStatus.CONNECTION_ERROR
    if "authentication" in name or "permissiondenied" in name:
        return HealthStatus.AUTH_ERROR
    if "ratelimit" in name:
        return HealthStatus.RATE_LIMITED
    if "notfound" in name:
        return HealthStatus.MODEL_UNAVAILABLE
    code = _status_code(exc)
    if code in (401, 403):
        return HealthStatus.AUTH_ERROR
    if code == 404:
        return HealthStatus.MODEL_UNAVAILABLE
    if code == 429:
        return HealthStatus.RATE_LIMITED
    if code is not None and code >= 500:
        return HealthStatus.SERVER_ERROR
    if "internalserver" in name or "serviceunavailable" in name or "overloaded" in name:
        return HealthStatus.SERVER_ERROR
    return None


def safe_error_message(exc: BaseException, limit: int = 300) -> str:
    """Short description without secrets (SDK messages can echo request headers/URLs)."""
    from app.security.redaction import redact_text

    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return redact_text(text, limit)
