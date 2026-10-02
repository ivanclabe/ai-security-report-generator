"""Observabilidad (admins only): health of the app and its dependencies.

Combines the persisted operational events (in_ops_events), the agent execution
trail (in_agent_executions) and the in-memory request buffer of this process.
Nothing here returns secrets: events are redacted when written.
"""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.auth import require_admin
from app.security.context import CurrentUser
from app.services import source_settings_service as sss
from app.services import supabase_rest as db
from app.services.observability import CATEGORIES, get_observability
from app.services.system_version import get_system_version

router = APIRouter(prefix="/api/observability", tags=["observability"])

_SAFE_TEXT = re.compile(r"[^\w\s.@:\-]", re.UNICODE)


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@router.get("/summary")
async def summary(_: CurrentUser = Depends(require_admin)):
    obs = get_observability()
    since = _since(24)

    events, _ = await db.query(
        "in_ops_events",
        [("select", "level,category,event,message,occurred_at,status"), ("occurred_at", f"gte.{since}"),
         ("order", "occurred_at.desc"), ("limit", "2000")],
    )
    by_level = Counter(e["level"] for e in events)
    by_category = Counter(e["category"] for e in events)
    source_events = [e for e in events if e["category"] == "source"]
    last_source = source_events[0] if source_events else None
    last_source_error = next((e for e in source_events if e["level"] == "ERROR"), None)

    executions, _ = await db.query(
        "in_agent_executions",
        [("select", "status,mode,duration_ms,started_at"), ("started_at", f"gte.{since}"), ("limit", "2000")],
    )
    durations = [e["duration_ms"] for e in executions if e.get("duration_ms") is not None]
    exec_status = Counter(e["status"] for e in executions)

    status = await sss.current_settings()
    config = sss.to_source_config(status)
    missing = await sss.configuration_problems()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "process": {"started_at": obs.started_at, "uptime_seconds": obs.uptime_seconds, "version": get_system_version()},
        "requests_last_hour": obs.request_stats(3600),
        "events_24h": {"total": len(events), "by_level": dict(by_level), "by_category": dict(by_category)},
        "source": {
            "configured": not missing,
            "missing": missing,
            "host": config.host or None,
            "uses_https": config.uses_https,
            "last_event": last_source,
            "last_error": last_source_error,
        },
        "agent_24h": {
            "total": len(executions),
            "by_status": dict(exec_status),
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "max_duration_ms": max(durations) if durations else None,
        },
        "reports_24h": exec_status.get("ready", 0),
    }


@router.get("/events")
async def events(
    level: Literal["INFO", "WARNING", "ERROR"] | None = None,
    category: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=120),
    hours: int = Query(default=24, ge=1, le=24 * 90),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_admin),
):
    params: list[tuple[str, str]] = [("occurred_at", f"gte.{_since(hours)}")]
    if level:
        params.append(("level", f"eq.{level}"))
    if category in CATEGORIES:
        params.append(("category", f"eq.{category}"))
    text = _SAFE_TEXT.sub(" ", q or "").strip()[:80]
    if text:
        pattern = "*" + "*".join(text.split()) + "*"
        params.append(("or", f"(event.ilike.{pattern},message.ilike.{pattern})"))
    params += [("order", "occurred_at.desc"), ("limit", str(limit)), ("offset", str(offset))]
    rows, total = await db.query("in_ops_events", params, count=True)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/requests")
async def requests(limit: int = Query(default=100, ge=1, le=1000), _: CurrentUser = Depends(require_admin)):
    obs = get_observability()
    return {"items": obs.recent_requests(limit), "stats": obs.request_stats(3600)}


@router.get("/executions")
async def executions(limit: int = Query(default=50, ge=1, le=200), _: CurrentUser = Depends(require_admin)):
    rows, _ = await db.query(
        "in_agent_executions",
        [
            ("select", "id,mode,status,company_id,model,duration_ms,started_at,completed_at,error_messages,estimated_cost_usd"),
            ("order", "started_at.desc"),
            ("limit", str(limit)),
        ],
    )
    for row in rows:
        row["error_count"] = len(row.pop("error_messages", None) or [])
    return {"items": rows}
