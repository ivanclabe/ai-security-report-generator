"""Thin LangGraph adapter over ValidationService."""
from app.agents.state import ReportState
from app.schemas.report_spec import ReportSpecification
from app.services.report.validation import validate


async def validate_report_specification(state: ReportState) -> dict:
    raw = state.get("report_specification")
    if not raw:
        return {"status": "error", "errors": ["No report specification was generated."]}

    try:
        spec = ReportSpecification.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return {"status": "error", "errors": [f"Report specification failed validation: {exc}"]}

    collected_alerts = (state.get("collected_data") or {}).get("alerts", [])
    known_alarm_numbers = {a["alarm_number"] for a in collected_alerts if a.get("alarm_number")}
    errors = validate(spec, known_alarm_numbers)
    if errors:
        return {"status": "error", "errors": errors}

    return {"status": "processing", "errors": []}
