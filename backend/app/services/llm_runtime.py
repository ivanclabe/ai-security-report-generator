"""Per-request LLM execution: which provider/model THIS report or chat turn uses.

    run = await start_run(selection, purpose="report")   # resolve + pre-flight health check
    ...LangGraph nodes call get_chat_model() -> run.model  (contextvar, no extra plumbing)
    run.drain_events()  # "llm" SSE events for the UI: selected provider, fallbacks
    run.summary()       # stored with the execution (provider, model, fallback, tokens, latency)

The run is kept in a contextvar: each HTTP request has its own context, and
the tasks LangGraph spawns inherit it, so the selection made by the user
reaches the node that performs inference without touching the graph.

Every LLM call becomes an observability event (provider, model, request id,
latency, status, tokens, fallback) and every provider switch an observability
WARNING plus an audit record -- never silent. Prompts and responses are never
recorded.
"""
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.llm.errors import LLMProviderError, NoProviderAvailableError
from app.llm.layer import LLMProviderLayer, Resolution, Target
from app.llm.types import (
    AUTO,
    HEALTH_LABELS,
    PROVIDER_LABELS,
    SELECTABLE_PROVIDERS,
    HealthStatus,
    LLMSelection,
)
from app.security.context import CurrentUser, get_request_meta
from app.services import audit
from app.services import llm_settings_service as llm_settings
from app.services import supabase_rest as db
from app.services.observability import get_observability

logger = logging.getLogger(__name__)

LLM_UNAVAILABLE = "llm_unavailable"


@dataclass
class LLMRun:
    selection: LLMSelection
    resolution: Resolution
    layer: LLMProviderLayer
    purpose: str
    calls: int = 0
    failed_calls: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fallbacks: list[dict] = field(default_factory=list)
    _pending: list[dict] = field(default_factory=list)
    _model: object | None = None

    @property
    def model(self):
        if self._model is None:
            self._model = self.layer.chat_model(self.resolution, observer=_RunObserver(self))
        return self._model

    @property
    def active(self) -> Target:
        model = self._model
        return model.active if model is not None else self.resolution.active

    def info(self) -> dict:
        active = self.active
        targets = self.resolution.targets
        remaining = targets[targets.index(active) + 1 :] if active in targets else []
        return {
            "requested": self.selection.provider,
            "requested_label": PROVIDER_LABELS.get(self.selection.provider, self.selection.provider),
            "provider": active.provider,
            "provider_label": PROVIDER_LABELS.get(active.provider, active.provider),
            "vendor": active.settings.vendor,
            "model": active.model,
            "fallbacks": [{"provider": t.provider, "model": t.model, "label": t.label} for t in remaining]
            if self.resolution.is_auto
            else [],
            "switched": bool(self.fallbacks),
            "last_fallback": self.fallbacks[-1] if self.fallbacks else None,
        }

    def _push(self, phase: str) -> None:
        self._pending.append({"event": "llm", "phase": phase, **self.info()})

    def drain_events(self) -> list[dict]:
        events, self._pending = self._pending, []
        return events

    def summary(self) -> dict:
        info = self.info()
        return {
            "requested_provider": self.selection.provider,
            "provider": info["provider"],
            "model": info["model"],
            "vendor": info["vendor"],
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "fallback_used": bool(self.fallbacks),
            "fallbacks": self.fallbacks,
        }


_current_run: ContextVar[LLMRun | None] = ContextVar("llm_run", default=None)


def current_run() -> LLMRun | None:
    return _current_run.get()


async def _record_switch(run: LLMRun, from_provider: str, from_model: str, to: Target, status: HealthStatus,
                         detail: str, stage: str) -> None:
    reason = HEALTH_LABELS.get(status, str(status))
    switch = {
        "from": from_provider,
        "from_model": from_model,
        "to": to.provider,
        "to_model": to.model,
        "reason": status.value,
        "reason_label": reason,
        "stage": stage,  # "preflight" (health check) | "runtime" (a call failed)
    }
    run.fallbacks.append(switch)
    message = f"Proveedor de IA cambiado: {PROVIDER_LABELS[from_provider]} → {PROVIDER_LABELS[to.provider]}. Motivo: {reason}"
    await get_observability().emit(
        "WARNING", "llm", "llm.provider_fallback", message,
        status=status.value, context={**switch, "detail": detail[:200], "purpose": run.purpose},
    )
    await audit.record(
        "llm.provider_fallback", module="ia", result="failure", resource_type="llm_provider", resource_id=to.provider,
        context={**switch, "purpose": run.purpose},
    )


class _RunObserver:
    def __init__(self, run: LLMRun):
        self._run = run

    async def on_call(self, target, *, ok, latency_ms, usage, status, error):
        run = self._run
        run.calls += 1
        run.latency_ms += latency_ms
        run.input_tokens += usage.get("input_tokens", 0)
        run.output_tokens += usage.get("output_tokens", 0)
        if not ok:
            run.failed_calls += 1
        seconds = f"{latency_ms / 1000:.1f}".replace(".", ",")
        await get_observability().emit(
            "INFO" if ok else "ERROR",
            "llm",
            "llm.call.completed" if ok else "llm.call.failed",
            f"{target.label}: {'ok' if ok else (error or status)} ({seconds} s)",
            status=status,
            duration_ms=latency_ms,
            context={
                "provider": target.provider,
                "vendor": target.settings.vendor,
                "model": target.model,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "fallback": bool(run.fallbacks),
                "purpose": run.purpose,
            },
            persist=True,
        )
        if not ok:
            await audit.record(
                "llm.provider_error", module="ia", result="error", resource_type="llm_provider",
                resource_id=target.provider, context={"model": target.model, "status": status, "error": error},
            )

    async def on_switch(self, from_target, to_target, *, status, detail):
        await _record_switch(self._run, from_target.provider, from_target.model, to_target, status, detail, "runtime")
        self._run._push("fallback")


async def start_run(selection: LLMSelection, *, purpose: str) -> LLMRun:
    """Resolve the provider for one execution and make it the current one.
    Raises LLMProviderError (explicit provider unavailable / AUTO with nothing available)."""
    layer = await llm_settings.get_layer()
    try:
        resolution = await layer.resolve(selection)
    except LLMProviderError as exc:
        attempts = getattr(exc, "attempts", [])
        await get_observability().emit(
            "ERROR", "llm", "llm.provider_unavailable", str(exc), status=exc.status.value,
            context={"requested": selection.provider, "model": selection.model, "purpose": purpose,
                     "attempts": [a.__dict__ for a in attempts]},
        )
        await audit.record(
            "llm.provider_error", module="ia", result="error", resource_type="llm_provider",
            resource_id=selection.provider, context={"requested": selection.provider, "model": selection.model,
                                                     "status": exc.status.value, "message": str(exc)},
        )
        raise
    run = LLMRun(selection, resolution, layer, purpose)
    # AUTO skipped unavailable providers during the pre-flight check: say so.
    previous = None
    for attempt in resolution.attempts:
        nxt = resolution.active
        await _record_switch(run, attempt.provider, attempt.model, nxt, HealthStatus(attempt.status), attempt.detail,
                             "preflight")
        previous = attempt
    _current_run.set(run)
    run._push("selected")
    await get_observability().emit(
        "INFO", "llm", "llm.provider_selected",
        f"{run.active.label} seleccionado ({'AUTO' if selection.provider == AUTO else 'elegido por el usuario'})",
        context={"requested": selection.provider, "provider": run.active.provider, "model": run.active.model,
                 "purpose": purpose, "request_id": get_request_meta().request_id,
                 "skipped": previous.provider if previous else None},
        persist=False,
    )
    return run


def end_run() -> None:
    _current_run.set(None)


def current_chat_model():
    """What get_chat_model() returns: the current request's provider, or -- outside a
    request (CLI tools, offline evals) -- the bootstrap Cloud provider, without checks."""
    run = current_run()
    if run is not None:
        return run.model
    providers = llm_settings.providers_from_env()
    routing = llm_settings.routing_from_env()
    layer = LLMProviderLayer(providers, routing)
    cloud = providers[next(iter(providers))]
    return layer.chat_model(Resolution(cloud.kind.value, [Target(cloud.kind.value, cloud.default_model, cloud)]))


async def default_selection(user: CurrentUser | None) -> LLMSelection:
    """The user's saved choice (Configuración), else the app's default provider."""
    if user is not None:
        try:
            rows = await db.select("in_user_preferences", filters={"auth_user_id": user.auth_id})
            prefs = (rows[0].get("preferences") or {}) if rows else {}
            provider = prefs.get("llm_provider")
            if provider in SELECTABLE_PROVIDERS:
                return LLMSelection(provider, prefs.get("llm_model") or None)
        except Exception:  # noqa: BLE001 - preferences are a convenience
            logger.debug("Sin preferencias de IA para el usuario; se usa el proveedor predeterminado")
    _, routing = await llm_settings.load()
    return LLMSelection(routing.default_provider, None)


async def selection_for(provider: str | None, model: str | None, user: CurrentUser | None) -> LLMSelection:
    if provider in SELECTABLE_PROVIDERS:
        return LLMSelection(provider, (model or None) if provider != AUTO else None)
    return await default_selection(user)


def unavailable_message(exc: LLMProviderError) -> str:
    if isinstance(exc, NoProviderAvailableError):
        return f"No se pudo iniciar: {exc} Revisa Configuración > Proveedores de IA o elige otro proveedor."
    return f"No se pudo iniciar con el proveedor elegido: {exc} Elige otro proveedor o usa Auto."
