"""The signed-in user: profile, preferences (Configuración) and session events.

Preferences are per user (in_user_preferences, RLS: own row only) and kept
separate from the data-source settings, which are app-wide and admin-only.
"""
import logging
import time
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_user
from app.security.context import CurrentUser
from app.services import audit
from app.services import supabase_rest as db
from app.services.db import now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["me"])


class MeOut(BaseModel):
    email: str | None
    display_name: str | None
    role: str
    is_admin: bool


class Preferences(BaseModel):
    default_format: Literal["docx", "pdf"] = "docx"
    default_audience: str = Field(default="", max_length=40)
    start_page: Literal["/", "/informes/nuevo", "/asistente"] = "/"
    density: Literal["comfortable", "compact"] = "comfortable"
    reduce_motion: bool = False


class PreferencesOut(BaseModel):
    theme: Literal["light", "dark", "system"] = "system"
    preferences: Preferences = Preferences()
    updated_at: str | None = None


class SessionEventIn(BaseModel):
    event: Literal["login", "logout"]


@router.get("/me", response_model=MeOut)
async def get_me(user: CurrentUser = Depends(require_user)):
    return MeOut(email=user.email, display_name=user.display_name, role=user.role, is_admin=user.is_admin)


@router.get("/me/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser = Depends(require_user)):
    rows = await db.select("in_user_preferences", filters={"auth_user_id": user.auth_id})
    if not rows:
        return PreferencesOut()
    row = rows[0]
    try:
        prefs = Preferences.model_validate(row.get("preferences") or {})
    except ValueError:
        prefs = Preferences()  # stored by an older version: fall back to defaults, never fail the page
    return PreferencesOut(theme=row.get("theme") or "system", preferences=prefs, updated_at=row.get("updated_at"))


@router.put("/me/preferences", response_model=PreferencesOut)
async def save_preferences(body: PreferencesOut, user: CurrentUser = Depends(require_user)):
    row = {
        "auth_user_id": user.auth_id,
        "theme": body.theme,
        "preferences": body.preferences.model_dump(),
        "updated_at": now_iso(),
    }
    stored = await db.upsert("in_user_preferences", [row], on_conflict="auth_user_id")
    await audit.record(
        "settings.preferences_updated",
        module="configuracion",
        resource_type="user_preferences",
        resource_id=user.member_id,
        context={"theme": body.theme, **body.preferences.model_dump()},
    )
    saved = stored[0] if stored else row
    return PreferencesOut(
        theme=saved["theme"], preferences=Preferences.model_validate(saved["preferences"]), updated_at=saved["updated_at"]
    )


@router.post("/me/session-events", status_code=204)
async def session_event(body: SessionEventIn, user: CurrentUser = Depends(require_user)):
    """The frontend reports sign-in/sign-out (they happen against Supabase Auth directly)."""
    await audit.record(f"auth.{body.event}", module="auth", resource_type="session", resource_id=user.member_id)


# ---- authentication failures (no session yet) ------------------------------------

_FAILURE_WINDOW_SECONDS = 300
_FAILURE_LIMIT_PER_IP = 20
_failures_by_ip: dict[str, list[float]] = defaultdict(list)


def reset_auth_event_rate_limit() -> None:
    _failures_by_ip.clear()


class AuthFailureIn(BaseModel):
    action: Literal["login_failed", "session_expired"]
    email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    reason: str = Field(default="", max_length=200)


@router.post("/auth/events", status_code=204)
async def auth_failure_event(body: AuthFailureIn, request: Request):
    """Public on purpose: a failed sign-in has no session to authenticate with. Rate-limited
    per client IP, and the database side (in_log_auth_event) accepts only these actions."""
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _failures_by_ip[ip]
    attempts[:] = [t for t in attempts if now - t < _FAILURE_WINDOW_SECONDS]
    if len(attempts) >= _FAILURE_LIMIT_PER_IP:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")
    attempts.append(now)
    await audit.record_auth_event(f"auth.{body.action}", email=body.email, reason=body.reason or body.action)
