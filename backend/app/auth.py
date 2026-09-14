from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config.settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"


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
async def login(body: LoginRequest):
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
