"""LLM Provider Layer: resolveProvider -> resolveModel -> createLLM.

    layer = LLMProviderLayer(providers, routing)
    resolution = await layer.resolve(LLMSelection("auto"))   # or "cloud", "vllm", "local"
    llm = layer.chat_model(resolution, observer)              # what LangGraph receives

All provider decisions are made here, from configuration -- no provider
if/else anywhere else in the app.
"""
import time
from dataclasses import dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel

from app.llm.adapters.base import ProviderAdapter
from app.llm.errors import LLMProviderError, NoProviderAvailableError
from app.llm.registry import get_adapter
from app.llm.types import (
    AUTO,
    HEALTH_LABELS,
    PROVIDER_LABELS,
    Attempt,
    HealthResult,
    HealthStatus,
    LLMSelection,
    ProviderKind,
    ProviderSettings,
    RoutingSettings,
)


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    settings: ProviderSettings

    @property
    def label(self) -> str:
        return f"{PROVIDER_LABELS.get(self.provider, self.provider)} · {self.model}"


@dataclass
class Resolution:
    requested: str  # auto | cloud | local | vllm
    targets: list[Target]  # active first; in AUTO, the remaining fallbacks in order
    attempts: list[Attempt] = field(default_factory=list)  # candidates skipped during resolution

    @property
    def active(self) -> Target:
        return self.targets[0]

    @property
    def is_auto(self) -> bool:
        return self.requested == AUTO

    @property
    def fallbacks(self) -> list[Target]:
        return self.targets[1:]


class HealthCache:
    def __init__(self):
        self._entries: dict[tuple, tuple[float, HealthResult]] = {}

    def get(self, key: tuple, ttl: int) -> HealthResult | None:
        entry = self._entries.get(key)
        if entry and entry[0] > time.monotonic() and ttl > 0:
            return entry[1]
        return None

    def put(self, key: tuple, result: HealthResult, ttl: int) -> None:
        self._entries[key] = (time.monotonic() + max(ttl, 0), result)

    def clear(self) -> None:
        self._entries.clear()


class LLMProviderLayer:
    def __init__(
        self,
        providers: dict[ProviderKind, ProviderSettings],
        routing: RoutingSettings,
        health_cache: HealthCache | None = None,
    ):
        self.providers = providers
        self.routing = routing
        self._health_cache = health_cache or HealthCache()

    # ---- adapters / health ------------------------------------------------------------

    def settings_for(self, provider: str) -> ProviderSettings:
        try:
            return self.providers[ProviderKind(provider)]
        except (ValueError, KeyError):
            raise LLMProviderError(provider, HealthStatus.NOT_CONFIGURED, f"Proveedor de IA desconocido: {provider!r}.") from None

    def adapter_for(self, settings: ProviderSettings) -> ProviderAdapter:
        return get_adapter(settings.vendor)

    async def health(self, provider: str, model: str | None = None, *, use_cache: bool = True) -> HealthResult:
        settings = self.settings_for(provider)
        model = model or settings.default_model
        key = (provider, model, settings.vendor, settings.base_url, settings.revision)
        ttl = self.routing.health_ttl_seconds
        if use_cache and (cached := self._health_cache.get(key, ttl)):
            return cached
        result = await self.adapter_for(settings).health(settings, model)
        self._health_cache.put(key, result, ttl)
        return result

    async def list_models(self, provider: str) -> list[str]:
        settings = self.settings_for(provider)
        return [m.id for m in await self.adapter_for(settings).list_models(settings)]

    # ---- resolveProvider / resolveModel ---------------------------------------------------

    def _target(self, provider: str, model: str | None) -> Target:
        settings = self.settings_for(provider)
        return Target(provider, model or settings.default_model, settings)

    def auto_candidates(self) -> list[str]:
        order = [p for p in self.routing.auto_order if p in {k.value for k in self.providers}]
        return [p for p in order if self.providers[ProviderKind(p)].enabled]

    async def resolve(self, selection: LLMSelection) -> Resolution:
        if selection.provider == AUTO:
            return await self._resolve_auto()
        target = self._target(selection.provider, selection.model)
        if not target.settings.enabled:
            raise LLMProviderError(target.provider, HealthStatus.DISABLED,
                                   f"El proveedor {PROVIDER_LABELS[target.provider]} está deshabilitado.", target.model)
        if self.routing.preflight_check:
            health = await self.health(target.provider, target.model)
            if not health.ok:
                # An explicit choice is respected: no silent switch to another provider.
                raise LLMProviderError(
                    target.provider,
                    health.status,
                    f"{target.label}: {HEALTH_LABELS[health.status]}. {health.detail}".strip(),
                    target.model,
                )
        return Resolution(selection.provider, [target])

    async def _resolve_auto(self) -> Resolution:
        candidates = [self._target(p, None) for p in self.auto_candidates()]
        if not candidates:
            raise NoProviderAvailableError([], "AUTO no tiene proveedores habilitados en su orden de prioridad.")
        if not self.routing.preflight_check:
            return Resolution(AUTO, candidates)
        attempts: list[Attempt] = []
        for index, target in enumerate(candidates):
            health = await self.health(target.provider, target.model)
            if health.ok:
                return Resolution(AUTO, candidates[index:], attempts)
            attempts.append(Attempt(target.provider, target.model, health.status.value, health.detail, health.latency_ms))
        summary = "; ".join(f"{PROVIDER_LABELS[a.provider]}: {HEALTH_LABELS[HealthStatus(a.status)]}" for a in attempts)
        raise NoProviderAvailableError(attempts, f"Ningún proveedor de IA está disponible ({summary}).")

    # ---- createLLM ---------------------------------------------------------------------

    def create_llm(self, target: Target) -> BaseChatModel:
        return self.adapter_for(target.settings).create_chat_model(target.settings, target.model, target.settings.params)

    def chat_model(self, resolution: Resolution, observer=None):
        from app.llm.fallback import ProviderChatModel

        failover = resolution.is_auto and self.routing.runtime_fallback
        return ProviderChatModel(self, resolution, failover=failover, observer=observer)
