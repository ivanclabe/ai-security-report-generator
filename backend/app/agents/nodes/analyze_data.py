"""Thin LangGraph adapter over AnalysisService."""
from app.agents.state import ReportState
from app.services.report.analysis import analyze


async def analyze_data(state: ReportState) -> dict:
    return {"analysis": analyze(state.get("collected_data") or {})}
