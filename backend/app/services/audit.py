"""Audit log: who did what, when, with which result -- persisted in Supabase
(in_audit_log, append-only, admins read).

Kept separate from observability on purpose: audit answers "which user did
this action?" for accountability; observability answers "is the system
healthy?" for diagnosis. An action can produce both (a failed source
connection test is an audit event of the admin who ran it *and* an ops event).

Rules enforced here, whatever the call site passes:
* the actor is always the authenticated user from the request context;
* `context` goes through redaction (no passwords, tokens, secrets);
* writing never breaks the operation being audited -- a failure is logged.
"""
import logging
from typing import Any

from app.security.context import CurrentUser, get_current_user, get_request_meta
from app.security.redaction import redact, redact_text
from app.services import supabase_rest as db

logger = logging.getLogger("app.audit")

RESULTS = ("success", "failure", "denied", "error")


async def record(
    action: str,
    *,
    module: str,
    result: str = "success",
    resource_type: str | None = None,
    resource_id: str | None = None,
    context: dict[str, Any] | None = None,
    operation_id: str | None = None,
    user: CurrentUser | None = None,
) -> None:
    if result not in RESULTS:
        result = "error"
    actor = user or get_current_user()
    meta = get_request_meta()
    safe_context = redact(context or {})
    logger.info(
        "AUDIT action=%s module=%s result=%s actor=%s resource=%s:%s op=%s",
        action,
        module,
        result,
        actor.email if actor else "-",
        resource_type or "-",
        resource_id or "-",
        operation_id or meta.request_id or "-",
    )
    if actor is None:
        return  # no member identity to write under (RLS): the log line above is the record
    row = {
        "actor_auth_id": actor.auth_id,
        "actor_member_id": actor.member_id,
        "actor_email": actor.email,
        "action": action,
        "module": module,
        "result": result,
        "operation_id": operation_id or meta.request_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "context": safe_context,
        "ip": meta.ip,
        "user_agent": redact_text(meta.user_agent or "", 300) or None,
    }
    try:
        await db.insert_quiet("in_audit_log", row)
    except Exception:  # noqa: BLE001 - auditing must never break the audited operation
        logger.warning("No se pudo persistir el evento de auditoría %s", action, exc_info=True)


async def record_auth_event(action: str, *, email: str | None, reason: str) -> None:
    """Authentication events that happen without a member session (failed login, access
    denied to a non-member): written through the narrow public RPC in_log_auth_event."""
    meta = get_request_meta()
    logger.warning("AUDIT action=%s module=auth email=%s reason=%s", action, email or "-", reason)
    try:
        await db.rpc(
            "in_log_auth_event",
            {
                "p_action": action,
                "p_email": email,
                "p_reason": redact_text(reason, 200),
                "p_ip": meta.ip,
                "p_user_agent": redact_text(meta.user_agent or "", 300) or None,
            },
            as_anon=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo persistir el evento de autenticación %s", action, exc_info=True)
