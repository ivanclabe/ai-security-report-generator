"""Configuración > Fuente de datos: the operator changes the source's address,
username and password from the app, tests the connection, and saves.

* Every route requires the app login (require_auth).
* The password is write-only: no response ever contains it -- GET only says
  whether one is set. Sending an empty password keeps the current one.
* Saving tests the connection first (unless the operator explicitly skips it,
  e.g. while the VPN is down) and then applies the new values to the running
  provider: no restart, and the old session/cache are dropped.
* Tests and saves are rate-limited: each test logs in to the source, and a
  service account behind a lockout policy must not be hammered from here.
"""
import dataclasses
import logging
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.config.settings import get_settings
from app.ingestion.client import SourceClient
from app.ingestion.config import SourceConfig
from app.ingestion.csv_decoder import decode_alarms_csv
from app.ingestion.errors import SourceAuthenticationError, SourceError
from app.ingestion.requests import build_alarms_request
from app.ingestion.source_settings_store import (
    InvalidSourceSettings,
    check_password,
    effective_source_config,
    get_source_settings_store,
    normalize_base_url,
    normalize_username,
)
from app.providers.factory import get_data_provider
from app.providers.http_source import HttpSourceDataProvider
from app.services.company_registry import get_company_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/source-settings", tags=["source-settings"])

_ATTEMPT_WINDOW_SECONDS = 300
_ATTEMPT_LIMIT = 10
_attempts: deque[float] = deque()


def reset_source_settings_rate_limit() -> None:
    """Test-only: the attempt window is process-global state."""
    _attempts.clear()


def _check_rate_limit() -> None:
    now = time.monotonic()
    while _attempts and now - _attempts[0] >= _ATTEMPT_WINDOW_SECONDS:
        _attempts.popleft()
    if len(_attempts) >= _ATTEMPT_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas pruebas de conexión seguidas. Espera unos minutos para no bloquear la cuenta de la fuente.",
        )
    _attempts.append(now)


class SourceSettingsOut(BaseModel):
    base_url: str
    username: str
    password_set: bool
    uses_https: bool
    origin: str  # "app" (saved from this screen) | "env" (backend/.env)
    updated_at: str | None = None
    updated_by: str | None = None
    provider_active: bool  # False when DATA_PROVIDER=mock: the source is not being used


class SourceSettingsIn(BaseModel):
    base_url: str = Field(max_length=2048)
    username: str = Field(max_length=256)
    # Empty/omitted = keep the current password (the UI never receives it to send it back).
    password: str | None = Field(default=None, max_length=512)


class SaveSourceSettingsIn(SourceSettingsIn):
    skip_connection_test: bool = False


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    login_method: str | None = None
    elapsed_seconds: float | None = None


class SaveSourceSettingsOut(BaseModel):
    saved: bool
    test: ConnectionTestOut | None = None
    settings: SourceSettingsOut


def _make_client(config: SourceConfig) -> SourceClient:
    """Seam for tests (an in-memory transport instead of the network)."""
    return SourceClient(config)


def _settings_out() -> SourceSettingsOut:
    settings = get_settings()
    config = effective_source_config(settings)
    overrides = get_source_settings_store(settings).load()
    return SourceSettingsOut(
        base_url=config.base_url,
        username=config.username,
        password_set=bool(config.password),
        uses_https=config.uses_https,
        origin="app" if overrides else "env",
        updated_at=overrides.updated_at if overrides else None,
        updated_by=overrides.updated_by if overrides else None,
        provider_active=settings.data_provider == "http",
    )


def _candidate_config(body: SourceSettingsIn) -> SourceConfig:
    """The config the operator is proposing, on top of the current one; raises 400 on bad input."""
    current = effective_source_config(get_settings())
    try:
        return dataclasses.replace(
            current,
            base_url=normalize_base_url(body.base_url),
            username=normalize_username(body.username),
            password=check_password(body.password if body.password else current.password),
        )
    except InvalidSourceSettings as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _sample_client_name() -> str:
    """Any registered company's `cliente=` -- the test only needs a well-formed request."""
    try:
        companies = await get_company_registry().list_active()
    except Exception:  # noqa: BLE001 -- the registry being down must not block a connection test
        return ""
    return companies[0].request_client_name if companies else ""


async def _test_connection(config: SourceConfig) -> ConnectionTestOut:
    """Log in and download a one-row export: proves address, credentials and format."""
    problems = config.problems()
    if problems:
        return ConnectionTestOut(ok=False, message="Configuración incompleta: " + "; ".join(problems) + ".")
    client = _make_client(dataclasses.replace(config, alarms_limit=1))
    started = time.monotonic()
    try:
        now = datetime.now()
        request = build_alarms_request(
            client.config,
            await _sample_client_name(),
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            now,
        )
        response = await client.fetch(request)
        decode_alarms_csv(response.content)
    except SourceAuthenticationError as exc:
        return ConnectionTestOut(ok=False, message=f"La fuente rechazó el usuario o la contraseña. {exc}")
    except SourceError as exc:
        return ConnectionTestOut(ok=False, message=str(exc))
    finally:
        await client.aclose()
    elapsed = round(time.monotonic() - started, 2)
    method = {"form": "formulario de inicio de sesión", "basic": "Basic Auth"}.get(client.last_login_method or "")
    login = f"inicio de sesión por {method}" if method else "sin inicio de sesión"
    seconds = f"{elapsed:.1f}".replace(".", ",")
    return ConnectionTestOut(
        ok=True,
        message=f"Conexión correcta con {config.host} ({login}, {seconds} s).",
        login_method=client.last_login_method,
        elapsed_seconds=elapsed,
    )


def _running_provider():
    """The provider serving reports, or None if it was not created yet (it will then
    read the saved values when first used)."""
    return get_data_provider() if get_data_provider.cache_info().currsize else None


async def _apply_to_running_provider(config: SourceConfig) -> None:
    provider = _running_provider()
    if isinstance(provider, HttpSourceDataProvider):
        await provider.reconfigure_source(config)


@router.get("", response_model=SourceSettingsOut)
async def get_source_settings(_: str = Depends(require_auth)):
    return _settings_out()


@router.post("/test", response_model=ConnectionTestOut)
async def test_source_settings(body: SourceSettingsIn, _: str = Depends(require_auth)):
    config = _candidate_config(body)
    _check_rate_limit()
    return await _test_connection(config)


@router.put("", response_model=SaveSourceSettingsOut)
async def save_source_settings(body: SaveSourceSettingsIn, username: str = Depends(require_auth)):
    settings = get_settings()
    previous = effective_source_config(settings)
    config = _candidate_config(body)

    test = None
    if not body.skip_connection_test:
        _check_rate_limit()
        test = await _test_connection(config)
        if not test.ok:
            return SaveSourceSettingsOut(saved=False, test=test, settings=_settings_out())

    get_source_settings_store(settings).save(
        base_url=config.base_url, username=config.username, password=config.password, updated_by=username
    )
    await _apply_to_running_provider(effective_source_config(settings))
    logger.info(
        "Fuente de datos reconfigurada desde la app por %s: servidor %s -> %s; usuario %s; contraseña %s%s",
        username,
        previous.host or "(vacío)",
        config.host,
        "cambiado" if config.username != previous.username else "sin cambios",
        "cambiada" if config.password != previous.password else "sin cambios",
        "" if test else " (guardado sin probar la conexión)",
    )
    if not config.uses_https:
        logger.warning("SECURITY: la fuente %s usa http:// -- las credenciales viajan sin cifrar.", config.host)
    return SaveSourceSettingsOut(saved=True, test=test, settings=_settings_out())
