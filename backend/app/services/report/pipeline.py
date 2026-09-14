"""run_deterministic -- the Modalidad 1 (form-driven) entry point into the
same report-generation core the conversational agent uses (DETERMINISTIC_FLOW.md
/ AGENT_ARCHITECTURE.md). Deliberately bypasses LangGraph entirely: there is no
conversation memory to manage and no LLM decision about *which* step to run
next -- every step always runs, in the same fixed order, which is exactly what
"reproducible" means here. It calls the identical collection/analysis/
specification/validation/document services the graph's nodes call.

An async generator so the API layer can stream the same
{"event": "progress"/"result", ...} shape conversation_service.py already
emits for chat -- one frontend rendering path for both modalities.
"""
from collections.abc import AsyncIterator
from typing import Any

from app.services.report.analysis import analyze
from app.services.report.collection import CompanyNotFoundError, collect
from app.services.report.document import (
    SUPPORTED_FORMATS,
    DocumentGenerationError,
    render,
)
from app.services.report.progress_messages import STATUS_MESSAGES
from app.services.report.request import ReportRequest
from app.services.report.specification import build_specification
from app.services.report.validation import validate


def validate_request(request: ReportRequest) -> list[str]:
    """Stage 1, "validar parámetros" -- checks that don't need any I/O.
    Field presence/type is already enforced by ReportRequest (Pydantic);
    this only covers the business-level checks that aren't shape validation."""
    errors: list[str] = []
    if not request.company and not request.company_id:
        errors.append("Debes indicar una empresa (nombre o company_id).")
    try:
        from datetime import date

        start = date.fromisoformat(request.start_date)
        end = date.fromisoformat(request.end_date)
        if start > end:
            errors.append("La fecha inicial debe ser anterior o igual a la fecha final.")
    except ValueError:
        errors.append("start_date/end_date deben ser fechas ISO válidas (YYYY-MM-DD).")
    if request.report_type is not None:
        from app.services.report.templates import get_template

        try:
            get_template(request.report_type)
        except ValueError as exc:
            errors.append(str(exc))
    if request.format not in SUPPORTED_FORMATS:
        errors.append(f"Formato '{request.format}' no soportado -- usa uno de: {', '.join(SUPPORTED_FORMATS)}.")
    return errors


async def run_deterministic(request: ReportRequest, *, conversation_id: str) -> AsyncIterator[dict[str, Any]]:
    param_errors = validate_request(request)
    if param_errors:
        yield {"event": "result", "status": "error", "errors": param_errors, "company": None}
        return

    yield {"event": "progress", "node": "collect_data", "message": STATUS_MESSAGES["collect_data"]}
    try:
        collection_result = await collect(request)
    except CompanyNotFoundError as exc:
        yield {"event": "result", "status": "error", "errors": [str(exc)], "company": None}
        return

    yield {"event": "progress", "node": "analyze_data", "message": STATUS_MESSAGES["analyze_data"]}
    # Computed for parity with the conversational flow (same services, same steps) -- not yet
    # consumed by build_specification in either flow, see AGENT_ARCHITECTURE.md §6.
    analysis = analyze(collection_result.data)

    yield {
        "event": "progress",
        "node": "generate_report_specification",
        "message": STATUS_MESSAGES["generate_report_specification"],
    }
    spec = await build_specification(request, collection_result.data)

    yield {
        "event": "progress",
        "node": "validate_report_specification",
        "message": STATUS_MESSAGES["validate_report_specification"],
    }
    known_alarm_numbers = {
        a["alarm_number"] for a in collection_result.data.get("alerts", []) if a.get("alarm_number")
    }
    validation_errors = validate(spec, known_alarm_numbers)
    if validation_errors:
        yield {"event": "result", "status": "error", "errors": validation_errors, "company": collection_result.company}
        return

    yield {"event": "progress", "node": "generate_document", "message": STATUS_MESSAGES["generate_document"]}
    try:
        document_path = render(spec, conversation_id, format=request.format)
    except DocumentGenerationError as exc:
        yield {"event": "result", "status": "error", "errors": [str(exc)], "company": collection_result.company}
        return

    yield {
        "event": "result",
        "status": "ready",
        "errors": [],
        "company": collection_result.company,
        "specification": spec,
        "document_path": document_path,
        "collected_data": collection_result.data,
        "analysis": analysis,
    }
