"""The agent's only door to an LLM.

LangGraph nodes and the report narrative call get_chat_model() and use the
standard LangChain surface (with_structured_output / bind_tools / ainvoke).
Which provider and model answers -- Cloud, vLLM, Local, or AUTO with
fallback -- is decided per request by the LLM Provider Layer (app/llm,
app/services/llm_runtime.py); nothing here or in the nodes knows about it.
"""
from app.services.llm_runtime import current_chat_model


def get_chat_model():
    return current_chat_model()
