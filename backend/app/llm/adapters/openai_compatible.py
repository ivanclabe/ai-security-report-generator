"""OpenAI-compatible chat completions: OpenAI itself, Gemini (its OpenAI-compatible
endpoint), vLLM and local runtimes (Ollama, LM Studio, llama.cpp server...).

One LangChain client (ChatOpenAI) covers all of them; each subclass only states
its defaults, how it lists models and how it checks health.
"""
from langchain_openai import ChatOpenAI

from app.llm.adapters.base import ProviderAdapter
from app.llm.types import (
    HealthResult,
    HealthStatus,
    LLMParams,
    ModelInfo,
    ProviderSettings,
)


class OpenAICompatibleAdapter(ProviderAdapter):
    vendor = "openai_compatible"
    label = "Servidor compatible con OpenAI"
    default_base_url = ""
    requires_api_key = False
    api_path = "/v1"  # appended to the base URL when it does not already end with it
    default_structured_output = "json_schema"

    def api_base(self, settings: ProviderSettings) -> str:
        base = self.base_url(settings)
        return base if not self.api_path or base.endswith(self.api_path) else f"{base}{self.api_path}"

    def _headers(self, settings: ProviderSettings) -> dict:
        return {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}

    async def list_models(self, settings: ProviderSettings) -> list[ModelInfo]:
        body = await self._get_json(f"{self.api_base(settings)}/models", self._headers(settings))
        return [
            ModelInfo(id=m["id"], owned_by=m.get("owned_by"), context_window=m.get("max_model_len"))
            for m in body.get("data", [])
            if m.get("id")
        ]

    def structured_output_method(self, params: LLMParams) -> str:
        return self.default_structured_output if params.structured_output in ("", "auto") else params.structured_output

    def create_chat_model(self, settings: ProviderSettings, model: str, params: LLMParams) -> ChatOpenAI:
        return ChatOpenAI(
            model=model,
            api_key=settings.api_key or "not-needed",  # local servers usually ignore it
            base_url=self.api_base(settings),
            timeout=params.timeout_seconds,
            max_retries=1,
            **self.supported(params),
        )


class OpenAIAdapter(OpenAICompatibleAdapter):
    vendor = "openai"
    label = "OpenAI (GPT)"
    default_base_url = "https://api.openai.com/v1"
    requires_api_key = True


class GeminiAdapter(OpenAICompatibleAdapter):
    vendor = "gemini"
    label = "Google (Gemini)"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    requires_api_key = True
    api_path = ""
    default_structured_output = "function_calling"

    async def list_models(self, settings: ProviderSettings) -> list[ModelInfo]:
        models = await super().list_models(settings)
        # Gemini's compatible endpoint lists "models/gemini-..." -- the chat API wants the bare id.
        return [ModelInfo(id=m.id.removeprefix("models/"), owned_by="google") for m in models]


class VLLMAdapter(OpenAICompatibleAdapter):
    """vLLM's OpenAI-compatible server: GET /health for liveness, GET /v1/models for the served model(s)."""

    vendor = "vllm"
    label = "vLLM"
    default_base_url = ""

    def root(self, settings: ProviderSettings) -> str:
        base = self.base_url(settings)
        return base[: -len(self.api_path)] if base.endswith(self.api_path) else base

    async def health(self, settings: ProviderSettings, model: str | None = None) -> HealthResult:
        result = await super().health(settings, model)
        if result.status != HealthStatus.AVAILABLE:
            return result
        try:
            async with self._client() as client:
                response = await client.get(f"{self.root(settings)}/health")
            if response.status_code >= 500:
                return HealthResult(result.provider, HealthStatus.SERVER_ERROR, result.latency_ms,
                                    f"/health respondió {response.status_code}", result.model, result.models)
        except Exception:  # noqa: BLE001 - /health is optional in some deployments; /v1/models already answered
            pass
        return result


class OllamaAdapter(OpenAICompatibleAdapter):
    """Ollama: chat through its OpenAI-compatible /v1, models through /api/tags."""

    vendor = "ollama"
    label = "Ollama"
    default_base_url = "http://localhost:11434"

    async def list_models(self, settings: ProviderSettings) -> list[ModelInfo]:
        root = self.base_url(settings).removesuffix("/v1")
        try:
            body = await self._get_json(f"{root}/api/tags")
            return [ModelInfo(id=m["name"], owned_by="ollama") for m in body.get("models", []) if m.get("name")]
        except Exception:  # noqa: BLE001 - older/other runtimes: fall back to the OpenAI-style listing
            return await super().list_models(settings)

    def structured_output_method(self, params: LLMParams) -> str:
        return "function_calling" if params.structured_output in ("", "auto") else params.structured_output
