"""Configuración > Proveedores de IA: persistence of the LLM Provider Layer's settings.

* in_llm_providers (one row per slot: cloud, local, vllm) -- vendor, endpoint,
  API key (ENCRYPTED, see app/security/secret_box.py; only its last 4
  characters are kept in clear as a hint), default model, manual and
  discovered models, inference parameters.
* in_llm_routing (one row) -- default provider, AUTO priority order, health
  check TTL, pre-flight check, runtime fallback.
* backend/.env (ANTHROPIC_API_KEY, LLM_MODEL, VLLM_*, LOCAL_LLM_*) only seeds a
  slot until it is saved from the app.

The LLM layer itself (app/llm) never reads this module: it receives plain
ProviderSettings / RoutingSettings.
"""
import logging
import time
from dataclasses import asdict, dataclass, replace
from urllib.parse import urlsplit

from app.config.settings import get_settings
from app.llm.layer import HealthCache, LLMProviderLayer
from app.llm.registry import vendors_for
from app.llm.types import (
    SELECTABLE_PROVIDERS,
    LLMParams,
    ProviderKind,
    ProviderSettings,
    RoutingSettings,
)
from app.security import secret_box
from app.security.context import CurrentUser
from app.services import supabase_rest as db
from app.services.db import now_iso

logger = logging.getLogger(__name__)

PROVIDERS_TABLE = "in_llm_providers"
ROUTING_TABLE = "in_llm_routing"
_CACHE_TTL_SECONDS = 30


class LLMSettingsError(ValueError):
    """Invalid input; the message is safe to show."""


class RevisionConflict(Exception):
    pass


# ---- bootstrap from the environment ------------------------------------------------------


def providers_from_env() -> dict[ProviderKind, ProviderSettings]:
    s = get_settings()
    vllm_key = s.vllm_api_key.get_secret_value()
    return {
        ProviderKind.CLOUD: ProviderSettings(
            kind=ProviderKind.CLOUD,
            vendor="anthropic",
            enabled=True,
            api_key=s.anthropic_api_key,
            api_key_hint=secret_box.hint(s.anthropic_api_key),
            default_model=s.llm_model,
            params=LLMParams(),
        ),
        ProviderKind.VLLM: ProviderSettings(
            kind=ProviderKind.VLLM,
            vendor="vllm",
            enabled=bool(s.vllm_base_url),
            base_url=s.vllm_base_url,
            api_key=vllm_key,
            api_key_hint=secret_box.hint(vllm_key),
            default_model=s.vllm_model,
            params=LLMParams(),
        ),
        ProviderKind.LOCAL: ProviderSettings(
            kind=ProviderKind.LOCAL,
            vendor=s.local_llm_runtime if s.local_llm_runtime in vendors_for(ProviderKind.LOCAL) else "ollama",
            enabled=bool(s.local_llm_base_url),
            base_url=s.local_llm_base_url,
            default_model=s.local_llm_model,
            params=LLMParams(),
        ),
    }


def routing_from_env() -> RoutingSettings:
    s = get_settings()
    order = tuple(p.strip() for p in s.llm_auto_order.split(",") if p.strip() in {k.value for k in ProviderKind})
    default = s.llm_default_provider if s.llm_default_provider in SELECTABLE_PROVIDERS else "cloud"
    return RoutingSettings(default_provider=default, auto_order=order or ("cloud",))


# ---- rows <-> settings ----------------------------------------------------------------------


def _params_from_row(data: dict | None) -> LLMParams:
    base = LLMParams()
    try:
        return base.merged(data or {})
    except (TypeError, ValueError):
        return base


def _provider_from_row(row: dict, env: ProviderSettings) -> ProviderSettings:
    api_key = ""
    if row.get("api_key_ciphertext"):
        try:
            api_key = secret_box.decrypt(row["api_key_ciphertext"], what="La API key guardada")
        except secret_box.SecretBoxError as exc:
            logger.error("Proveedor de IA %s: %s", row.get("kind"), exc)
    return ProviderSettings(
        kind=ProviderKind(row["kind"]),
        vendor=row.get("vendor") or env.vendor,
        enabled=bool(row.get("enabled", True)),
        base_url=row.get("base_url") or "",
        api_key=api_key,
        api_key_hint=row.get("api_key_hint"),
        default_model=row.get("default_model") or "",
        manual_models=tuple(row.get("manual_models") or ()),
        discovered_models=tuple(row.get("discovered_models") or ()),
        discovery_enabled=bool(row.get("discovery_enabled", True)),
        params=_params_from_row(row.get("params")),
        revision=int(row.get("revision") or 0),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
        origin="app",
    )


def _routing_from_row(row: dict) -> RoutingSettings:
    order = tuple(p for p in (row.get("auto_order") or ()) if p in {k.value for k in ProviderKind})
    return RoutingSettings(
        default_provider=row.get("default_provider") if row.get("default_provider") in SELECTABLE_PROVIDERS else "cloud",
        auto_order=order or ("cloud",),
        health_ttl_seconds=int(row.get("health_ttl_seconds") or 30),
        preflight_check=bool(row.get("preflight_check", True)),
        runtime_fallback=bool(row.get("runtime_fallback", True)),
        revision=int(row.get("revision") or 0),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
        origin="app",
    )


# ---- load (cached) ---------------------------------------------------------------------------

_cache: tuple[float, dict[ProviderKind, ProviderSettings], RoutingSettings] | None = None
_health_cache = HealthCache()


def invalidate_cache() -> None:
    global _cache
    _cache = None
    _health_cache.clear()


async def load() -> tuple[dict[ProviderKind, ProviderSettings], RoutingSettings]:
    """Saved settings over the environment bootstrap. Needs a member in context (RLS);
    without one (CLI, offline evals) the environment values are used."""
    global _cache
    if _cache and _cache[0] > time.monotonic():
        return _cache[1], _cache[2]
    providers = providers_from_env()
    routing = routing_from_env()
    try:
        for row in await db.select(PROVIDERS_TABLE):
            kind = ProviderKind(row["kind"])
            providers[kind] = _provider_from_row(row, providers[kind])
        rows = await db.select(ROUTING_TABLE, filters={"id": "default"})
        if rows:
            routing = _routing_from_row(rows[0])
    except Exception:  # noqa: BLE001 - no Supabase/user: the environment bootstrap still works
        logger.debug("Proveedores de IA: sin acceso a Supabase; se usan los valores de backend/.env")
        return providers, routing
    _cache = (time.monotonic() + _CACHE_TTL_SECONDS, providers, routing)
    return providers, routing


async def get_layer() -> LLMProviderLayer:
    providers, routing = await load()
    return LLMProviderLayer(providers, routing, _health_cache)


# ---- validation --------------------------------------------------------------------------------


def normalize_base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMSettingsError("La URL debe empezar con http:// o https:// e incluir el servidor, p. ej. http://llm-server:8000.")
    if parts.username or parts.password:
        raise LLMSettingsError("No incluyas usuario ni contraseña en la URL; usa el campo de API key.")
    if parts.query or parts.fragment:
        raise LLMSettingsError("La URL no debe incluir parámetros (?…) ni fragmentos (#…).")
    try:
        parts.port  # noqa: B018 - raises for an invalid port
    except ValueError as exc:
        raise LLMSettingsError("El puerto de la URL no es válido.") from exc
    return url


def _clean_models(models: list[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for model in models:
        model = (model or "").strip()
        if model and model not in seen:
            if len(model) > 200 or any(c in model for c in "\r\n\t"):
                raise LLMSettingsError(f"Nombre de modelo no válido: {model[:40]!r}.")
            seen.append(model)
    return tuple(seen[:100])


def _validate_params(params: dict) -> LLMParams:
    p = LLMParams().merged(params)
    if p.temperature is not None and not 0 <= p.temperature <= 2:
        raise LLMSettingsError("La temperatura debe estar entre 0 y 2.")
    if p.top_p is not None and not 0 < p.top_p <= 1:
        raise LLMSettingsError("Top P debe estar entre 0 y 1.")
    if p.max_tokens is not None and not 1 <= p.max_tokens <= 200_000:
        raise LLMSettingsError("Max tokens debe estar entre 1 y 200000.")
    if not 1 <= p.timeout_seconds <= 900:
        raise LLMSettingsError("El tiempo de espera debe estar entre 1 y 900 segundos.")
    if p.context_window is not None and not 512 <= p.context_window <= 10_000_000:
        raise LLMSettingsError("La ventana de contexto no es válida.")
    if p.structured_output not in ("auto", "json_schema", "function_calling", "json_mode"):
        raise LLMSettingsError("Método de salida estructurada no válido.")
    return p


@dataclass(frozen=True)
class ProviderInput:
    vendor: str
    enabled: bool
    base_url: str
    api_key: str | None  # None/"" = keep the stored one
    clear_api_key: bool
    default_model: str
    manual_models: list[str]
    discovery_enabled: bool
    params: dict


def validate_provider(kind: ProviderKind, data: ProviderInput, current: ProviderSettings) -> tuple[ProviderSettings, str | None]:
    """(validated settings with the CURRENT key, the new clear key / "" to clear / None to keep)."""
    if data.vendor not in vendors_for(kind):
        raise LLMSettingsError(f"«{data.vendor}» no es un proveedor válido para {kind.value}.")
    model = (data.default_model or "").strip()
    if len(model) > 200:
        raise LLMSettingsError("Nombre de modelo demasiado largo.")
    new_key: str | None = None
    if data.clear_api_key:
        new_key = ""
    elif data.api_key:
        if len(data.api_key) > 1000 or any(c in data.api_key for c in "\r\n "):
            raise LLMSettingsError("La API key no es válida.")
        new_key = data.api_key.strip()
    validated = replace(
        current,
        vendor=data.vendor,
        enabled=data.enabled,
        base_url=normalize_base_url(data.base_url),
        default_model=model,
        manual_models=_clean_models(data.manual_models),
        discovery_enabled=data.discovery_enabled,
        params=_validate_params(data.params),
    )
    return validated, new_key


def with_key(settings: ProviderSettings, new_key: str | None) -> ProviderSettings:
    if new_key is None:
        return settings
    return replace(settings, api_key=new_key, api_key_hint=secret_box.hint(new_key))


# ---- save ---------------------------------------------------------------------------------------


async def save_provider(
    kind: ProviderKind, validated: ProviderSettings, new_key: str | None, *, expected_revision: int | None,
    user: CurrentUser,
) -> ProviderSettings:
    rows = await db.select(PROVIDERS_TABLE, filters={"kind": kind.value})
    existing = rows[0] if rows else None
    if expected_revision is not None and existing and int(existing.get("revision") or 0) != expected_revision:
        raise RevisionConflict()

    if new_key is not None:
        ciphertext = secret_box.encrypt(new_key) if new_key else None
        key_hint = secret_box.hint(new_key) if new_key else None
    elif existing:
        ciphertext, key_hint = existing.get("api_key_ciphertext"), existing.get("api_key_hint")
    else:  # first save keeps the bootstrap key from backend/.env
        ciphertext = secret_box.encrypt(validated.api_key) if validated.api_key else None
        key_hint = secret_box.hint(validated.api_key) if validated.api_key else None

    row = {
        "kind": kind.value,
        "vendor": validated.vendor,
        "enabled": validated.enabled,
        "base_url": validated.base_url,
        "api_key_ciphertext": ciphertext,
        "api_key_hint": key_hint,
        "default_model": validated.default_model,
        "manual_models": list(validated.manual_models),
        "discovery_enabled": validated.discovery_enabled,
        "params": asdict(validated.params),
        "revision": (int(existing.get("revision") or 0) if existing else 0) + 1,
        "updated_at": now_iso(),
        "updated_by": user.member_id,
    }
    if existing:
        stored = await db.update(PROVIDERS_TABLE, {"kind": kind.value}, {k: v for k, v in row.items() if k != "kind"})
    else:
        row["discovered_models"] = []
        stored = await db.insert(PROVIDERS_TABLE, row)
    invalidate_cache()
    return _provider_from_row(stored or row, providers_from_env()[kind])


async def save_discovered_models(kind: ProviderKind, models: list[str]) -> None:
    """Remember the last discovery so every member's selector can offer them without probing."""
    payload = {"discovered_models": list(_clean_models(models)), "discovered_at": now_iso()}
    rows = await db.select(PROVIDERS_TABLE, filters={"kind": kind.value})
    if rows:
        await db.update(PROVIDERS_TABLE, {"kind": kind.value}, payload)
        invalidate_cache()


@dataclass(frozen=True)
class RoutingInput:
    default_provider: str
    auto_order: list[str]
    health_ttl_seconds: int
    preflight_check: bool
    runtime_fallback: bool


def validate_routing(data: RoutingInput, current: RoutingSettings) -> RoutingSettings:
    if data.default_provider not in SELECTABLE_PROVIDERS:
        raise LLMSettingsError("Proveedor predeterminado no válido.")
    kinds = {k.value for k in ProviderKind}
    order: list[str] = []
    for provider in data.auto_order:
        if provider not in kinds:
            raise LLMSettingsError(f"«{provider}» no puede ir en el orden de AUTO.")
        if provider not in order:
            order.append(provider)
    if not order:
        raise LLMSettingsError("AUTO necesita al menos un proveedor en su orden de prioridad.")
    if not 0 <= data.health_ttl_seconds <= 3600:
        raise LLMSettingsError("La vigencia del health check debe estar entre 0 y 3600 segundos.")
    return replace(
        current,
        default_provider=data.default_provider,
        auto_order=tuple(order),
        health_ttl_seconds=data.health_ttl_seconds,
        preflight_check=data.preflight_check,
        runtime_fallback=data.runtime_fallback,
    )


async def save_routing(validated: RoutingSettings, *, expected_revision: int | None, user: CurrentUser) -> RoutingSettings:
    rows = await db.select(ROUTING_TABLE, filters={"id": "default"})
    existing = rows[0] if rows else None
    if expected_revision is not None and existing and int(existing.get("revision") or 0) != expected_revision:
        raise RevisionConflict()
    row = {
        "id": "default",
        "default_provider": validated.default_provider,
        "auto_order": list(validated.auto_order),
        "health_ttl_seconds": validated.health_ttl_seconds,
        "preflight_check": validated.preflight_check,
        "runtime_fallback": validated.runtime_fallback,
        "revision": (int(existing.get("revision") or 0) if existing else 0) + 1,
        "updated_at": now_iso(),
        "updated_by": user.member_id,
    }
    if existing:
        stored = await db.update(ROUTING_TABLE, {"id": "default"}, {k: v for k, v in row.items() if k != "id"})
    else:
        stored = await db.insert(ROUTING_TABLE, row)
    invalidate_cache()
    return _routing_from_row(stored or row)
