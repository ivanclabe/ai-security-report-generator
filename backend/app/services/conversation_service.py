import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback

from app.services.repositories import ConversationRepository, ReportRepository, UserRepository
from app.services.report.execution_tracking import finish_execution, start_execution
from app.services.report.pipeline import run_deterministic
from app.services.report.progress_messages import STATUS_MESSAGES
from app.services.report.request import ReportRequest
from app.services.report.templates import DEFAULT_TEMPLATE_KEY

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, graph):
        self._graph = graph
        self._conversations = ConversationRepository()
        self._reports = ReportRepository()
        self._users = UserRepository()

    async def _resolve_user_id(self, username: str | None) -> str | None:
        if not username:
            return None
        try:
            user = await self._users.get_by_username(username)
        except Exception:  # noqa: BLE001 - attribution is best-effort, never blocks the request
            logger.warning("Could not resolve user '%s' for execution attribution", username, exc_info=True)
            return None
        return user["id"] if user else None

    async def create_conversation(self, title: str | None = None) -> dict:
        return await self._conversations.create(title)

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

    async def process_message(
        self, conversation_id: str, user_message: str, *, username: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        await self._conversations.add_message(conversation_id, "user", user_message)

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
                triggered_by=await self._resolve_user_id(username),
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
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as a chat error, not swallowed
            usage_cb_ctx.__exit__(None, None, None)
            message = f"Tuve un problema al procesar tu solicitud: {exc}"
            await self._conversations.add_message(conversation_id, "assistant", message)
            await self._safe_finish_execution(
                execution_id,
                status="error",
                errors=[str(exc)],
                duration_ms=int((time.monotonic() - started_at) * 1000),
                usage_metadata=usage_cb.usage_metadata,
            )
            yield {"event": "result", "status": "error", "message": message, "errors": [str(exc)], "report": None}
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

        await self._safe_finish_execution(
            execution_id,
            status=tracked_status,
            company_id=final_state.get("company_id"),
            report_id=report_id,
            report_version_id=report_version_id,
            errors=final_state.get("errors") or [],
            duration_ms=int((time.monotonic() - started_at) * 1000),
            usage_metadata=usage_cb.usage_metadata,
        )

        yield result

    async def generate_report_deterministic(
        self, request: ReportRequest, *, username: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Modalidad 1 (formulario) entry point -- creates its own conversation as the
        persistence anchor (reused as-is: same in_reports/in_report_versions tables, same
        download endpoint, and the conversation list IS the "historial de informes" for this
        modality, see DETERMINISTIC_FLOW.md). No LLM decides anything about *whether* to run
        each step -- pipeline.run_deterministic always runs the same fixed sequence, which is
        what makes the same input reproducible.
        """
        title = f"Informe — {request.company or request.company_id} — {request.start_date} a {request.end_date}"
        conversation = await self._conversations.create(title)
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
                triggered_by=await self._resolve_user_id(username),
            )
        except Exception:  # noqa: BLE001 - audit trail is best-effort, never blocks generation
            logger.warning("Could not start execution tracking for %s", conversation_id, exc_info=True)

        yield {"event": "progress", "node": "conversation_created", "conversation_id": conversation_id, "message": "Solicitud validada..."}

        final: dict[str, Any] = {}
        with get_usage_metadata_callback() as usage_cb:
            try:
                async for event in run_deterministic(request, conversation_id=conversation_id):
                    if event["event"] == "progress":
                        yield event
                    else:
                        final = event
            except Exception as exc:  # noqa: BLE001 - an unexpected failure here (e.g. PDF conversion
                # crashing outside the errors pipeline.py already anticipates) must still end the
                # stream cleanly, not leave the request hanging or surface a raw 500 mid-SSE.
                final = {"status": "error", "errors": [str(exc)], "company": None}
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
            )
            yield {
                "event": "result",
                "status": "error",
                "message": message,
                "errors": errors,
                "report": None,
                "conversation_id": conversation_id,
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
        )

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
        }

    async def _safe_finish_execution(self, execution_id: str | None, **kwargs) -> None:
        if not execution_id:
            return
        try:
            await finish_execution(execution_id, **kwargs)
        except Exception:  # noqa: BLE001 - audit trail is best-effort, never blocks a chat turn
            logger.warning("Could not finish execution tracking for %s", execution_id, exc_info=True)
