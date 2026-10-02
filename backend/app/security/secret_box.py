"""Encryption of application secrets stored in Supabase (source password, LLM
provider API keys). Fernet (AES-128-CBC + HMAC) with SOURCE_SECRET_KEY, which
exists only in the backend's environment: rows readable by members never
expose a secret in clear, and the frontend never receives one."""
from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import get_settings


class SecretBoxError(ValueError):
    """The message is safe to show."""


def fernet() -> Fernet:
    key = get_settings().source_secret_key.get_secret_value().strip()
    if not key:
        raise SecretBoxError(
            "El servidor no tiene SOURCE_SECRET_KEY configurada, así que no puede guardar secretos de forma "
            "cifrada. Un administrador del servidor debe definirla en backend/.env."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretBoxError("SOURCE_SECRET_KEY no es una clave válida (Fernet, 32 bytes en base64).") from exc


def is_ready() -> bool:
    try:
        fernet()
    except SecretBoxError:
        return False
    return True


def encrypt(value: str) -> str:
    return fernet().encrypt(value.encode()).decode()


def decrypt(token: str, *, what: str = "El secreto guardado") -> str:
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError(
            f"{what} no se puede descifrar (la clave SOURCE_SECRET_KEY cambió). Vuelve a escribirlo en la app."
        ) from exc


def hint(value: str) -> str | None:
    """Last 4 characters, for "••••abcd" in the UI. Nothing for short values."""
    return value[-4:] if len(value) >= 12 else None
