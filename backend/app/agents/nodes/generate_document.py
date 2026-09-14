"""Thin LangGraph adapter over DocumentService."""
from app.agents.state import ReportState
from app.schemas.report_spec import ReportSpecification
from app.services.report.document import DocumentGenerationError, render


async def generate_document(state: ReportState) -> dict:
    spec = ReportSpecification.model_validate(state["report_specification"])
    try:
        output_path = render(spec, state["conversation_id"], format=state.get("format") or "docx")
    except DocumentGenerationError as exc:
        return {"status": "error", "errors": [str(exc)]}
    return {"report_file_path": str(output_path)}
