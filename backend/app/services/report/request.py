"""ReportRequest -- the transport-agnostic input to the report-generation
pipeline (see AGENT_ARCHITECTURE.md / ARCHITECTURE_TARGET.md §3.1).

Both the conversational agent (built from ReportState, via from_state) and a
future deterministic form endpoint (built directly from form fields) produce
the same ReportRequest, so app/services/report/* never needs to know which
one it came from.
"""
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.agents.state import ReportState


class ReportRequest(BaseModel):
    conversation_id: str | None = None
    company: str | None = None
    company_id: str | None = None
    start_date: str
    end_date: str
    report_type: str | None = None
    audience: str | None = None
    focus_categories: list[str] | None = None
    risk_level_filter: list[str] | None = None
    framework: str | None = None
    report_requirements: str | None = None
    format: str = "docx"

    @classmethod
    def from_state(cls, state: "ReportState") -> "ReportRequest":
        return cls(
            conversation_id=state.get("conversation_id"),
            company=state.get("company"),
            company_id=state.get("company_id"),
            start_date=state["start_date"],
            end_date=state["end_date"],
            report_type=state.get("report_type"),
            audience=state.get("audience"),
            focus_categories=state.get("focus_categories"),
            risk_level_filter=state.get("risk_level_filter"),
            framework=state.get("framework"),
            report_requirements=state.get("report_requirements"),
            format=state.get("format") or "docx",
        )
