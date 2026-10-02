"""In-memory stand-ins for LLM providers' HTTP endpoints (model listing, /health) and for
chat models, so the LLM Provider Layer is tested without any network or real model."""
import httpx


class FakeLLMServers:
    """Answers GET /v1/models (Anthropic and OpenAI-compatible), /api/tags (Ollama) and
    /health (vLLM) per host. Switches simulate each failure mode a health check reports."""

    def __init__(self):
        self.models = {
            "api.anthropic.com": ["claude-sonnet-5", "claude-haiku-4-5"],
            "llm-server": ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"],
            "localhost": ["llama3.1:8b", "mistral:7b"],
            "api.openai.com": ["gpt-5", "gpt-5-mini"],
        }
        self.failures: dict[str, str] = {}  # host -> "timeout" | "connect" | "401" | "500"
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def fail(self, host: str, mode: str) -> None:
        self.failures[host] = mode

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        mode = self.failures.get(host)
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if mode == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if mode and mode.isdigit():
            return httpx.Response(int(mode), json={"error": "fake"})
        models = self.models.get(host)
        if models is None:
            raise httpx.ConnectError("unknown host", request=request)
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200)
        if path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m, "owned_by": "fake"} for m in models]})
        return httpx.Response(404)


class _FakeGeneration:
    def __init__(self, usage):
        self.message = type("M", (), {"usage_metadata": usage})()


class _FakeLLMResult:
    def __init__(self, usage):
        self.generations = [[_FakeGeneration(usage)]]


class ScriptedChatModel:
    """Stands in for the LangChain client of ONE provider (what an adapter's create_chat_model
    returns). Answers structured-output calls by schema, records every call, can fail on demand,
    and reports token usage through the callbacks it receives -- like a real client."""

    def __init__(self, name: str, responses: dict | None = None, fail: Exception | None = None,
                 usage: dict | None = None, log: list | None = None):
        self.name = name
        self.responses = responses or {}
        self.fail = fail
        self.usage = usage or {"input_tokens": 100, "output_tokens": 20}
        self.log = log if log is not None else []

    def with_structured_output(self, schema, **kwargs):
        return _ScriptedRunnable(self, schema, kwargs)

    def bind_tools(self, tools, **kwargs):
        return _ScriptedRunnable(self, "tools", kwargs)


class _ScriptedRunnable:
    def __init__(self, model: ScriptedChatModel, key, kwargs):
        self.model, self.key, self.kwargs = model, key, kwargs

    async def ainvoke(self, input, config=None, **kwargs):  # noqa: A002
        self.model.log.append((self.model.name, getattr(self.key, "__name__", self.key), self.kwargs))
        if self.model.fail is not None:
            raise self.model.fail
        for callback in (config or {}).get("callbacks") or []:
            if hasattr(callback, "on_llm_end"):
                callback.on_llm_end(_FakeLLMResult(self.model.usage))
        response = self.model.responses.get(self.key)
        return response() if callable(response) else response
