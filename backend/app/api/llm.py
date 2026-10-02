"""AI providers: selection catalog, health checks, provider settings, routing.

* GET  /api/llm/catalog                      -- members: what can be selected (no secrets)
* POST /api/llm/health                       -- members: is a provider/model available now?
* GET  /api/llm/providers                    -- admins: full settings (API keys only as "set" + hint)
* PUT  /api/llm/providers/{kind}             -- admins: save (key write-only, revision-checked, audited)
* POST /api/llm/providers/{kind}/test        -- admins: health of UNSAVED values
* POST /api/llm/providers/{kind}/models/refresh -- admins: discover models and remember them
* GET/PUT /api/llm/routing                   -- admins: default provider, AUTO order, checks

Every call that needs a provider secret runs here, in the backend.
"""
import dataclasses
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_admin, require_user
from app.llm.registry import get_adapter, vendor_catalog
from app.llm.types import (
    HEALTH_LABELS,
    PROVIDER_LABELS,
    SELECTABLE_PROVIDERS,
    ProviderKind,
    ProviderSettings,
)
from app.security import secret_box
from app.security.context import CurrentUser
from app.services import audit, llm_runtime
from app.services import llm_settings_service as llm_settings
from app.services.observability import get_observability

router = APIRouter(prefix="/api/llm", tags=["llm"])

_WINDOW_SECONDS = 300
_LIMIT = 30
_checks: deque[float] = deque()


def reset_llm_rate_limit() -> None:
    _checks.clear()


def _rate_limit() -> None:
    now = time.monotonic()
    while _checks and now - _checks[0] >= _WINDOW_SECONDS:
        _checks.popleft()
    if len(_checks) >= _LIMIT:
        raise HTTPException(status_code=429, detail="Demasiadas comprobaciones seguidas. Espera unos minutos.")
    _checks.append(now)


ProviderName = Literal["cloud", "local", "vllm"]


class ParamsIn(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=8192, ge=1, le=200_000)
    top_p: float | None = Field(default=None, gt=0, le=1)
    timeout_seconds: float = Field(default=120, ge=1, le=900)
    context_window: int | None = Field(default=None, ge=512)
    structured_output: Literal["auto", "json_schema", "function_calling", "json_mode"] = "auto"


class ProviderIn(BaseModel):
    vendor: str = Field(max_length=40)
    enabled: bool = True
    base_url: str = Field(default="", max_length=500)
    api_key: str | None = Field(default=None, max_length=1000)  # empty = keep the stored one
    clear_api_key: bool = False
    default_model: str = Field(default="", max_length=200)
    manual_models: list[str] = Field(default_factory=list, max_length=100)
    discovery_enabled: bool = True
    params: ParamsIn = ParamsIn()


class SaveProviderIn(ProviderIn):
    expected_revision: int | None = None


class RoutingIn(BaseModel):
    default_provider: Literal["auto", "cloud", "local", "vllm"]
    auto_order: list[ProviderName] = Field(min_length=1, max_length=3)
    health_ttl_seconds: int = Field(default=30, ge=0, le=3600)
    preflight_check: bool = True
    runtime_fallback: bool = True
    expected_revision: int | None = None


class HealthIn(BaseModel):
    provider: ProviderName
    model: str | None = Field(default=None, max_length=200)
    refresh: bool = False


def _provider_out(settings: ProviderSettings) -> dict:
    adapter = get_adapter(settings.vendor)
    return {
        "provider": settings.kind.value,
        "label": PROVIDER_LABELS[settings.kind.value],
        "vendor": settings.vendor,
        "vendor_label": adapter.label,
        "enabled": settings.enabled,
        "base_url": settings.base_url,
        "effective_base_url": adapter.base_url(settings),
        "api_key_set": bool(settings.api_key),
        "api_key_hint": settings.api_key_hint,
        "requires_api_key": adapter.requires_api_key,
        "default_model": settings.default_model,
        "manual_models": list(settings.manual_models),
        "discovered_models": list(settings.discovered_models),
        "models": settings.models,
        "discovery_enabled": settings.discovery_enabled,
        "params": dataclasses.asdict(settings.params),
        "revision": settings.revision,
        "updated_at": settings.updated_at,
        "origin": settings.origin,
    }


def _routing_out(routing) -> dict:
    return {
        "default_provider": routing.default_provider,
        "auto_order": list(routing.auto_order),
        "health_ttl_seconds": routing.health_ttl_seconds,
        "preflight_check": routing.preflight_check,
        "runtime_fallback": routing.runtime_fallback,
        "revision": routing.revision,
        "updated_at": routing.updated_at,
        "origin": routing.origin,
    }


def _to_input(body: ProviderIn) -> llm_settings.ProviderInput:
    return llm_settings.ProviderInput(
        vendor=body.vendor,
        enabled=body.enabled,
        base_url=body.base_url,
        api_key=body.api_key,
        clear_api_key=body.clear_api_key,
        default_model=body.default_model,
        manual_models=body.manual_models,
        discovery_enabled=body.discovery_enabled,
        params=body.params.model_dump(),
    )


async def _candidate(kind: ProviderKind, body: ProviderIn) -> tuple[ProviderSettings, ProviderSettings, str | None]:
    providers, _ = await llm_settings.load()
    current = providers[kind]
    try:
        validated, new_key = llm_settings.validate_provider(kind, _to_input(body), current)
    except llm_settings.LLMSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current, validated, new_key


async def _record_health(result, *, context: dict) -> None:
    await get_observability().emit(
        "INFO" if result.ok else "WARNING",
        "llm",
        "llm.health_check",
        f"{PROVIDER_LABELS[result.provider]} · {result.model or '—'}: {HEALTH_LABELS[result.status]}"
        + (f" ({result.detail})" if result.detail and not result.ok else ""),
        status=result.status.value,
        duration_ms=result.latency_ms,
        context={"provider": result.provider, "model": result.model, **context},
    )


# ---- members --------------------------------------------------------------------------------


@router.get("/catalog")
async def catalog(user: CurrentUser = Depends(require_user)):
    layer = await llm_settings.get_layer()
    default = await llm_runtime.default_selection(user)
    providers = []
    for kind in ProviderKind:
        settings = layer.providers[kind]
        adapter = get_adapter(settings.vendor)
        problem = adapter.configuration_problem(settings, settings.default_model)
        providers.append(
            {
                "provider": kind.value,
                "label": PROVIDER_LABELS[kind.value],
                "vendor_label": adapter.label,
                "enabled": settings.enabled,
                "configured": problem is None,
                "problem": problem,
                "default_model": settings.default_model,
                "models": settings.models,
            }
        )
    return {
        "selectable": list(SELECTABLE_PROVIDERS),
        "providers": providers,
        "routing": {
            "default_provider": layer.routing.default_provider,
            "auto_order": list(layer.routing.auto_order),
            "auto_candidates": layer.auto_candidates(),
            "preflight_check": layer.routing.preflight_check,
            "runtime_fallback": layer.routing.runtime_fallback,
        },
        "default_selection": {"provider": default.provider, "model": default.model},
    }


@router.post("/health")
async def health(body: HealthIn, _: CurrentUser = Depends(require_user)):
    _rate_limit()
    layer = await llm_settings.get_layer()
    result = await layer.health(body.provider, body.model, use_cache=not body.refresh)
    await _record_health(result, context={"trigger": "selector"})
    return result.as_dict()


# ---- admins ------------------------------------------------------------------------------------


@router.get("/providers")
async def list_providers(_: CurrentUser = Depends(require_admin)):
    providers, routing = await llm_settings.load()
    return {
        "providers": [_provider_out(providers[k]) for k in ProviderKind],
        "routing": _routing_out(routing),
        "vendors": vendor_catalog(),
        "encryption_ready": secret_box.is_ready(),
    }


@router.post("/providers/{kind}/test")
async def test_provider(kind: ProviderName, body: ProviderIn, _: CurrentUser = Depends(require_admin)):
    _rate_limit()
    provider = ProviderKind(kind)
    _, validated, new_key = await _candidate(provider, body)
    candidate = llm_settings.with_key(dataclasses.replace(validated, enabled=True), new_key)
    result = await get_adapter(candidate.vendor).health(candidate, candidate.default_model)
    await _record_health(result, context={"trigger": "admin_test"})
    await audit.record(
        "llm.provider_tested",
        module="ia",
        result="success" if result.ok else "failure",
        resource_type="llm_provider",
        resource_id=kind,
        context={"vendor": candidate.vendor, "model": candidate.default_model, "status": result.status.value,
                 "latency_ms": result.latency_ms, "base_url": get_adapter(candidate.vendor).base_url(candidate)},
    )
    return {**result.as_dict(), "models": list(result.models)}


@router.post("/providers/{kind}/models/refresh")
async def refresh_models(kind: ProviderName, _: CurrentUser = Depends(require_admin)):
    _rate_limit()
    provider = ProviderKind(kind)
    providers, _ = await llm_settings.load()
    settings = providers[provider]
    adapter = get_adapter(settings.vendor)
    started = time.monotonic()
    try:
        models = [m.id for m in await adapter.list_models(dataclasses.replace(settings, enabled=True))]
    except Exception as exc:  # noqa: BLE001 - reported to the admin, classified
        from app.llm.errors import classify_error, safe_error_message

        status = classify_error(exc)
        detail = safe_error_message(exc)
        await audit.record("llm.models_refreshed", module="ia", result="failure", resource_type="llm_provider",
                           resource_id=kind, context={"error": detail})
        label = HEALTH_LABELS[status] if status else "Error"
        raise HTTPException(status_code=502, detail=f"No se pudieron obtener los modelos: {label}. {detail}") from None
    await llm_settings.save_discovered_models(provider, models)
    await audit.record("llm.models_refreshed", module="ia", resource_type="llm_provider", resource_id=kind,
                       context={"count": len(models), "latency_ms": int((time.monotonic() - started) * 1000)})
    return {"provider": kind, "models": models}


@router.put("/providers/{kind}")
async def save_provider(kind: ProviderName, body: SaveProviderIn, user: CurrentUser = Depends(require_admin)):
    provider = ProviderKind(kind)
    current, validated, new_key = await _candidate(provider, body)
    try:
        saved = await llm_settings.save_provider(
            provider, validated, new_key, expected_revision=body.expected_revision, user=user
        )
    except llm_settings.RevisionConflict:
        raise HTTPException(
            status_code=409, detail="Otro administrador cambió este proveedor mientras lo editabas. Recarga la página."
        ) from None
    except secret_box.SecretBoxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fields = ("vendor", "enabled", "base_url", "default_model", "manual_models", "discovery_enabled")
    changes = {
        f: {"antes": getattr(current, f), "despues": getattr(saved, f)}
        for f in fields
        if getattr(current, f) != getattr(saved, f)
    }
    if current.params != saved.params:
        changes["params"] = {"antes": dataclasses.asdict(current.params), "despues": dataclasses.asdict(saved.params)}
    await audit.record(
        "llm.provider_settings_updated",
        module="ia",
        resource_type="llm_provider",
        resource_id=kind,
        context={"changes": changes, "api_key_changed": new_key is not None, "revision": saved.revision},
    )
    if "default_model" in changes:
        await audit.record("llm.model_changed", module="ia", resource_type="llm_provider", resource_id=kind,
                           context=changes["default_model"])
    await get_observability().emit(
        "INFO", "config", "llm.provider_settings_updated",
        f"Proveedor de IA {PROVIDER_LABELS[kind]} actualizado ({', '.join(sorted(changes)) or 'sin cambios visibles'})",
        context={"provider": kind, "fields": sorted(changes), "api_key_changed": new_key is not None},
    )
    return _provider_out(saved)


@router.get("/routing")
async def get_routing(_: CurrentUser = Depends(require_admin)):
    _, routing = await llm_settings.load()
    return _routing_out(routing)


@router.put("/routing")
async def save_routing(body: RoutingIn, user: CurrentUser = Depends(require_admin)):
    _, current = await llm_settings.load()
    try:
        validated = llm_settings.validate_routing(
            llm_settings.RoutingInput(body.default_provider, list(body.auto_order), body.health_ttl_seconds,
                                      body.preflight_check, body.runtime_fallback),
            current,
        )
        saved = await llm_settings.save_routing(validated, expected_revision=body.expected_revision, user=user)
    except llm_settings.LLMSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm_settings.RevisionConflict:
        raise HTTPException(status_code=409, detail="La configuración cambió mientras la editabas. Recarga la página.") from None
    changes = {
        f: {"antes": getattr(current, f), "despues": getattr(saved, f)}
        for f in ("default_provider", "auto_order", "health_ttl_seconds", "preflight_check", "runtime_fallback")
        if getattr(current, f) != getattr(saved, f)
    }
    await audit.record("llm.routing_updated", module="ia", resource_type="llm_routing", resource_id="default",
                       context={"changes": changes, "revision": saved.revision})
    await get_observability().emit(
        "INFO", "config", "llm.routing_updated",
        f"Enrutamiento de IA actualizado: predeterminado {PROVIDER_LABELS[saved.default_provider]}, "
        f"AUTO {' → '.join(PROVIDER_LABELS[p] for p in saved.auto_order)}",
        context={"fields": sorted(changes)},
    )
    return _routing_out(saved)
