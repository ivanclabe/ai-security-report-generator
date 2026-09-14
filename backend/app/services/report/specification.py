"""ReportSpecService -- assembles the final ReportSpecification from a
ReportRequest + collected data, delegating section structure to whichever
template is registered (templates.py) and narrative prose to the LLM
(narrative.py). This outer assembly (document_control, company, period,
objective, services, sections, recommendations) is shared across every
template -- it's the part that genuinely doesn't vary by report type.
"""
import json
from datetime import date

from app.schemas.report_spec import DocumentControl, ReportPeriod, ReportSpecification
from app.services.report.narrative import _build_narrative_payload, generate_narrative
from app.services.report.request import ReportRequest
from app.services.report.templates import get_template


async def build_specification(request: ReportRequest, collected: dict) -> ReportSpecification:
    payload = _build_narrative_payload(collected)
    narrative = await generate_narrative(
        json.dumps(payload, indent=2, default=str),
        company=request.company,
        start_date=request.start_date,
        end_date=request.end_date,
        audience=request.audience,
        report_requirements=request.report_requirements,
    )

    template = get_template(request.report_type)
    sections = template(collected, narrative)

    return ReportSpecification(
        document_control=DocumentControl(
            titulo=f"Informe de Gestión — Servicio de Monitoreo SOC — {request.company}",
            fecha_version=date.today().isoformat(),
        ),
        company=request.company,
        period=ReportPeriod(start=request.start_date, end=request.end_date),
        objective=narrative.objective,
        services=collected.get("services", []),
        sections=sections,
        recommendations=narrative.recommendations,
    )
