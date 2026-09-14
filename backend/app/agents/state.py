from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field


def _replace(_old: Any, new: Any) -> Any:
    """Reducer: the latest write always wins (no auto-merge across nodes)."""
    return new


class ReportState(TypedDict, total=False):
    conversation_id: str
    user_request: str

    company: str | None
    company_id: str | None
    start_date: str | None
    end_date: str | None
    report_type: str | None
    audience: str | None
    focus_categories: list[str] | None
    risk_level_filter: list[str] | None
    framework: str | None
    report_requirements: str | None
    format: str | None

    collected_data: Annotated[dict, _replace]
    analysis: Annotated[dict, _replace]
    report_specification: Annotated[dict | None, _replace]
    report_file_path: str | None
    intent: str | None

    status: Literal[
        "collecting_requirements",
        "awaiting_user_input",
        "processing",
        "ready",
        "answered",
        "error",
    ]
    errors: Annotated[list[str], _replace]
    pending_question: str | None
    assistant_message: str | None
    data_refresh_required: bool


class ReportRequestUpdate(BaseModel):
    """Structured extraction of a single user turn, merged into ReportState."""

    intent: Literal["new_report", "modify_report", "clarification_answer", "question", "other"] = Field(
        description="Classify the user's message."
    )
    company: str | None = Field(default=None, description="Company name mentioned, if any.")
    start_date: str | None = Field(default=None, description="ISO date (YYYY-MM-DD), inferred if relative.")
    end_date: str | None = Field(default=None, description="ISO date (YYYY-MM-DD), inferred if relative.")
    report_type: str | None = Field(default=None, description="e.g. general, executive, focused, comparison")
    audience: str | None = Field(default=None, description="e.g. executive, technical, board")
    focus_categories: list[str] | None = Field(
        default=None,
        description="Security alert categories to focus on, replacing any prior focus, exactly as the user "
        "names them (categories are discovered from the client's own data -- never assume a fixed list; if "
        "unsure of the exact spelling, use the user's wording as-is and let the data lookup confirm it).",
    )
    risk_level_filter: list[str] | None = Field(
        default=None,
        description="Risk levels to include, using the client's own labels: Critico, Alto, Medio, Bajo "
        "(map 'critical'->Critico, 'high'->Alto, 'medium'->Medio, 'low'->Bajo if the user writes in English).",
    )
    framework: str | None = Field(default=None, description="e.g. NIST CSF, ISO 27001, CIS Controls, MITRE ATT&CK")
    report_requirements: str | None = Field(
        default=None, description="Any other free-form requirement not captured above."
    )
    format: Literal["docx", "pdf"] | None = Field(
        default=None, description="Output file format, only if the user explicitly asks for one."
    )
    missing_info_question: str | None = Field(
        default=None,
        description="If required info (company or period) is still missing after this update, "
        "the single clarifying question to ask the user. Otherwise null.",
    )
