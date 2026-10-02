import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback

from app.ingestion.errors import SourceConfigError, SourceError
from app.llm.errors import LLMProviderError
from app.llm.types import LLMSelection
from app.security.context import CurrentUser
from app.services import audit, llm_runtime
from app.services.observability import get_observability
from app.services.report.execution_tracking import finish_execution, start_execution
from app.services.report.pipeline import run_deterministic
from app.services.report.progress_messages import STATUS_MESSAGES
from app.services.report.request import ReportRequest
from app.services.report.templates import DEFAULT_TEMPLATE_KEY
from app.services.repositories import (
    ConversationRepository,
    ReportRepository,
)
from app.services.source_settings_service import configuration_problems

logger = logging.getLogger(__name__)

SOURCE_NOT_CONFIGURED = "source_not_configured"


def _source_not_configured_message(missing: list[str]) -> str:
    return (
        "Antes de generar informes hay que configurar la fuente de datos: falta "
        + ", ".join(missing)
        + ". Un administrador puede completarla en Fuente de Datos."
    )


def _error_code(exc: BaseException) -> str | None:
    """Classify a failure for the UI (e.g. to offer "Configurar fuente de datos")."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, LLMProviderError):
            return llm_runtime.LLM_UNAVAILABLE
        if isinstance(exc, SourceConfigError):
            return SOURCE_NOT_CONFIGURED
        if isinstance(exc, SourceError):
            return "source_error"
        exc = exc.__cause__ or exc.__context__
    return None


def _llm_audit(run) -> dict:
    summary = run.summary()
    return {k: summary[k] for k in ("requested_provider", "provider", "model", "fallback_used", "calls",
                                     "input_tokens", "output_tokens")}


class ConversationService:
    def __init__(self, graph):
        self._graph = graph
        self._conversations = ConversationRepository()
        self._reports = ReportRepository()

    async def create_conversation(self, title: str | None = None, *, user: CurrentUser | None = None) -> dict:
        return await self._conversations.create(title, created_by=user.member_id if user else None)

    async def get_conversation(self, conversation_id: str) -> dict | None:
        return await self._conversations.get(conversation_id)

    async def list_messages(self, conversation_id: str) -> list[dict]:
        return await self._conversations.list_messages(conversation_id)

    async def list_conversations(self) -> list[dict]:
        return await self._conversations.list_all()

    async def rename_conversation(self, conversation_id: str, title: str) -> dict | None:
        return await self._conversations.rename(conversation_id, title)

    async def set_pinned(self, conversation_id: str, is_pinned: bool) -> dict | None:
        return await self._conversations.set_pinned(conversation_id, is_pinned)

    async def delete_conversation(self, conversation_id: str) -> None:
        await self._reports.delete_for_conversation(conversation_id)
        await self._conversations.delete(conversation_id)
        # Also drop the LangGraph checkpoint thread so no orphaned agent state lingers.
        # setup() is required first: AsyncSqliteSaver creates its tables lazily on the
        # first *write* (a real graph run), and adelete_thread() doesn't call it itself
        # -- deleting a conversation that only ever went through the deterministic
        # form (never touched the graph) on a backend where no chat has run yet would
        # otherwise crash with "no such table: checkpoints". Found via a real end-to-end
        # test (QUALITY_OBSERVABILITY.md), not by inspection.
        await self._graph.checkpointer.setup()
        await self._graph.checkpointer.adelete_thread(conversation_id)

    async def get_report(self, report_id: str) -> dict | None:
        return await self._reports.get_report(report_id)

    async def get_latest_version(self, report_id: str) -> dict | None:
        return await self._reports.get_latest_version(report_id)

    async def get_report_card_for_conversation(self, conversation_id: str) -> dict | None:
        """Reconstructs the same {report_id, version, title, section_count, objective} shape
        the live SSE "result" event carries, so reopening a conversation (or reloading the
        page) shows the same download card instead of losing it -- a gap present since before
        this phase but explicitly in scope now ("descargar informes previamente generados")."""
        report = await self._reports.get_for_conversation(conversation_id)
        if not report:
            return None
        version = await self._reports.get_latest_version(report["id"])
        if not version:
            return None
        spec = version.get("specification") or {}
        return {
            "report_id": report["id"],
            "version": version["version"],
            "title": (spec.get("document_control") or {}).get("titulo"),
            "section_count": len(spec.get("sections", [])),
            "objective": spec.get("objective"),
            "format": version.get("format") or "docx",
        }

    async def list_recent_reports(self, limit: int = 20) -> list[dict]:
        reports = await self._reports.list_recent(limit)
        items = []
        for report in reports:
            version = await self._reports.get_latest_version(report["id"])
            if not version:
                continue
            spec = version.get("specification") or {}
            items.append(
                {
                    "report_id": report["id"],
                    "conversation_id": report["conversation_id"],
                    "company": report.get("company"),
                    "title": (spec.get("document_control") or {}).get("titulo"),
                    "version": version["version"],
                    "format": version.get("format") or "docx",
                    "section_count": len(spec.get("sections", [])),
                    "created_at": version.get("created_at") or report.get("created_at"),
                }
            )
        return items

    async def process_message(
        self,
        conversation_id: str,
        user_message: str,
        *,
        user: CurrentUser | None = None,
        llm: LLMSelection | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        await self._conversations.add_message(conversation_id, "user", user_message)

        # Which provider/model answers this turn (pre-flight checked; AUTO may fall back).
        try:
            run = await llm_runtime.start_run(llm or await llm_runtime.default_selection(user), purpose="asistente")
        except LLMProviderError as exc:
            message = llm_runtime.unavailable_message(exc)
            await self._conversations.add_message(conversation_id, "assistant", message)
            yield {"event": "result", "status": "error", "message": message, "errors": [str(exc)], "report": None,
                   "error_code": llm_runtime.LLM_UNAVAILABLE}
            return
        for llm_event in run.drain_events():
            yield llm_event

        config = {"configurable": {"thread_id": conversation_id}}
        graph_input = {"conversation_id": conversation_id, "user_request": user_message}

        started_at = time.monotonic()
        execution_id: str | None = None
        try:
            execution_id = await start_execution(
                conversation_id=conversation_id,
                company_id=None,
                mode="conversational",
                request=None,
                triggered_by=user.member_id if user else None,
                llm=run.summary(),
            )
        except Exception:  # noqa: BLE001 - audit trail is best-effort, never blocks a chat turn
            logger.warning("Could not start execution tracking for %s", conversation_id, exc_info=True)

        usage_cb_ctx = get_usage_metadata_callback()
        usage_cb = usage_cb_ctx.__enter__()
        try:
            # astream_events fires as each node STARTS, not only once it finishes -- with
            # stream_mode="updates" the UI would show the *previous* node's label for the
            # entire duration of a slow step (e.g. still "Entendiendo la solicitud..." during
            # the ~90s report-generation call), looking hung even though it's progressing.
            async for event in self._graph.astream_events(graph_input, config=config, version="v2"):
                if event["event"] == "on_chain_start" and event["name"] in STATUS_MESSAGES:
                    node_name = event["name"]
                    yield {
                        "event": "progress",
                        "node": node_name,
                        "message": STATUS_MESSAGES.get(node_name, node_name),
                    }
                for llm_event in run.drain_events():  # a provider switch mid-run
                    yield llm_event
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as a chat error, not swallowed
            usage_cb_ctx.__exit__(None, None, None)
            for llm_event in run.drain_events():
                yield llm_event
            error_code = _error_code(exc)
            if error_code == SOURCE_NOT_CONFIGURED:
                message = _source_not_configured_message(await configuration_problems() or ["la configuración"])
            elif error_code == llm_runtime.LLM_UNAVAILABLE:
                message = f"El proveedor de IA no pudo responder: {exc}"
            else:
                message = f"Tuve un problema al procesar tu solicitud: {exc}"
            await self._conversations.add_message(conversation_id, "assistant", message)
            duration_ms = int((time.monotonic() - started_at) * 1000)
            await self._safe_finish_execution(
                execution_id,
                status="error",
                errors=[str(exc)],
                duration_ms=duration_ms,
                usage_metadata=usage_cb.usage_metadata,
                llm=run.summary(),
            )
            await self._observe_run("conversational", "error", duration_ms, conversation_id, detail=str(exc))
            llm_runtime.end_run()
            yield {
                "event": "result",
                "status": "error",
                "message": message,
                "errors": [str(exc)],
                "report": None,
                "error_code": error_code,
                "llm": run.info(),
            }
            return
        else:
            usage_cb_ctx.__exit__(None, None, None)

        final_state = (await self._graph.aget_state(config)).values

        assistant_message = final_state.get("assistant_message") or "Listo."
        await self._conversations.add_message(conversation_id, "assistant", assistant_message)

        result: dict[str, Any] = {
            "event": "result",
            "status": final_state.get("status"),
            "message": assistant_message,
            "errors": final_state.get("errors") or [],
            "report": None,
            "llm": run.info(),
        }

        report_id = None
        report_version_id = None
        if final_state.get("status") == "ready" and final_state.get("report_file_path"):
            report = await self._reports.get_or_create_for_conversation(
                conversation_id, final_state.get("company"), final_state.get("company_id")
            )
            report_format = final_state.get("format") or "docx"
            version = await self._reports.add_version(
                report_id=report["id"],
                file_path=final_state["report_file_path"],
                specification=final_state.get("report_specification") or {},
                change_summary=user_message,
                format=report_format,
            )
            report_id, report_version_id = report["id"], version["id"]
            spec = final_state.get("report_specification") or {}
            result["report"] = {
                "report_id": report["id"],
                "version": version["version"],
                "title": (spec.get("document_control") or {}).get("titulo"),
                "section_count": len(spec.get("sections", [])),
                "objective": spec.get("objective"),
                "format": report_format,
            }

        # in_agent_executions.status only tracks running/ready/awaiting_user_input/error --
        # "answered" (answer_question's terminal state) counts as a successful completion
        # for audit purposes, it just didn't produce a new document.
        tracked_status = final_state.get("status") or "error"
        if tracked_status not in {"running", "ready", "awaiting_user_input", "error"}:
            tracked_status = "ready"

        duration_ms = int((time.monotonic() - started_at) * 1000)
        await self._safe_finish_execution(
            execution_id,
            status=tracked_status,
            company_id=final_state.get("company_id"),
            report_id=report_id,
            report_version_id=report_version_id,
            errors=final_state.get("errors") or [],
            duration_ms=duration_ms,
            usage_metadata=usage_cb.usage_metadata,
            llm=run.summary(),
        )
        await self._observe_run(
            "conversational", tracked_status, duration_ms, conversation_id,
            detail="; ".join(final_state.get("errors") or [])[:300],
        )
        if report_id:
            await audit.record(
                "report.generated",
                module="asistente",
                resource_type="report",
                resource_id=report_id,
                context={"version": result["report"]["version"], "company": final_state.get("company"),
                         "format": result["report"]["format"], "conversation_id": conversation_id,
                         "duration_ms": duration_ms, "llm": _llm_audit(run)},
            )

        for llm_event in run.drain_events():
            yield llm_event
        llm_runtime.end_run()
        yield result

    async def generate_report_deterministic(
        self, request: ReportRequest, *, user: CurrentUser | None = None, llm: LLMSelection | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Modalidad 1 (formulario) entry point -- creates its own conversation as the
        persistence anchor (reused as-is: same in_reports/in_report_versions tables, same
        download endpoint, and the conversation list IS the "historial de informes" for this
        modality, see DETERMINISTIC_FLOW.md). No LLM decides anything about *whether* to run
        each step -- pipeline.run_deterministic always runs the same fixed sequence, which is
        what makes the same input reproducible.
        """
        # Never start a source query that cannot succeed: no conversation, no execution,
        # no request -- just tell the user what to configure, and where.
        missing = await configuration_problems()
        if missing:
            message = _source_not_configured_message(missing)
            await get_observability().emit(
                "WARNING", "report", "report.blocked_source_not_configured", message, context={"missing": missing}
            )
            await audit.record(
                "report.generation_blocked",
                module="informes",
                result="failure",
                context={"reason": SOURCE_NOT_CONFIGURED, "missing": missing, "company": request.company},
            )
            yield {
                "event": "result",
                "status": "error",
                "message": message,
                "errors": [message],
                "report": None,
                "error_code": SOURCE_NOT_CONFIGURED,
            }
            return

        # Same rule for the LLM: check the chosen provider before starting anything.
        try:
            run = await llm_runtime.start_run(llm or await llm_runtime.default_selection(user), purpose="informe")
        except LLMProviderError as exc:
            message = llm_runtime.unavailable_message(exc)
            await audit.record(
                "report.generation_blocked",
                module="informes",
                result="failure",
                context={"reason": llm_runtime.LLM_UNAVAILABLE, "status": exc.status.value, "company": request.company,
                         "requested_provider": (llm.provider if llm else None)},
            )
            yield {"event": "result", "status": "error", "message": message, "errors": [str(exc)], "report": None,
                   "error_code": llm_runtime.LLM_UNAVAILABLE}
            return
        for llm_event in run.drain_events():
            yield llm_event

        title = f"Informe — {request.company or request.company_id} — {request.start_date} a {request.end_date}"
        conversation = await self._conversations.create(title, created_by=user.member_id if user else None)
        conversation_id = conversation["id"]

        summary = (
            f"[Formulario] Empresa: {request.company or request.company_id} | "
            f"Período: {request.start_date} a {request.end_date} | "
            f"Tipo: {request.report_type or DEFAULT_TEMPLATE_KEY}"
        )
        if request.focus_categories:
            summary += f" | Categorías: {', '.join(request.focus_categories)}"
        if request.risk_level_filter:
            summary += f" | Riesgo: {', '.join(request.risk_level_filter)}"
        await self._conversations.add_message(conversation_id, "user", summary)

        started_at = time.monotonic()
        execution_id: str | None = None
        try:
            execution_id = await start_execution(
                conversation_id=conversation_id,
                company_id=request.company_id,
                mode="deterministic",
                request=request,
                triggered_by=user.member_id if user else None,
                llm=run.summary(),
            )
        except Exception:  # noqa: BLE001 - audit trail is best-effort, never blocks generation
            logger.warning("Could not start execution tracking for %s", conversation_id, exc_info=True)

        yield {"event": "progress", "node": "conversation_created", "conversation_id": conversation_id, "message": "Solicitud validada..."}

        final: dict[str, Any] = {}
        error_code: str | None = None
        with get_usage_metadata_callback() as usage_cb:
            try:
                async for event in run_deterministic(request, conversation_id=conversation_id):
                    if event["event"] == "progress":
                        yield event
                    else:
                        final = event
                    for llm_event in run.drain_events():  # a provider switch mid-run
                        yield llm_event
            except Exception as exc:  # noqa: BLE001 - an unexpected failure here (e.g. PDF conversion
                # crashing outside the errors pipeline.py already anticipates) must still end the
                # stream cleanly, not leave the request hanging or surface a raw 500 mid-SSE.
                final = {"status": "error", "errors": [str(exc)], "company": None}
                error_code = _error_code(exc)
            usage_metadata = dict(usage_cb.usage_metadata)

        duration_ms = int((time.monotonic() - started_at) * 1000)

        if final.get("status") != "ready":
            errors = final.get("errors") or ["Error desconocido al generar el informe."]
            message = "No se pudo generar el informe:\n" + "\n".join(f"- {e}" for e in errors)
            await self._conversations.add_message(conversation_id, "assistant", message)
            await self._safe_finish_execution(
                execution_id,
                status="error",
                company_id=request.company_id,
                errors=errors,
                duration_ms=duration_ms,
                usage_metadata=usage_metadata,
                llm=run.summary(),
            )
            await self._observe_run("deterministic", "error", duration_ms, conversation_id, detail="; ".join(errors)[:300])
            await audit.record(
                "report.generation_failed",
                module="informes",
                result="error",
                resource_type="conversation",
                resource_id=conversation_id,
                context={"company": request.company, "period": f"{request.start_date} a {request.end_date}",
                         "errors": errors[:5], "error_code": error_code, "llm": _llm_audit(run)},
            )
            for llm_event in run.drain_events():
                yield llm_event
            llm_runtime.end_run()
            yield {
                "event": "result",
                "status": "error",
                "message": message,
                "errors": errors,
                "report": None,
                "conversation_id": conversation_id,
                "error_code": error_code,
                "llm": run.info(),
            }
            return

        company = final["company"]
        spec = final["specification"]
        report = await self._reports.get_or_create_for_conversation(conversation_id, company.name, company.id)
        version = await self._reports.add_version(
            report_id=report["id"],
            file_path=str(final["document_path"]),
            specification=spec.model_dump(),
            change_summary="Generado desde formulario",
            template_id=None,
            format=request.format,
        )

        assistant_message = (
            f"Tu informe de gestión de {company.name} ({request.start_date} a {request.end_date}) "
            f"está listo — {len(spec.sections)} secciones."
        )
        await self._conversations.add_message(conversation_id, "assistant", assistant_message)

        await self._safe_finish_execution(
            execution_id,
            status="ready",
            company_id=company.id,
            report_id=report["id"],
            report_version_id=version["id"],
            duration_ms=duration_ms,
            usage_metadata=usage_metadata,
            llm=run.summary(),
        )
        await self._observe_run("deterministic", "ready", duration_ms, conversation_id)
        await audit.record(
            "report.generated",
            module="informes",
            resource_type="report",
            resource_id=report["id"],
            context={"version": version["version"], "company": company.name, "format": request.format,
                     "period": f"{request.start_date} a {request.end_date}", "report_type": request.report_type,
                     "conversation_id": conversation_id, "duration_ms": duration_ms, "llm": _llm_audit(run)},
        )
        for llm_event in run.drain_events():
            yield llm_event
        llm_runtime.end_run()

        yield {
            "event": "result",
            "status": "ready",
            "message": assistant_message,
            "errors": [],
            "conversation_id": conversation_id,
            "report": {
                "report_id": report["id"],
                "version": version["version"],
                "title": spec.document_control.titulo,
                "section_count": len(spec.sections),
                "objective": spec.objective,
                "format": request.format,
            },
            "llm": run.info(),
        }

    async def _observe_run(
        self, mode: str, status: str, duration_ms: int, conversation_id: str, *, detail: str = ""
    ) -> None:
        label = "Informe por formulario" if mode == "deterministic" else "Ejecución del asistente"
        failed = status == "error"
        await get_observability().emit(
            "ERROR" if failed else "INFO",
            "agent" if mode == "conversational" else "report",
            f"{'agent.run' if mode == 'conversational' else 'report.generation'}.{'failed' if failed else 'completed'}",
            f"{label}: {status}" + (f" -- {detail}" if detail else ""),
            status=status,
            duration_ms=duration_ms,
            context={"mode": mode, "conversation_id": conversation_id},
        )

    async def _safe_finish_execution(self, execution_id: str | None, **kwargs) -> None:
        if not execution_id:
            return
        try:
            await finish_execution(execution_id, **kwargs)
        except Exception:  # noqa: BLE001 - audit trail is best-effort, never blocks a chat turn
            logger.warning("Could not finish execution tracking for %s", execution_id, exc_info=True)
