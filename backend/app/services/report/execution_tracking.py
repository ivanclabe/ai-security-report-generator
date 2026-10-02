"""ExecutionTrackingService -- records one row per pipeline run (conversational
or deterministic) in in_agent_executions, closing the audit gap identified in
ARCHITECTURE_ASSESSMENT.md (§9: no record of what data/model/params/tokens/cost
produced a given report, or which user triggered it). Best-effort: a Supabase
outage here must never break a chat turn or a report generation -- callers
catch and log, matching ingestion_service.py's approach.
"""
from app.config.settings import get_settings
from app.services import supabase_rest as db
from app.services.db import new_id, now_iso
from app.services.report.cost_estimation import estimate_cost_usd
from app.services.report.request import ReportRequest
from app.services.system_version import get_system_version


async def start_execution(
    *,
    conversation_id: str | None,
    company_id: str | None,
    mode: str,
    request: ReportRequest | None,
    triggered_by: str | None = None,
    llm: dict | None = None,
) -> str:
    execution_id = new_id("exec")
    await db.insert(
        "in_agent_executions",
        {
            "id": execution_id,
            "conversation_id": conversation_id,
            "report_id": None,
            "report_version_id": None,
            "company_id": company_id,
            "mode": mode,
            "triggered_by": triggered_by,
            "request_params": request.model_dump(mode="json") if request else {},
            "data_import_ids": [],
            "model": (llm or {}).get("model") or get_settings().llm_model,
            "llm_provider": (llm or {}).get("provider"),
            "status": "running",
            "error_messages": [],
            "usage_metadata": {},
            "estimated_cost_usd": None,
            "system_version": get_system_version(),
            "started_at": now_iso(),
        },
    )
    return execution_id


async def finish_execution(
    execution_id: str,
    *,
    status: str,
    company_id: str | None = None,
    report_id: str | None = None,
    report_version_id: str | None = None,
    errors: list[str] | None = None,
    duration_ms: int | None = None,
    usage_metadata: dict | None = None,
    llm: dict | None = None,
) -> None:
    update: dict = {
        "status": status,
        "report_id": report_id,
        "report_version_id": report_version_id,
        "error_messages": errors or [],
        "completed_at": now_iso(),
    }
    if company_id:
        update["company_id"] = company_id
    if llm:
        # the provider/model that actually answered (it can differ from the start after an AUTO fallback)
        update["model"] = llm.get("model")
        update["llm_provider"] = llm.get("provider")
        update["fallback_used"] = bool(llm.get("fallback_used"))
        last = (llm.get("fallbacks") or [None])[-1]
        update["fallback_reason"] = last.get("reason") if last else None
        update["llm_metrics"] = {k: llm.get(k) for k in ("requested_provider", "calls", "failed_calls", "latency_ms",
                                                          "input_tokens", "output_tokens", "fallbacks")}
    if duration_ms is not None:
        update["duration_ms"] = duration_ms
    if usage_metadata:
        update["usage_metadata"] = usage_metadata
        update["estimated_cost_usd"] = estimate_cost_usd(usage_metadata)
    await db.update("in_agent_executions", {"id": execution_id}, update)
