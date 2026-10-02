"""DataCollectionService -- moved verbatim from the old collect_data node body
(see AGENT_ARCHITECTURE.md). Framework-agnostic: takes a ReportRequest, talks
to the DataProvider via security_tools, returns a plain dict. The LangGraph
node (app/agents/nodes/collect_data.py) is now a thin adapter over this.
"""
from datetime import datetime, timezone

from pydantic import BaseModel

from app.models.domain import Company
from app.providers.factory import get_data_provider
from app.services.company_registry import get_company_registry
from app.services.report import csoc_facts
from app.services.report.request import ReportRequest
from app.tools import security_tools as tools


class CompanyNotFoundError(Exception):
    """The requested company text matched no registered company, or matched
    several (then `candidates` lists them so the user can pick one)."""

    def __init__(self, company_name: str | None, candidates: list[str] | None = None):
        self.company_name = company_name
        self.candidates = candidates or []
        message = f"No se encontró la empresa '{company_name}'."
        if self.candidates:
            message += f" ¿Te refieres a: {', '.join(self.candidates)}?"
        super().__init__(message)


async def _candidate_names(text: str | None) -> list[str]:
    try:
        return [c.name for c in await get_company_registry().suggest(text)]
    except Exception:  # noqa: BLE001 - suggestions are a courtesy; never mask the real "not found"
        return []


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def _months_back(dt: datetime, n: int) -> datetime:
    month = dt.month - n
    year = dt.year
    while month <= 0:
        month += 12
        year -= 1
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


class CollectionResult(BaseModel):
    company: Company
    data: dict


async def collect(request: ReportRequest, provider=None) -> CollectionResult:
    """`provider` defaults to the app's data provider; the LLM quality evaluation passes the
    synthetic mock provider so comparing models never sends real client data anywhere."""
    provider = provider or get_data_provider()

    company = await tools.get_company(
        provider, tools.GetCompanyParams(company_id=request.company_id, name=request.company)
    )
    if company is None:
        raise CompanyNotFoundError(request.company, await _candidate_names(request.company or request.company_id))

    start_date = _parse_date(request.start_date)
    end_date = _parse_date(request.end_date, end_of_day=True)

    category = None
    focus_categories = request.focus_categories
    if focus_categories and len(focus_categories) == 1:
        category = focus_categories[0]

    risk_level = request.risk_level_filter

    summary = await tools.get_security_summary(
        provider,
        tools.GetSecuritySummaryParams(
            company_id=company.id, start_date=start_date, end_date=end_date, category=category, risk_level=risk_level
        ),
    )
    alerts = await tools.get_security_alerts(
        provider,
        tools.GetSecurityAlertsParams(
            company_id=company.id, start_date=start_date, end_date=end_date, category=category, risk_level=risk_level
        ),
    )

    if focus_categories and len(focus_categories) > 1:
        alerts = [a for a in alerts if a.category in focus_categories]

    trends = await tools.get_alert_trends(
        provider,
        tools.GetAlertTrendsParams(
            company_id=company.id, start_date=start_date, end_date=end_date, category=category, risk_level=risk_level
        ),
    )

    three_months_start = _months_back(end_date, 2)
    trends_3mo = await tools.get_alert_trends(
        provider,
        tools.GetAlertTrendsParams(company_id=company.id, start_date=three_months_start, end_date=end_date),
    )

    # The report's 3-month comparison (sections 3.1/3.2): every alarm of the window, aggregated per
    # month/service/risk. Same window as trends_3mo, so the HTTP provider serves it from its cache.
    history_alerts = await tools.get_security_alerts(
        provider,
        tools.GetSecurityAlertsParams(company_id=company.id, start_date=three_months_start, end_date=end_date),
    )
    history_3mo = csoc_facts.monthly_history(
        [a.model_dump(mode="json") for a in history_alerts], csoc_facts.last_three_months(end_date.date())
    )

    mitre = await tools.get_mitre_analysis(
        provider, tools.GetMitreAnalysisParams(company_id=company.id, start_date=start_date, end_date=end_date)
    )
    response_metrics = await tools.get_response_metrics(
        provider, tools.GetResponseMetricsParams(company_id=company.id, start_date=start_date, end_date=end_date)
    )
    email_summary = await tools.get_email_security_summary(
        provider, tools.GetEmailSecuritySummaryParams(company_id=company.id, start_date=start_date, end_date=end_date)
    )
    ip_indicators = await tools.get_ip_indicators(
        provider, tools.GetIpIndicatorsParams(company_id=company.id, start_date=start_date, end_date=end_date)
    )

    notifications = await tools.get_notifications(
        provider, tools.GetNotificationsParams(alert_ids=[a.id for a in alerts])
    )

    services = sorted({a.alert_type for a in alerts if a.alert_type and a.alert_type.upper() != "ANULADO"})

    data = {
        "company": company.model_dump(),
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "metrics": summary.metrics.model_dump(),
        "alerts_by_category": summary.alerts_by_category,
        "alerts_by_risk_level": summary.alerts_by_risk_level,
        "top_risk_alerts": [a.model_dump(mode="json") for a in summary.top_risk_alerts],
        "trends": [t.model_dump() for t in trends],
        "trends_3mo": [t.model_dump() for t in trends_3mo],
        "history_3mo": history_3mo,
        "period": {"start": request.start_date, "end": request.end_date},
        "mitre_analysis": mitre.model_dump(),
        "response_metrics": response_metrics.model_dump(),
        "email_summary": email_summary.model_dump(),
        "ip_indicators": ip_indicators.model_dump(),
        "services": services,
        "notifications": [n.model_dump(mode="json") for n in notifications],
    }
    return CollectionResult(company=company, data=data)
