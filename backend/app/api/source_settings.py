"""Fuente de Datos: protocol, host/IP, base path, Alertas and Notificaciones
endpoints, credentials and connection options of the alarm source.

* GET /status          -- any member: is the source ready? (drives the "configure the
                          source first" guidance before generating a report)
* GET, POST /test, PUT -- admins only.
* The password is write-only: no response contains it (GET says only whether
  one is stored). An empty password keeps the stored one.
* Saving tests the connection first unless the admin explicitly skips it (VPN
  down), uses optimistic concurrency (revision) so two admins cannot silently
  overwrite each other, and is audited (what changed; never the password).
* Tests/saves are rate-limited: each test logs in to the source, and a service
  account behind a lockout policy must not be hammered from here.
"""
import dataclasses
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_admin, require_user
from app.config.settings import get_settings
from app.ingestion.client import SourceClient
from app.ingestion.config import SourceConfig
from app.ingestion.csv_decoder import decode_alarms_csv
from app.ingestion.errors import SourceAuthenticationError, SourceError
from app.ingestion.requests import build_alarms_request
from app.security.context import CurrentUser
from app.services import audit
from app.services import source_settings_service as sss
from app.services.company_registry import get_company_registry
from app.services.observability import get_observability

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


class SourceStatusOut(BaseModel):
    configured: bool
    missing: list[str]
    host: str | None
    uses_https: bool
    origin: str
    provider_active: bool


class SourceSettingsOut(BaseModel):
    scheme: str
    host: str
    base_path: str
    alarms_path: str
    notifications_path: str
    alarms_url: str
    notifications_url: str
    username: str
    password_set: bool
    verify_tls: bool
    timeout_seconds: float
    alarms_limit: int
    reconcile_indicators: bool
    origin: str
    revision: int
    updated_at: str | None = None
    updated_by: str | None = None
    provider_active: bool
    encryption_ready: bool


class SourceSettingsIn(BaseModel):
    scheme: str = Field(pattern="^(http|https)$")
    host: str = Field(max_length=260)
    base_path: str = Field(default="", max_length=512)
    alarms_path: str = Field(max_length=1024)
    notifications_path: str = Field(max_length=1024)
    username: str = Field(max_length=256)
    password: str | None = Field(default=None, max_length=512)  # empty = keep the stored one
    verify_tls: bool = True
    timeout_seconds: float = Field(default=30, ge=1, le=300)
    alarms_limit: int = Field(default=1000, ge=1, le=100000)
    reconcile_indicators: bool = True


class SaveSourceSettingsIn(SourceSettingsIn):
    skip_connection_test: bool = False
    expected_revision: int | None = None


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


def _encryption_ready() -> bool:
    try:
        sss._fernet()
    except sss.SourceSettingsError:
        return False
    return True


def _settings_out(settings: sss.SourceSettings) -> SourceSettingsOut:
    config = sss.to_source_config(settings)
    return SourceSettingsOut(
        scheme=settings.scheme,
        host=settings.host,
        base_path=settings.base_path,
        alarms_path=settings.alarms_path,
        notifications_path=settings.notifications_path,
        alarms_url=config.url_for(settings.alarms_path) if settings.host else "",
        notifications_url=config.url_for(settings.notifications_path) if settings.host else "",
        username=settings.username,
        password_set=bool(config.password),
        verify_tls=settings.verify_tls,
        timeout_seconds=settings.timeout_seconds,
        alarms_limit=settings.alarms_limit,
        reconcile_indicators=settings.reconcile_indicators,
        origin=settings.origin,
        revision=settings.revision,
        updated_at=settings.updated_at,
        updated_by=settings.updated_by,
        provider_active=get_settings().data_provider == "http",
        encryption_ready=_encryption_ready(),
    )


def _to_input(body: SourceSettingsIn) -> sss.SourceSettingsInput:
    return sss.SourceSettingsInput(
        scheme=body.scheme,
        host=body.host,
        base_path=body.base_path,
        alarms_path=body.alarms_path,
        notifications_path=body.notifications_path,
        username=body.username,
        password=body.password,
        verify_tls=body.verify_tls,
        timeout_seconds=body.timeout_seconds,
        alarms_limit=body.alarms_limit,
        reconcile_indicators=body.reconcile_indicators,
    )


async def _validated(body: SourceSettingsIn) -> tuple[sss.SourceSettings, sss.SourceSettings, str | None]:
    current = await sss.current_settings()
    try:
        validated, new_password = sss.validate_input(_to_input(body), current)
    except sss.SourceSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return current, validated, new_password


async def _sample_client_name() -> str:
    """Any registered company's `cliente=` -- the test only needs a well-formed request."""
    try:
        companies = await get_company_registry().list_active()
    except Exception:  # noqa: BLE001 - the registry being down must not block a connection test
        return ""
    return companies[0].request_client_name if companies else ""


async def _test_connection(config: SourceConfig) -> ConnectionTestOut:
    """Log in and download a one-row export: proves address, credentials and format."""
    missing = sss.missing_fields(config)
    if missing:
        return ConnectionTestOut(ok=False, message="Falta completar: " + ", ".join(missing) + ".")
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
        result = ConnectionTestOut(ok=False, message=f"La fuente rechazó el usuario o la contraseña. {exc}")
    except SourceError as exc:
        result = ConnectionTestOut(ok=False, message=str(exc))
    else:
        elapsed = round(time.monotonic() - started, 2)
        method = {"form": "formulario de inicio de sesión", "basic": "Basic Auth"}.get(client.last_login_method or "")
        login = f"inicio de sesión por {method}" if method else "sin inicio de sesión"
        seconds = f"{elapsed:.1f}".replace(".", ",")
        result = ConnectionTestOut(
            ok=True,
            message=f"Conexión correcta con {config.host} ({login}, {seconds} s).",
            login_method=client.last_login_method,
            elapsed_seconds=elapsed,
        )
    finally:
        await client.aclose()
    duration_ms = int((time.monotonic() - started) * 1000)
    await get_observability().emit(
        "INFO" if result.ok else "WARNING",
        "source",
        "source.connection_test",
        result.message,
        status="ok" if result.ok else "error",
        duration_ms=duration_ms,
        context={"host": config.host},
    )
    await audit.record(
        "source.connection_tested",
        module="fuente_de_datos",
        result="success" if result.ok else "failure",
        resource_type="source",
        resource_id=config.host,
        context={"host": config.host, "message": result.message},
    )
    return result


_AUDITED_FIELDS = (
    "scheme", "host", "base_path", "alarms_path", "notifications_path", "username",
    "verify_tls", "timeout_seconds", "alarms_limit", "reconcile_indicators",
)


@router.get("/status", response_model=SourceStatusOut)
async def source_status(_: CurrentUser = Depends(require_user)):
    settings = await sss.current_settings()
    config = sss.to_source_config(settings)
    missing = await sss.configuration_problems()
    return SourceStatusOut(
        configured=not missing,
        missing=missing,
        host=config.host or None,
        uses_https=config.uses_https,
        origin=settings.origin,
        provider_active=get_settings().data_provider == "http",
    )


@router.get("", response_model=SourceSettingsOut)
async def get_source_settings(_: CurrentUser = Depends(require_admin)):
    return _settings_out(await sss.current_settings())


@router.post("/test", response_model=ConnectionTestOut)
async def test_source_settings(body: SourceSettingsIn, _: CurrentUser = Depends(require_admin)):
    current, validated, new_password = await _validated(body)
    _check_rate_limit()
    return await _test_connection(sss.candidate_config(validated, new_password, current))


@router.put("", response_model=SaveSourceSettingsOut)
async def save_source_settings(body: SaveSourceSettingsIn, user: CurrentUser = Depends(require_admin)):
    current, validated, new_password = await _validated(body)

    test = None
    if not body.skip_connection_test:
        _check_rate_limit()
        test = await _test_connection(sss.candidate_config(validated, new_password, current))
        if not test.ok:
            return SaveSourceSettingsOut(saved=False, test=test, settings=_settings_out(current))

    try:
        saved = await sss.save(validated, new_password, expected_revision=body.expected_revision, user=user)
    except sss.RevisionConflict:
        raise HTTPException(
            status_code=409,
            detail="Otro administrador cambió la configuración mientras la editabas. Recarga la página y revisa los valores.",
        ) from None
    except sss.SourceSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    changes = {
        name: {"antes": getattr(current, name), "despues": getattr(saved, name)}
        for name in _AUDITED_FIELDS
        if getattr(current, name) != getattr(saved, name)
    }
    await audit.record(
        "source.settings_updated",
        module="fuente_de_datos",
        resource_type="source",
        resource_id=saved.host,
        context={
            "changes": changes,
            "password_changed": new_password is not None,
            "connection_tested": test is not None,
            "revision": saved.revision,
        },
    )
    if any(k in changes for k in ("scheme", "host", "base_path")):
        await audit.record(
            "source.address_changed",
            module="fuente_de_datos",
            resource_type="source",
            resource_id=saved.host,
            context={"antes": current.base_url, "despues": saved.base_url},
        )
    await get_observability().emit(
        "WARNING" if saved.scheme == "http" else "INFO",
        "config",
        "source.settings_updated",
        f"Fuente de datos actualizada ({saved.base_url})"
        + (" -- usa http: las credenciales viajan sin cifrar" if saved.scheme == "http" else ""),
        context={"fields": sorted(changes), "password_changed": new_password is not None},
    )
    return SaveSourceSettingsOut(saved=True, test=test, settings=_settings_out(saved))
