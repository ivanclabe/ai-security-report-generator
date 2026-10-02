"""Thin LangGraph adapter over DataCollectionService -- translates
ReportState <-> ReportRequest/CollectedData. No business logic lives here;
see app/services/report/collection.py for the actual implementation
(AGENT_ARCHITECTURE.md)."""
from app.agents.state import ReportState
from app.services.report.collection import CompanyNotFoundError, collect
from app.services.report.request import ReportRequest


async def collect_data(state: ReportState) -> dict:
    request = ReportRequest.from_state(state)
    try:
        result = await collect(request)
    except CompanyNotFoundError as exc:
        if exc.candidates:
            question = (
                f"'{exc.company_name}' no identifica a una sola empresa. "
                f"¿Cuál de estas quieres? {', '.join(exc.candidates)}"
            )
        else:
            question = (
                f"No encontré un cliente que coincida con '{exc.company_name}'. "
                "¿Puedes confirmar el nombre exacto?"
            )
        return {"status": "awaiting_user_input", "pending_question": question, "errors": [str(exc)]}

    return {
        "company_id": result.company.id,
        "company": result.company.name,
        "collected_data": result.data,
        "errors": [],
    }
