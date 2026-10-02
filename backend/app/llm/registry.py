"""Which adapters exist and which provider slot may use which vendor.

To add a provider: implement ProviderAdapter, add it to ADAPTERS and to the
slot(s) in VENDORS_BY_PROVIDER. Nothing else in the app changes.
"""
import httpx

from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.base import ProviderAdapter
from app.llm.adapters.openai_compatible import (
    GeminiAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
    VLLMAdapter,
)
from app.llm.types import ProviderKind

ADAPTER_CLASSES: dict[str, type[ProviderAdapter]] = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
    "gemini": GeminiAdapter,
    "vllm": VLLMAdapter,
    "ollama": OllamaAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
}

VENDORS_BY_PROVIDER: dict[ProviderKind, tuple[str, ...]] = {
    ProviderKind.CLOUD: ("anthropic", "openai", "gemini"),
    ProviderKind.VLLM: ("vllm",),
    ProviderKind.LOCAL: ("ollama", "openai_compatible"),
}

_transport: httpx.AsyncBaseTransport | None = None


def set_probe_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Test seam: route health checks / model discovery through an in-memory transport."""
    global _transport
    _transport = transport


def get_adapter(vendor: str) -> ProviderAdapter:
    try:
        return ADAPTER_CLASSES[vendor](transport=_transport)
    except KeyError:
        raise ValueError(f"Proveedor de IA desconocido: {vendor!r}") from None


def vendors_for(kind: ProviderKind) -> tuple[str, ...]:
    return VENDORS_BY_PROVIDER[kind]


def vendor_catalog() -> dict[str, list[dict]]:
    return {
        kind.value: [
            {"vendor": v, "label": ADAPTER_CLASSES[v].label, "default_base_url": ADAPTER_CLASSES[v].default_base_url,
             "requires_api_key": ADAPTER_CLASSES[v].requires_api_key}
            for v in vendors
        ]
        for kind, vendors in VENDORS_BY_PROVIDER.items()
    }
