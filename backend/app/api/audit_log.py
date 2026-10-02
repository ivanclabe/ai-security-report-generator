"""Auditoría: query the audit log (admins only), with filters and CSV export.

Filters are validated and turned into PostgREST operators here -- free text
is reduced to a safe character set before it reaches an `or=(...)` filter.
"""
import csv
import io
import json
import re
from datetime import date, datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import require_admin
from app.security.context import CurrentUser
from app.services import audit
from app.services import supabase_rest as db

router = APIRouter(prefix="/api/audit", tags=["audit"])

_SAFE_TEXT = re.compile(r"[^\w\s.@:\-]", re.UNICODE)
_IDENTIFIER = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")

MODULES = ["auth", "fuente_de_datos", "informes", "asistente", "configuracion", "auditoria"]


class AuditEntry(BaseModel):
    id: str
    occurred_at: str
    actor_email: str | None = None
    action: str
    module: str
    result: str
    operation_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    context: dict = {}
    ip: str | None = None
    user_agent: str | None = None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int | None
    limit: int
    offset: int
    modules: list[str] = MODULES


def _filters(
    q: str | None,
    module: str | None,
    action: str | None,
    result: str | None,
    date_from: date | None,
    date_to: date | None,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    if module and _IDENTIFIER.match(module):
        params.append(("module", f"eq.{module}"))
    if action and _IDENTIFIER.match(action):
        # "source" matches every source.* action, "source.settings_updated" only itself
        params.append(("action", f"like.{action}*" if "." not in action else f"eq.{action}"))
    if result:
        params.append(("result", f"eq.{result}"))
    if date_from:
        params.append(("occurred_at", f"gte.{datetime.combine(date_from, time.min, timezone.utc).isoformat()}"))
    if date_to:
        params.append(("occurred_at", f"lte.{datetime.combine(date_to, time.max, timezone.utc).isoformat()}"))
    text = _SAFE_TEXT.sub(" ", q or "").strip()[:80]
    if text:
        pattern = "*" + "*".join(text.split()) + "*"
        params.append(
            ("or", f"(action.ilike.{pattern},actor_email.ilike.{pattern},resource_id.ilike.{pattern},module.ilike.{pattern})")
        )
    return params


ResultFilter = Literal["success", "failure", "denied", "error"]


@router.get("", response_model=AuditPage)
async def list_audit(
    q: str | None = Query(default=None, max_length=120),
    module: str | None = Query(default=None, max_length=40),
    action: str | None = Query(default=None, max_length=80),
    result: ResultFilter | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
    _: CurrentUser = Depends(require_admin),
):
    params = _filters(q, module, action, result, date_from, date_to)
    params += [("order", "occurred_at.desc"), ("limit", str(limit)), ("offset", str(offset))]
    rows, total = await db.query("in_audit_log", params, count=True)
    return AuditPage(items=[AuditEntry(**{**r, "id": str(r["id"])}) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/export.csv")
async def export_audit(
    q: str | None = Query(default=None, max_length=120),
    module: str | None = Query(default=None, max_length=40),
    action: str | None = Query(default=None, max_length=80),
    result: ResultFilter | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _: CurrentUser = Depends(require_admin),
):
    params = _filters(q, module, action, result, date_from, date_to)
    params += [("order", "occurred_at.desc"), ("limit", "5000")]
    rows, _total = await db.query("in_audit_log", params)
    await audit.record(
        "audit.exported",
        module="auditoria",
        context={"rows": len(rows), "filters": {"q": q, "module": module, "action": action, "result": result,
                                                 "from": str(date_from or ""), "to": str(date_to or "")}},
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = ["occurred_at", "actor_email", "action", "module", "result", "operation_id",
               "resource_type", "resource_id", "ip", "context"]
    writer.writerow(columns)
    for row in rows:
        writer.writerow([json.dumps(row.get(c), ensure_ascii=False) if c == "context" else row.get(c) for c in columns])
    filename = f"auditoria-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        iter(["﻿" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
