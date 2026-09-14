from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from app.config.settings import get_settings


@lru_cache
def get_chat_model() -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
    )
