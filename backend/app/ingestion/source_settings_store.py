"""Source address and credentials edited from the app (Configuración > Fuente de datos).

backend/.env stays the starting point; what the operator saves from the app is
written here and takes precedence over it, so the IP or the password can change
without touching the server or restarting. Only the three values an operator
legitimately needs to change are editable: base URL, username, password -- TLS
policy, paths and limits stay in the environment.

Storage is a JSON file next to the backend (SOURCE_SETTINGS_PATH, gitignored;
the persistent volume in Docker), never Supabase and never the browser:

* created with permissions 0600 (only the backend's OS user can read it), the
  same protection the credentials already have in backend/.env;
* written atomically (temp file + rename), so a crash mid-save can never leave
  a half-written file that loses the credentials;
* the password is never returned by the API, logged, or shown in repr().
"""
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.ingestion.config import SourceConfig

logger = logging.getLogger(__name__)

_FILE_MODE = 0o600


class InvalidSourceSettings(ValueError):
    """A value the operator typed cannot be used; the message is safe to show."""


@dataclass(frozen=True)
class SourceOverrides:
    base_url: str | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    updated_at: str | None = None
    updated_by: str | None = None

    def apply_to(self, config: SourceConfig) -> SourceConfig:
        return replace(
            config,
            base_url=self.base_url if self.base_url is not None else config.base_url,
            username=self.username if self.username is not None else config.username,
            password=self.password if self.password is not None else config.password,
        )


def normalize_base_url(value: str) -> str:
    """The source's base URL as typed by an operator, validated and without a trailing slash."""
    url = (value or "").strip()
    if not url:
        raise InvalidSourceSettings("Indica la dirección de la fuente, p. ej. http://10.2.85.8/ProyectoSOC/views.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidSourceSettings(
            "La dirección debe empezar con http:// o https://, p. ej. http://10.2.85.8/ProyectoSOC/views."
        )
    if not parts.hostname:
        raise InvalidSourceSettings("La dirección no tiene servidor (IP o nombre).")
    if parts.username or parts.password or "@" in parts.netloc:
        raise InvalidSourceSettings(
            "No incluyas usuario ni contraseña dentro de la dirección; usa los campos de credenciales."
        )
    if parts.query or parts.fragment:
        raise InvalidSourceSettings("La dirección no debe incluir parámetros (?…) ni fragmentos (#…).")
    try:
        parts.port  # noqa: B018 -- raises ValueError for an out-of-range or non-numeric port
    except ValueError as exc:
        raise InvalidSourceSettings("El puerto de la dirección no es válido.") from exc
    return url.rstrip("/")


def normalize_username(value: str) -> str:
    username = (value or "").strip()
    if not username:
        raise InvalidSourceSettings("Indica el usuario de la fuente.")
    if len(username) > 256 or any(ch in username for ch in "\r\n\t"):
        raise InvalidSourceSettings("El usuario no es válido.")
    return username


def check_password(value: str) -> str:
    if not value:
        raise InvalidSourceSettings("Indica la contraseña de la fuente.")
    if len(value) > 512 or any(ch in value for ch in "\r\n"):
        raise InvalidSourceSettings("La contraseña no es válida.")
    return value


class SourceSettingsStore:
    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> SourceOverrides | None:
        """Saved values, or None if nothing was saved from the app (or the file is unusable)."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.error(
                "No se pudo leer la configuración de la fuente guardada desde la app (%s: %s); "
                "se usan los valores de backend/.env.",
                self._path,
                type(exc).__name__,
            )
            return None
        if not isinstance(raw, dict):
            return None

        def text(key: str) -> str | None:
            value = raw.get(key)
            return value if isinstance(value, str) and value else None

        return SourceOverrides(
            base_url=text("base_url"),
            username=text("username"),
            password=text("password"),
            updated_at=text("updated_at"),
            updated_by=text("updated_by"),
        )

    def save(self, *, base_url: str, username: str, password: str, updated_by: str) -> SourceOverrides:
        overrides = SourceOverrides(
            base_url=normalize_base_url(base_url),
            username=normalize_username(username),
            password=check_password(password),
            updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            updated_by=updated_by,
        )
        payload = json.dumps(
            {
                "base_url": overrides.base_url,
                "username": overrides.username,
                "password": overrides.password,
                "updated_at": overrides.updated_at,
                "updated_by": overrides.updated_by,
            },
            ensure_ascii=False,
            indent=2,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".source_settings.", dir=self._path.parent)
        try:
            os.fchmod(fd, _FILE_MODE)  # before any byte of the password is written
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        return overrides


def get_source_settings_store(settings) -> SourceSettingsStore:
    return SourceSettingsStore(settings.source_settings_path)


def effective_source_config(settings) -> SourceConfig:
    """backend/.env values with whatever the operator saved from the app on top."""
    config = SourceConfig.from_settings(settings)
    overrides = get_source_settings_store(settings).load()
    return overrides.apply_to(config) if overrides else config
