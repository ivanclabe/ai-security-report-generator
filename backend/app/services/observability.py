"""Observability: operational events and request metrics, without secrets.

Two stores, by design:
* in_ops_events (Supabase) -- significant events that must survive restarts
  and be queryable: source connections, agent runs, report generation,
  configuration changes, errors. Written as the signed-in user (RLS).
* an in-memory ring buffer -- every HTTP request (method, route, status,
  duration) and every event, for the live "Solicitudes" view. Process-local and
  bounded: cheap enough to record everything, gone on restart.

Every event is also written to the Python log at the matching level (INFO,
WARNING, ERROR), so the server log tells the same story.
"""
import logging
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.security.context import get_current_user, get_request_meta
from app.security.redaction import redact, redact_text
from app.services import supabase_rest as db

logger = logging.getLogger("app.ops")

LEVELS = {"INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}
CATEGORIES = ("request", "auth", "source", "agent", "report", "config", "system")

_ID_SEGMENT = re.compile(
    r"^(?:[a-z]+-[0-9a-f]{12}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+)$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def route_template(path: str) -> str:
    """'/api/conversations/conv-1a2b3c4d5e6f/messages' -> '/api/conversations/{id}/messages'."""
    return "/".join("{id}" if _ID_SEGMENT.match(part) else part for part in path.split("/"))


@dataclass
class OpsEvent:
    level: str
    category: str
    event: str
    message: str
    occurred_at: str = field(default_factory=_now)
    status: str | None = None
    duration_ms: int | None = None
    operation_id: str | None = None
    actor_email: str | None = None
    context: dict = field(default_factory=dict)


@dataclass
class RequestRecord:
    occurred_at: str
    method: str
    route: str
    status: int
    duration_ms: int
    request_id: str | None
    actor_email: str | None


class Observability:
    def __init__(self, max_events: int = 500, max_requests: int = 1000):
        self._events: deque[OpsEvent] = deque(maxlen=max_events)
        self._requests: deque[RequestRecord] = deque(maxlen=max_requests)
        self.started_at = _now()
        self._started_monotonic = time.monotonic()

    @property
    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self._started_monotonic)

    async def emit(
        self,
        level: str,
        category: str,
        event: str,
        message: str,
        *,
        status: str | None = None,
        duration_ms: int | None = None,
        operation_id: str | None = None,
        context: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> OpsEvent:
        level = level if level in LEVELS else "INFO"
        category = category if category in CATEGORIES else "system"
        user = get_current_user()
        meta = get_request_meta()
        record = OpsEvent(
            level=level,
            category=category,
            event=event[:100],
            message=redact_text(message, 2000),
            status=status,
            duration_ms=duration_ms,
            operation_id=operation_id or meta.request_id,
            actor_email=user.email if user else None,
            context=redact(context or {}),
        )
        self._events.append(record)
        logger.log(
            LEVELS[level],
            "[%s] %s: %s%s",
            category,
            event,
            record.message,
            f" ({duration_ms} ms)" if duration_ms is not None else "",
        )
        if persist and user is not None:
            try:
                await db.insert_quiet(
                    "in_ops_events",
                    {
                        "level": record.level,
                        "category": record.category,
                        "event": record.event,
                        "message": record.message,
                        "status": record.status,
                        "duration_ms": record.duration_ms,
                        "operation_id": record.operation_id,
                        "actor_auth_id": user.auth_id,
                        "context": record.context,
                    },
                )
            except Exception:  # noqa: BLE001 - observability must never break the observed operation
                logger.warning("No se pudo persistir el evento operativo %s", event, exc_info=True)
        return record

    def record_request(self, method: str, path: str, status: int, duration_ms: int) -> RequestRecord:
        user = get_current_user()
        record = RequestRecord(
            occurred_at=_now(),
            method=method,
            route=route_template(path),
            status=status,
            duration_ms=duration_ms,
            request_id=get_request_meta().request_id,
            actor_email=user.email if user else None,
        )
        self._requests.append(record)
        return record

    def recent_events(self, limit: int = 200) -> list[dict]:
        return [asdict(e) for e in list(self._events)[-limit:]][::-1]

    def recent_requests(self, limit: int = 200) -> list[dict]:
        return [asdict(r) for r in list(self._requests)[-limit:]][::-1]

    def request_stats(self, since_seconds: int = 3600) -> dict:
        cutoff = datetime.now(timezone.utc).timestamp() - since_seconds
        window = [r for r in self._requests if datetime.fromisoformat(r.occurred_at).timestamp() >= cutoff]
        durations = sorted(r.duration_ms for r in window)
        errors = sum(1 for r in window if r.status >= 500)
        auth_failures = sum(1 for r in window if r.status in (401, 403))
        p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None
        return {
            "window_seconds": since_seconds,
            "total": len(window),
            "server_errors": errors,
            "auth_failures": auth_failures,
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "p95_duration_ms": p95,
        }

    def clear(self) -> None:
        self._events.clear()
        self._requests.clear()


_observability = Observability()


def get_observability() -> Observability:
    return _observability
