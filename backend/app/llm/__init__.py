"""LLM Provider Layer.

Everything that knows how to talk to a concrete LLM lives here: provider
settings types, one adapter per vendor (Anthropic, OpenAI, Gemini, vLLM, local
runtimes), health checks, model discovery, provider resolution (including
AUTO with ordered fallbacks) and a chat-model wrapper that fails over at call
time. LangGraph nodes never import from here directly: they call
app.agents.llm.get_chat_model(), which returns whatever this layer resolved
for the current request.

Adding a provider = implementing ProviderAdapter and registering it in
registry.py. Nothing in app/agents or app/services/report changes.
"""
