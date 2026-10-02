"""Fuente de Datos: connection settings of the alarm source, managed from the app.

Where things live:
* Supabase `in_source_settings` (one row) -- protocol, host/IP, base path, the
  Alertas (alarms export) and Notificaciones (indicators page) endpoints,
  username, TLS policy, timeout, row limit, reconciliation flag. Changing the
  IP is editing `host` from the app: no code, no restart.
* the source password, in that same row but **encrypted** (Fernet) with
  SOURCE_SECRET_KEY, which exists only in the backend's environment. Members
  can read the row (the backend needs it to fetch data on their behalf), never
  the clear password; the API never returns it, not even masked-but-real.
* SOURCE_* in backend/.env only bootstrap a fresh install (no row yet).

The acquisition layer (app/ingestion) does not know any of this: it receives a
plain SourceConfig through `effective_config()`.
"""
import ipaddress
import logging
import re
import time
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from app.config.settings import get_settings
from app.ingestion.config import SourceConfig
from app.security import secret_box
from app.security.context import CurrentUser
from app.services import supabase_rest as db
from app.services.db import now_iso

logger = logging.getLogger(__name__)

TABLE = "in_source_settings"
ROW_ID = "default"
_CACHE_TTL_SECONDS = 30
_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(\.(?!-)[a-zA-Z0-9-]{1,63}(?<!-))*$")


class SourceSettingsError(ValueError):
    """Invalid input or an unusable stored value; the message is safe to show to the user."""


@dataclass(frozen=True)
class SourceSettings:
    scheme: str = "http"
    host: str = ""
    base_path: str = ""
    alarms_path: str = "/detallado_alarmas.php"
    notifications_path: str = "/indicadores.php"
    username: str = ""
    password_ciphertext: str | None = None
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    alarms_limit: int = 1000
    reconcile_indicators: bool = True
    revision: int = 0
    updated_at: str | None = None
    updated_by: str | None = None
    origin: str = "env"  # "app" (saved from Fuente de Datos) | "env" (backend/.env bootstrap)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}{self.base_path}" if self.host else ""


# ---- validation -------------------------------------------------------------------


def normalize_host(value: str) -> str:
    host = (value or "").strip().lower()
    if not host:
        raise SourceSettingsError("Indica la IP o el nombre del servidor, p. ej. 10.2.85.8.")
    if "://" in host or "/" in host or "@" in host or "?" in host or " " in host:
        raise SourceSettingsError("El host es solo la IP o el nombre (y opcionalmente :puerto), sin http:// ni rutas.")
    name, port = host, None
    if host.startswith("["):  # [IPv6]:port
        end = host.find("]")
        if end == -1:
            raise SourceSettingsError("Dirección IPv6 mal escrita.")
        name, rest = host[1:end], host[end + 1 :]
        if rest:
            if not rest.startswith(":"):
                raise SourceSettingsError("Dirección IPv6 mal escrita.")
            port = rest[1:]
    elif host.count(":") == 1:
        name, port = host.split(":")
    if port is not None:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise SourceSettingsError("El puerto debe ser un número entre 1 y 65535.")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        if not _HOSTNAME.match(name):
            raise SourceSettingsError(f"«{name}» no es una IP ni un nombre de servidor válido.") from None
    return host


def normalize_base_path(value: str) -> str:
    path = (value or "").strip()
    if not path or path == "/":
        return ""
    if not path.startswith("/"):
        path = "/" + path
    if any(ch in path for ch in "?#@ \\") or "//" in path or ".." in path:
        raise SourceSettingsError("La ruta base no es válida (sin espacios, parámetros ni '..'), p. ej. /ProyectoSOC/views.")
    return path.rstrip("/")


def normalize_endpoint(value: str, label: str) -> str:
    path = (value or "").strip()
    if not path:
        raise SourceSettingsError(f"Indica la ruta de {label}.")
    parts = urlsplit(path)
    if parts.scheme:
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SourceSettingsError(f"La URL de {label} debe empezar con http:// o https:// e incluir el servidor.")
        if parts.username or parts.password:
            raise SourceSettingsError(f"No incluyas usuario ni contraseña dentro de la URL de {label}.")
    elif not path.startswith("/"):
        path = "/" + path
    if parts.query or parts.fragment or " " in path or ".." in path:
        raise SourceSettingsError(
            f"La ruta de {label} no debe incluir parámetros (?…), fragmentos (#…), espacios ni '..'."
        )
    return path


def normalize_username(value: str) -> str:
    username = (value or "").strip()
    if not username:
        raise SourceSettingsError("Indica el usuario de la fuente.")
    if len(username) > 256 or any(ch in username for ch in "\r\n\t"):
        raise SourceSettingsError("El usuario no es válido.")
    return username


def check_password(value: str) -> str:
    if len(value) > 512 or any(ch in value for ch in "\r\n"):
        raise SourceSettingsError("La contraseña no es válida.")
    return value


# ---- secret box -------------------------------------------------------------------


def _fernet():
    try:
        return secret_box.fernet()
    except secret_box.SecretBoxError as exc:
        raise SourceSettingsError(str(exc)) from exc


def encrypt_password(password: str) -> str:
    try:
        return secret_box.encrypt(password)
    except secret_box.SecretBoxError as exc:
        raise SourceSettingsError(str(exc)) from exc


def decrypt_password(ciphertext: str) -> str:
    try:
        return secret_box.decrypt(ciphertext, what="La contraseña guardada")
    except secret_box.SecretBoxError as exc:
        raise SourceSettingsError(str(exc)) from exc


# ---- load / save ------------------------------------------------------------------


def settings_from_env(app_settings=None) -> SourceSettings:
    s = app_settings or get_settings()
    parts = urlsplit(s.source_base_url.strip())
    return SourceSettings(
        scheme=parts.scheme if parts.scheme in ("http", "https") else "http",
        host=parts.netloc,
        base_path=parts.path.rstrip("/"),
        alarms_path=s.source_alarms_path,
        notifications_path=s.source_indicators_path,
        username=s.source_username,
        verify_tls=s.source_verify_tls,
        timeout_seconds=s.source_timeout_seconds,
        alarms_limit=s.source_alarms_limit,
        reconcile_indicators=s.source_reconcile_indicators,
        origin="env",
    )


def _from_row(row: dict) -> SourceSettings:
    return SourceSettings(
        scheme=row.get("scheme") or "http",
        host=row.get("host") or "",
        base_path=row.get("base_path") or "",
        alarms_path=row.get("alarms_path") or "/detallado_alarmas.php",
        notifications_path=row.get("notifications_path") or "/indicadores.php",
        username=row.get("username") or "",
        password_ciphertext=row.get("password_ciphertext"),
        verify_tls=bool(row.get("verify_tls", True)),
        timeout_seconds=float(row.get("timeout_seconds") or 30),
        alarms_limit=int(row.get("alarms_limit") or 1000),
        reconcile_indicators=bool(row.get("reconcile_indicators", True)),
        revision=int(row.get("revision") or 0),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
        origin="app",
    )


_cache: tuple[float, SourceSettings | None] | None = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


async def load_saved() -> SourceSettings | None:
    """The row saved from the app, or None. Needs a member in the request context (RLS)."""
    global _cache
    if _cache and _cache[0] > time.monotonic():
        return _cache[1]
    rows = await db.select(TABLE, filters={"id": ROW_ID})
    saved = _from_row(rows[0]) if rows else None
    _cache = (time.monotonic() + _CACHE_TTL_SECONDS, saved)
    return saved


async def current_settings() -> SourceSettings:
    try:
        saved = await load_saved()
    except Exception:  # noqa: BLE001 - no Supabase/user (CLI, startup): the environment still works
        logger.debug("Fuente: sin acceso a in_source_settings; se usan los valores de backend/.env")
        saved = None
    return saved or settings_from_env()


def to_source_config(settings: SourceSettings, app_settings=None) -> SourceConfig:
    """SourceConfig for the acquisition layer. A password that cannot be decrypted counts as missing."""
    env = app_settings or get_settings()
    if settings.origin == "app":
        password = ""
        if settings.password_ciphertext:
            try:
                password = decrypt_password(settings.password_ciphertext)
            except SourceSettingsError as exc:
                logger.error("Fuente: %s", exc)
    else:
        password = env.source_password.get_secret_value()
    base = SourceConfig.from_settings(env)
    return replace(
        base,
        base_url=settings.base_url,
        alarms_path=settings.alarms_path,
        indicators_path=settings.notifications_path,
        username=settings.username,
        password=password,
        verify_tls=settings.verify_tls,
        timeout_seconds=settings.timeout_seconds,
        alarms_limit=settings.alarms_limit,
        reconcile_with_indicators=settings.reconcile_indicators,
    )


async def effective_config() -> SourceConfig:
    return to_source_config(await current_settings())


def missing_fields(config: SourceConfig) -> list[str]:
    """What still has to be filled in before the source can be queried, in user terms."""
    missing = []
    if not urlsplit(config.base_url).hostname:
        missing.append("la IP o el host del servidor")
    if not config.username:
        missing.append("el usuario")
    if not config.password:
        missing.append("la contraseña")
    return missing


async def configuration_problems() -> list[str]:
    """[] when reports can query the source (or the app runs on mock data)."""
    if get_settings().data_provider != "http":
        return []
    return missing_fields(await effective_config())


@dataclass(frozen=True)
class SourceSettingsInput:
    scheme: str
    host: str
    base_path: str
    alarms_path: str
    notifications_path: str
    username: str
    password: str | None  # None/"" = keep the stored one
    verify_tls: bool
    timeout_seconds: float
    alarms_limit: int
    reconcile_indicators: bool


def validate_input(data: SourceSettingsInput, current: SourceSettings) -> tuple[SourceSettings, str | None]:
    """(validated settings without the secret, the new clear password or None to keep)."""
    if data.scheme not in ("http", "https"):
        raise SourceSettingsError("El protocolo debe ser http o https.")
    if not 1 <= data.timeout_seconds <= 300:
        raise SourceSettingsError("El tiempo de espera debe estar entre 1 y 300 segundos.")
    if not 1 <= data.alarms_limit <= 100000:
        raise SourceSettingsError("El límite de filas debe estar entre 1 y 100000.")
    new_password = check_password(data.password) if data.password else None
    if new_password is None and not (current.password_ciphertext or current.origin == "env"):
        raise SourceSettingsError("Indica la contraseña de la fuente.")
    validated = replace(
        current,
        scheme=data.scheme,
        host=normalize_host(data.host),
        base_path=normalize_base_path(data.base_path),
        alarms_path=normalize_endpoint(data.alarms_path, "Alertas"),
        notifications_path=normalize_endpoint(data.notifications_path, "Notificaciones"),
        username=normalize_username(data.username),
        verify_tls=data.verify_tls,
        timeout_seconds=float(data.timeout_seconds),
        alarms_limit=int(data.alarms_limit),
        reconcile_indicators=data.reconcile_indicators,
    )
    return validated, new_password


def candidate_config(validated: SourceSettings, new_password: str | None, current: SourceSettings) -> SourceConfig:
    """The SourceConfig the proposed values would produce (for a connection test)."""
    config = to_source_config(replace(validated, origin=current.origin))
    return replace(config, password=new_password) if new_password else config


class RevisionConflict(Exception):
    pass


async def save(
    validated: SourceSettings, new_password: str | None, *, expected_revision: int | None, user: CurrentUser
) -> SourceSettings:
    existing_rows = await db.select(TABLE, filters={"id": ROW_ID})
    existing = _from_row(existing_rows[0]) if existing_rows else None
    if expected_revision is not None and existing and existing.revision != expected_revision:
        raise RevisionConflict()

    if new_password:
        ciphertext = encrypt_password(new_password)
    elif existing and existing.password_ciphertext:
        ciphertext = existing.password_ciphertext
    else:  # first save keeps the bootstrap password from backend/.env
        env_password = get_settings().source_password.get_secret_value()
        if not env_password:
            raise SourceSettingsError("Indica la contraseña de la fuente.")
        ciphertext = encrypt_password(env_password)

    row = {
        "id": ROW_ID,
        "scheme": validated.scheme,
        "host": validated.host,
        "base_path": validated.base_path,
        "alarms_path": validated.alarms_path,
        "notifications_path": validated.notifications_path,
        "username": validated.username,
        "password_ciphertext": ciphertext,
        "verify_tls": validated.verify_tls,
        "timeout_seconds": validated.timeout_seconds,
        "alarms_limit": validated.alarms_limit,
        "reconcile_indicators": validated.reconcile_indicators,
        "revision": (existing.revision if existing else 0) + 1,
        "updated_at": now_iso(),
        "updated_by": user.member_id,
    }
    if existing:
        stored = await db.update(TABLE, {"id": ROW_ID}, {k: v for k, v in row.items() if k != "id"})
    else:
        stored = await db.insert(TABLE, row)
    invalidate_cache()
    return _from_row(stored or row)
