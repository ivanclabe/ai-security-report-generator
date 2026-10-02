"""Authentication and authorization with Supabase Auth.

The frontend signs in with Supabase Auth (email + password) and sends the
session's access token as `Authorization: Bearer <jwt>`. This module:

1. verifies the token locally against the project's published signing keys
   (JWKS, ES256/RS256): signature, expiry, issuer and audience -- no shared
   secret in this backend, no extra round trip per request;
2. checks **membership of this app** (an active in_users row linked to the
   Supabase user): the Supabase project is shared with other applications, so
   being a valid Supabase user is not enough;
3. puts the user and their token in the request context, so every Supabase
   query runs as that user under RLS (app/services/supabase_rest.py).

There is no other login: no passwords are stored or checked here.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import get_settings
from app.security.context import CurrentUser, set_access_token, set_current_user
from app.services import audit
from app.services import supabase_rest as db

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)
_MEMBERSHIP_TTL_SECONDS = 60
_ALGORITHMS = ["ES256", "RS256"]


@dataclass(frozen=True)
class AuthError(Exception):
    code: str
    message: str


class SupabaseTokenVerifier:
    """Verifies Supabase Auth access tokens with the project's JWKS (cached by PyJWT)."""

    def __init__(self, supabase_url: str, audience: str = "authenticated", jwks_client=None):
        self.issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        self.audience = audience
        self._jwks = jwks_client or jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600, timeout=10
        )

    def verify(self, token: str) -> dict:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=10,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("session_expired", "Tu sesión expiró. Inicia sesión de nuevo.") from exc
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthError("auth_unavailable", "No se pudo validar la sesión con Supabase. Intenta de nuevo.") from exc
        except (jwt.PyJWKClientError, jwt.PyJWTError) as exc:
            raise AuthError("invalid_token", "Sesión no válida. Inicia sesión de nuevo.") from exc


@lru_cache
def get_token_verifier() -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(get_settings().supabase_url)


_membership_cache: dict[str, tuple[float, CurrentUser | None]] = {}


def clear_membership_cache() -> None:
    _membership_cache.clear()


async def _load_member(auth_id: str, email: str | None) -> CurrentUser | None:
    cached = _membership_cache.get(auth_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    rows = await db.select("in_users", filters={"auth_user_id": auth_id})
    row = rows[0] if rows else None
    member = None
    if row and row.get("is_active", True):
        member = CurrentUser(
            auth_id=auth_id,
            member_id=row["id"],
            email=row.get("email") or email,
            role=row.get("role") or "operator",
            display_name=row.get("display_name"),
        )
    _membership_cache[auth_id] = (time.monotonic() + _MEMBERSHIP_TTL_SECONDS, member)
    return member


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
    )


async def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _http_error(401, "not_authenticated", "Inicia sesión para continuar.")
    token = credentials.credentials
    try:
        claims = await asyncio.to_thread(get_token_verifier().verify, token)
    except AuthError as exc:
        raise _http_error(401, exc.code, exc.message) from None

    set_access_token(token)  # membership itself is read as this user (RLS: own row only)
    email = claims.get("email")
    try:
        user = await _load_member(claims["sub"], email)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo comprobar la membresía en Supabase: %s", type(exc).__name__)
        raise _http_error(503, "auth_unavailable", "No se pudo comprobar tu acceso. Intenta de nuevo.") from None
    if user is None:
        await audit.record_auth_event(
            "auth.access_denied", email=email, reason="usuario de Supabase sin acceso a esta aplicación"
        )
        raise _http_error(
            403,
            "not_member",
            "Tu cuenta no tiene acceso a esta aplicación. Pide a un administrador que te dé de alta.",
        )
    set_current_user(user)
    return user


async def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if not user.is_admin:
        await audit.record("auth.admin_required", module="auth", result="denied")
        raise _http_error(403, "admin_required", "Esta sección es solo para administradores.")
    return user
