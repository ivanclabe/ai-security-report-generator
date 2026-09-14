"""Thin LangGraph adapter over ReportSpecService -- structure/narrative/template
logic now lives in app/services/report/{specification,templates,narrative}.py
(AGENT_ARCHITECTURE.md)."""
from app.agents.state import ReportState
from app.services.report.request import ReportRequest
from app.services.report.specification import build_specification


async def generate_report_specification(state: ReportState) -> dict:
    request = ReportRequest.from_state(state)
    collected = state.get("collected_data") or {}
    spec = await build_specification(request, collected)
    return {"report_specification": spec.model_dump()}
