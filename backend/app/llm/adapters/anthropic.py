"""Anthropic (Claude) -- the original provider of the app, now one adapter among others."""
from langchain_anthropic import ChatAnthropic

from app.llm.adapters.base import ProviderAdapter
from app.llm.types import LLMParams, ModelInfo, ProviderSettings


class AnthropicAdapter(ProviderAdapter):
    vendor = "anthropic"
    label = "Anthropic (Claude)"
    default_base_url = "https://api.anthropic.com"
    requires_api_key = True

    def _headers(self, settings: ProviderSettings) -> dict:
        return {"x-api-key": settings.api_key, "anthropic-version": "2023-06-01"}

    async def list_models(self, settings: ProviderSettings) -> list[ModelInfo]:
        body = await self._get_json(f"{self.base_url(settings)}/v1/models?limit=100", self._headers(settings))
        return [ModelInfo(id=m["id"], owned_by="anthropic") for m in body.get("data", []) if m.get("id")]

    def supported(self, params: LLMParams) -> dict:
        values = super().supported(params)
        # Recent Claude models reject temperature and top_p together: keep temperature.
        if "temperature" in values:
            values.pop("top_p", None)
        return values

    def create_chat_model(self, settings: ProviderSettings, model: str, params: LLMParams) -> ChatAnthropic:
        return ChatAnthropic(
            model=model,
            api_key=settings.api_key,
            base_url=self.base_url(settings),
            timeout=params.timeout_seconds,
            max_retries=1,
            **self.supported(params),
        )
