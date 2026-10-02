"""Plain data types of the LLM Provider Layer (no I/O)."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum


class ProviderKind(StrEnum):
    """The three provider slots the app exposes. Each slot is independent configuration,
    even when (today) two of them point at the same server."""

    CLOUD = "cloud"
    LOCAL = "local"
    VLLM = "vllm"


AUTO = "auto"
SELECTABLE_PROVIDERS = (AUTO, ProviderKind.CLOUD.value, ProviderKind.LOCAL.value, ProviderKind.VLLM.value)

PROVIDER_LABELS = {
    AUTO: "Auto",
    ProviderKind.CLOUD.value: "Cloud",
    ProviderKind.LOCAL.value: "Local",
    ProviderKind.VLLM.value: "vLLM",
}


class HealthStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    AUTH_ERROR = "auth_error"
    TIMEOUT = "timeout"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONNECTION_ERROR = "connection_error"
    SERVER_ERROR = "server_error"
    RATE_LIMITED = "rate_limited"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"


HEALTH_LABELS = {
    HealthStatus.AVAILABLE: "Disponible",
    HealthStatus.UNAVAILABLE: "No disponible",
    HealthStatus.AUTH_ERROR: "Error de autenticación",
    HealthStatus.TIMEOUT: "Tiempo de espera agotado",
    HealthStatus.MODEL_UNAVAILABLE: "Modelo no disponible",
    HealthStatus.CONNECTION_ERROR: "Error de conexión",
    HealthStatus.SERVER_ERROR: "Error del servidor",
    HealthStatus.RATE_LIMITED: "Límite de uso alcanzado",
    HealthStatus.NOT_CONFIGURED: "Sin configurar",
    HealthStatus.DISABLED: "Deshabilitado",
}


@dataclass(frozen=True)
class LLMParams:
    """Normalized inference parameters. None = let the provider use its default.
    Adapters drop whatever their provider does not support (never an error)."""

    temperature: float | None = None
    max_tokens: int | None = 8192
    top_p: float | None = None
    timeout_seconds: float = 120.0
    context_window: int | None = None
    # How structured output is requested from OpenAI-compatible servers:
    # "json_schema" (vLLM/OpenAI guided decoding), "function_calling" or "json_mode".
    structured_output: str = "auto"

    def merged(self, overrides: dict | None) -> "LLMParams":
        if not overrides:
            return self
        known = {k: v for k, v in overrides.items() if k in self.__dataclass_fields__ and v is not None}
        return replace(self, **known)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    owned_by: str | None = None
    context_window: int | None = None


@dataclass(frozen=True)
class ProviderSettings:
    kind: ProviderKind
    vendor: str  # adapter key: anthropic | openai | gemini | vllm | ollama | openai_compatible
    enabled: bool = True
    base_url: str = ""
    api_key: str = field(default="", repr=False)  # clear text only in memory, never logged
    api_key_hint: str | None = None  # last 4 characters, for the UI
    default_model: str = ""
    manual_models: tuple[str, ...] = ()
    discovered_models: tuple[str, ...] = ()
    discovery_enabled: bool = True
    params: LLMParams = LLMParams()
    revision: int = 0
    updated_at: str | None = None
    updated_by: str | None = None
    origin: str = "env"  # "app" (saved from Configuración) | "env" (bootstrap)

    @property
    def models(self) -> list[str]:
        """Models offered for selection: discovered first, then manual extras, no duplicates."""
        seen: list[str] = []
        for model in (*self.discovered_models, *self.manual_models, self.default_model):
            if model and model not in seen:
                seen.append(model)
        return seen


@dataclass(frozen=True)
class RoutingSettings:
    default_provider: str = ProviderKind.CLOUD.value  # auto | cloud | local | vllm
    auto_order: tuple[str, ...] = (ProviderKind.VLLM.value, ProviderKind.CLOUD.value)
    health_ttl_seconds: int = 30
    preflight_check: bool = True  # check the selected provider before an important operation
    runtime_fallback: bool = True  # in AUTO, also fail over when a call fails mid-run
    revision: int = 0
    updated_at: str | None = None
    updated_by: str | None = None
    origin: str = "env"


@dataclass(frozen=True)
class LLMSelection:
    """What the user (or the request) asked for."""

    provider: str = AUTO  # auto | cloud | local | vllm
    model: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class HealthResult:
    provider: str
    status: HealthStatus
    latency_ms: int | None = None
    detail: str = ""
    model: str | None = None
    models: tuple[str, ...] = ()
    checked_at: str = field(default_factory=_now)

    @property
    def ok(self) -> bool:
        return self.status == HealthStatus.AVAILABLE

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "label": HEALTH_LABELS[self.status],
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "model": self.model,
            "models_count": len(self.models),
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class Attempt:
    """One provider considered while resolving AUTO (or failing over at call time)."""

    provider: str
    model: str
    status: str
    detail: str = ""
    latency_ms: int | None = None
