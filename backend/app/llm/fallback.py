"""The chat model LangGraph receives: one object, whatever the provider.

It exposes the part of the LangChain chat-model API the nodes use --
with_structured_output(), bind_tools(), ainvoke() -- builds the real client of
the active provider lazily, measures every call, and in AUTO fails over to the
next provider when a call fails for a provider-level reason (timeout,
connection, 5xx, auth, model missing, rate limit). Each switch is reported to
the observer: it never happens silently. Explicit selections never fail over.
"""
import time
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler

from app.llm.errors import (
    FAILOVER_STATUSES,
    LLMProviderError,
    classify_error,
    safe_error_message,
)
from app.llm.types import HEALTH_LABELS, HealthStatus


class LLMObserver(Protocol):
    async def on_call(self, target, *, ok: bool, latency_ms: int, usage: dict, status: str | None,
                      error: str | None) -> None: ...

    async def on_switch(self, from_target, to_target, *, status: HealthStatus, detail: str) -> None: ...


class _UsageCapture(BaseCallbackHandler):
    """Token usage of one call, from whatever the provider reports (none is fine)."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        for generations in getattr(response, "generations", []) or []:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                self.input_tokens += int(usage.get("input_tokens") or 0)
                self.output_tokens += int(usage.get("output_tokens") or 0)

    @property
    def usage(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def _with_callback(config: dict | None, handler: BaseCallbackHandler) -> dict:
    config = dict(config or {})
    callbacks = config.get("callbacks")
    if callbacks is None:
        config["callbacks"] = [handler]
    elif isinstance(callbacks, list):
        config["callbacks"] = [*callbacks, handler]
    else:  # a CallbackManager
        callbacks = callbacks.copy()
        callbacks.add_handler(handler, inherit=False)
        config["callbacks"] = callbacks
    return config


class ProviderChatModel:
    def __init__(self, layer, resolution, *, failover: bool, observer: LLMObserver | None = None):
        self._layer = layer
        self._resolution = resolution
        self._failover = failover
        self._observer = observer
        self._index = 0
        self._clients: dict[int, Any] = {}

    @property
    def resolution(self):
        return self._resolution

    @property
    def active(self):
        return self._resolution.targets[self._index]

    def _client(self):
        if self._index not in self._clients:
            self._clients[self._index] = self._layer.create_llm(self.active)
        return self._clients[self._index]

    def _runnable(self, op: str | None, arg: Any, kwargs: dict):
        client = self._client()
        if op == "structured":
            adapter = self._layer.adapter_for(self.active.settings)
            method = getattr(adapter, "structured_output_method", None)
            if method is not None and "method" not in kwargs:
                kwargs = {**kwargs, "method": method(self.active.settings.params)}
            return client.with_structured_output(arg, **kwargs)
        if op == "tools":
            return client.bind_tools(arg, **kwargs)
        return client

    # ---- the LangChain surface the nodes use -------------------------------------------

    def with_structured_output(self, schema, **kwargs) -> "_BoundCall":
        return _BoundCall(self, "structured", schema, kwargs)

    def bind_tools(self, tools, **kwargs) -> "_BoundCall":
        return _BoundCall(self, "tools", tools, kwargs)

    async def ainvoke(self, input, config=None, **kwargs):  # noqa: A002 - LangChain's signature
        return await _BoundCall(self, None, None, {}).ainvoke(input, config, **kwargs)

    # ---- failover ---------------------------------------------------------------------

    async def _call(self, op: str | None, arg: Any, kwargs: dict, input, config, call_kwargs):  # noqa: A002
        while True:
            target = self.active
            capture = _UsageCapture()
            started = time.monotonic()
            try:
                result = await self._runnable(op, arg, kwargs).ainvoke(input, _with_callback(config, capture), **call_kwargs)
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                status = classify_error(exc)
                detail = safe_error_message(exc)
                if self._observer:
                    await self._observer.on_call(target, ok=False, latency_ms=latency, usage=capture.usage,
                                                 status=status.value if status else "error", error=detail)
                can_switch = self._failover and status in FAILOVER_STATUSES and self._index + 1 < len(self._resolution.targets)
                if not can_switch:
                    if status is None:
                        raise
                    raise LLMProviderError(
                        target.provider, status, f"{target.label}: {HEALTH_LABELS[status]}. {detail}", target.model
                    ) from exc
                self._index += 1
                if self._observer:
                    await self._observer.on_switch(target, self.active, status=status, detail=detail)
                continue
            if self._observer:
                await self._observer.on_call(target, ok=True, latency_ms=int((time.monotonic() - started) * 1000),
                                             usage=capture.usage, status="ok", error=None)
            return result


class _BoundCall:
    def __init__(self, owner: ProviderChatModel, op: str | None, arg: Any, kwargs: dict):
        self._owner, self._op, self._arg, self._kwargs = owner, op, arg, kwargs

    async def ainvoke(self, input, config=None, **kwargs):  # noqa: A002
        return await self._owner._call(self._op, self._arg, self._kwargs, input, config, kwargs)
