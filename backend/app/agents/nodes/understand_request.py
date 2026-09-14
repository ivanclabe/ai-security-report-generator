from datetime import date

from app.agents.llm import get_chat_model
from app.agents.state import ReportRequestUpdate, ReportState

SYSTEM_PROMPT = """You are the request-understanding component of a security report generator.

Extract structured fields from the user's latest message, in the context of \
the conversation so far. Today's date is {today}.

Rules:
- Only set a field if the user's latest message provides or changes it. Leave others null.
- Resolve relative dates/periods ("last 3 months", "August 2026", "agosto") into absolute \
  ISO dates (YYYY-MM-DD) using today's date as the reference point.
- focus_categories, risk_level_filter REPLACE any prior value when the user gives a new one \
  (they are not additive), except when the user says to ADD one more item on top of an existing \
  report -- in that case include the full resulting list.
- intent = "new_report" only if there is no existing report yet for this conversation and the \
  user is asking for one. Use "modify_report" if a report already exists and the user is asking \
  to change/regenerate it. Use "clarification_answer" if this message is just answering a \
  question you previously asked (e.g. supplying a missing period or company). Use "question" when \
  the user is asking about specific data already discussed (e.g. "what happened with alarm X", \
  "tell me more about that category", "why does that IP show up so often", "how have critical \
  alarms evolved this quarter", "compare this month to the previous one") without asking to \
  create or change the report itself. Use "other" for anything unrelated to generating/modifying \
  a report or asking about its data.
- A report can only be generated once both company and a period (start_date+end_date) are known, \
  combining the current message with everything already known in the conversation (provided below). \
  If, after applying this update, company or period would still be missing, set \
  missing_info_question to the single most important clarifying question to ask next. \
  Otherwise leave it null.
- Write missing_info_question in Spanish (the client's data and the product's UI are in \
  Spanish), unless the user has been writing in a different language, in which case match them.
- format: set only when the user explicitly asks for a specific file format ("as PDF", "en Word", \
  "en docx"). Changing format alone does not require re-collecting data.

Current known state:
{current_state}
"""


def _summarize_current_state(state: ReportState) -> str:
    keys = [
        "company",
        "company_id",
        "start_date",
        "end_date",
        "report_type",
        "audience",
        "focus_categories",
        "risk_level_filter",
        "framework",
        "report_requirements",
        "format",
    ]
    lines = [f"- {k}: {state.get(k)}" for k in keys]
    has_report = bool(state.get("report_specification"))
    lines.append(f"- report already generated for this conversation: {has_report}")
    return "\n".join(lines)


async def understand_request(state: ReportState) -> dict:
    model = get_chat_model().with_structured_output(ReportRequestUpdate)
    system = SYSTEM_PROMPT.format(today=date.today().isoformat(), current_state=_summarize_current_state(state))

    update: ReportRequestUpdate = await model.ainvoke(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": state["user_request"]},
        ]
    )

    changed_refresh_fields = False
    refresh_fields = ("company", "start_date", "end_date", "focus_categories", "risk_level_filter", "framework")
    for field in refresh_fields:
        new_value = getattr(update, field)
        if new_value is not None and new_value != state.get(field):
            changed_refresh_fields = True
            break

    result: dict = {}
    for field in (
        "company",
        "start_date",
        "end_date",
        "report_type",
        "audience",
        "focus_categories",
        "risk_level_filter",
        "framework",
        "report_requirements",
        "format",
    ):
        value = getattr(update, field)
        if value is not None:
            result[field] = value

    result["pending_question"] = update.missing_info_question
    result["data_refresh_required"] = changed_refresh_fields or not state.get("collected_data")
    result["status"] = "awaiting_user_input" if update.missing_info_question else "processing"
    result["intent"] = update.intent
    return result
