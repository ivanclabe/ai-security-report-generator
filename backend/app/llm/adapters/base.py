"""Contract every provider adapter implements.

An adapter knows three things about one vendor/runtime: how to list its models,
how to tell whether it can serve right now (health), and how to build a
LangChain chat model with normalized parameters. It never stores settings and
never logs secrets.
"""
import time
from abc import ABC, abstractmethod

import httpx
from langchain_core.language_models.chat_models import BaseChatModel

from app.llm.errors import classify_error, safe_error_message
from app.llm.types import (
    HealthResult,
    HealthStatus,
    LLMParams,
    ModelInfo,
    ProviderSettings,
)

SUPPORTED_PARAMS_ALL = frozenset({"temperature", "max_tokens", "top_p", "timeout_seconds", "context_window"})


class ProviderAdapter(ABC):
    vendor: str = ""
    label: str = ""
    default_base_url: str = ""
    requires_api_key: bool = False
    supports_discovery: bool = True
    supported_params: frozenset[str] = SUPPORTED_PARAMS_ALL
    # Seconds allowed for health checks and model discovery (short: they gate a request).
    probe_timeout_seconds: float = 8.0

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport  # tests inject an in-memory transport

    # ---- to implement ---------------------------------------------------------------

    @abstractmethod
    async def list_models(self, settings: ProviderSettings) -> list[ModelInfo]: ...

    @abstractmethod
    def create_chat_model(self, settings: ProviderSettings, model: str, params: LLMParams) -> BaseChatModel: ...

    # ---- shared behaviour -----------------------------------------------------------

    def base_url(self, settings: ProviderSettings) -> str:
        return (settings.base_url or self.default_base_url).rstrip("/")

    def supported(self, params: LLMParams) -> dict:
        """Only the parameters this provider understands (unsupported ones are dropped)."""
        values = {
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "top_p": params.top_p,
        }
        return {k: v for k, v in values.items() if v is not None and k in self.supported_params}

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout or self.probe_timeout_seconds, transport=self._transport)

    def configuration_problem(self, settings: ProviderSettings, model: str | None) -> str | None:
        if not self.base_url(settings):
            return "Falta la URL del proveedor."
        if self.requires_api_key and not settings.api_key:
            return "Falta la API key."
        if not (model or settings.default_model):
            return "No hay un modelo seleccionado."
        return None

    async def health(self, settings: ProviderSettings, model: str | None = None) -> HealthResult:
        """Available / not, why, and the approximate latency of a lightweight probe
        (model listing). If discovery works and the model is not listed: MODEL_UNAVAILABLE."""
        kind = settings.kind.value
        model = model or settings.default_model
        if not settings.enabled:
            return HealthResult(kind, HealthStatus.DISABLED, detail="El proveedor está deshabilitado.", model=model)
        problem = self.configuration_problem(settings, model)
        if problem:
            return HealthResult(kind, HealthStatus.NOT_CONFIGURED, detail=problem, model=model)
        started = time.monotonic()
        try:
            models = [m.id for m in await self.list_models(settings)]
        except NotImplementedError:
            models = []
        except Exception as exc:  # noqa: BLE001 - classified below, never raised to the caller
            status = classify_error(exc) or HealthStatus.UNAVAILABLE
            return HealthResult(
                kind, status, latency_ms=int((time.monotonic() - started) * 1000),
                detail=safe_error_message(exc), model=model,
            )
        latency = int((time.monotonic() - started) * 1000)
        if models and model not in models:
            return HealthResult(
                kind, HealthStatus.MODEL_UNAVAILABLE, latency_ms=latency,
                detail=f"El modelo «{model}» no está disponible en el proveedor.", model=model, models=tuple(models),
            )
        return HealthResult(kind, HealthStatus.AVAILABLE, latency_ms=latency, model=model, models=tuple(models))

    async def _get_json(self, url: str, headers: dict | None = None) -> dict:
        async with self._client() as client:
            response = await client.get(url, headers=headers or {})
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code} en {httpx.URL(url).path}", request=response.request, response=response
            )
        return response.json()
