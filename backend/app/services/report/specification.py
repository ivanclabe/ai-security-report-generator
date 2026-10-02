"""ReportSpecService -- assembles the final ReportSpecification from a
ReportRequest + collected data, delegating section structure to whichever
template is registered (templates.py) and narrative prose to the LLM
(narrative.py). This outer assembly (document_control, company, period,
objective, services, sections, recommendations) is shared across every
template -- it's the part that genuinely doesn't vary by report type.
"""
import json
from datetime import date, datetime

from app.schemas.report_spec import DocumentControl, ReportPeriod, ReportSpecification
from app.services.report.narrative import (
    ReportNarrative,
    _build_narrative_payload,
    generate_narrative,
)
from app.services.report.request import ReportRequest
from app.services.report.templates import get_template


async def build_specification(request: ReportRequest, collected: dict) -> ReportSpecification:
    narrative = await narrative_for(request, collected)
    return assemble_specification(request, collected, narrative)


async def narrative_for(request: ReportRequest, collected: dict) -> ReportNarrative:
    """The LLM step of the specification (also used by the provider quality evaluation)."""
    collected = {**collected, "period": {"start": request.start_date, "end": request.end_date}}
    payload = _build_narrative_payload(collected)
    return await generate_narrative(
        json.dumps(payload, indent=2, default=str),
        company=request.company,
        start_date=request.start_date,
        end_date=request.end_date,
        audience=request.audience,
        report_requirements=request.report_requirements,
    )


OBJECTIVE_TEMPLATE = (
    "Dar a conocer el estado general y actividades gestionadas, correlacionamiento y gestión de alarmas, los "
    "procesos de vigilancia y control de activos, monitoreo de los servicios de seguridad por medio de la "
    "recolección de logs, detección de intrusos y evaluación de vulnerabilidades de los diferentes segmentos de "
    "la red {company} de acuerdo con el alcance pactado con el cliente."
)


def _author() -> str:
    """Who generated the report (the signed-in member); the app never invents a person."""
    from app.security.context import get_current_user

    user = get_current_user()
    if user is None:
        return "Generado automáticamente por la plataforma"
    return user.display_name or user.email or "Generado automáticamente por la plataforma"


def assemble_specification(request: ReportRequest, collected: dict, narrative: ReportNarrative) -> ReportSpecification:
    """Deterministic part: template sections + document metadata around the narrative.
    Only the recommendations come from the LLM, and only those whose figures and cited
    alarms the data supports survive (validation.ground_recommendations)."""
    from app.services.report import csoc_facts
    from app.services.report.validation import ground_recommendations

    collected = {**collected, "period": {"start": request.start_date, "end": request.end_date}}
    template = get_template(request.report_type)
    sections = template(collected, narrative)

    # The company as the registry knows it (collect() resolved it): its official report name
    # and logo win over whatever spelling the user typed.
    company = collected.get("company") or {}
    company_name = company.get("name") or request.company
    start, end = date.fromisoformat(request.start_date), date.fromisoformat(request.end_date)
    alerts = collected.get("alerts", [])
    facts = csoc_facts.build_facts(alerts, collected.get("history_3mo"), start, end)
    known_alarms = {a["alarm_number"] for a in alerts if a.get("alarm_number")}
    recommendations, notes = ground_recommendations(
        narrative.recommendations, csoc_facts.allowed_numbers(facts, alerts), known_alarms
    )
    services = csoc_facts.ordered_services(
        {s for s in csoc_facts.service_counts(alerts) if s != csoc_facts.ANULADAS}
    )

    return ReportSpecification(
        document_control=DocumentControl(
            titulo=f"Informe Correspondiente al período {facts['period'] if facts['period'].startswith('del') else 'de ' + facts['period']}.",
            autor=_author(),
            fecha_version=datetime.now().astimezone().strftime("%d/%m/%Y"),
        ),
        company=company_name,
        company_logo=company.get("logo_key"),
        period=ReportPeriod(start=request.start_date, end=request.end_date),
        objective=OBJECTIVE_TEMPLATE.format(company=company_name),
        services=services,
        sections=sections,
        recommendations=recommendations,
        facts=facts,
        validation_notes=notes,
    )
