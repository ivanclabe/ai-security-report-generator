import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config.settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"

# In-process brute-force guard on /login (SECURITY_REVIEW.md) -- there was no
# rate limiting at all before this. Deliberately not a new dependency
# (slowapi/redis): this single endpoint, one in-memory sliding window is
# enough for the current single-instance deployment (ARCHITECTURE_TARGET.md's
# scalability notes) -- explicitly NOT correct across multiple replicas
# (each would track its own window), noted as a gap in SECURITY_REVIEW.md
# rather than solved preventively with infrastructure nothing else needs yet.
_LOGIN_ATTEMPT_WINDOW_SECONDS = 300
_LOGIN_ATTEMPT_LIMIT = 10
_login_attempts: dict[str, list[float]] = defaultdict(list)


def reset_login_rate_limit() -> None:
    """Test-only escape hatch -- _login_attempts is process-global state, and
    each test hitting /login (directly or via the shared auth_headers() test
    helper) would otherwise accumulate across the whole pytest run and start
    tripping the real limit. See tests/conftest.py's autouse fixture."""
    _login_attempts.clear()


def _check_login_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    attempts = _login_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < _LOGIN_ATTEMPT_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_ATTEMPT_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos de inicio de sesión. Intenta de nuevo en unos minutos.",
        )
    attempts.append(now)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    username: str


def create_access_token(username: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_token_ttl_hours)
    payload = {"sub": username, "exp": expires_at}
    return jwt.encode(payload, settings.auth_secret_key, algorithm=JWT_ALGORITHM)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    _check_login_rate_limit(request.client.host if request.client else "unknown")
    settings = get_settings()
    if body.username != settings.auth_username or body.password != settings.auth_password:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return LoginResponse(access_token=create_access_token(body.username), username=body.username)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.auth_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return payload["sub"]
