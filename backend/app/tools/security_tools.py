"""Explicit, Pydantic-validated tools the agent may call.

No tool accepts or executes arbitrary code/SQL from the LLM: every parameter
is a typed, validated field and every tool delegates to the DataProvider
abstraction. Analytics that don't need a dedicated provider method (MITRE
breakdown, response-rate) are computed here, generically, from whatever
list[NormalizedSecurityAlert] the provider returns -- so they work
identically against mock or Excel-sourced data.
"""
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.domain import AlertMetrics, Company, EmailRarityEntry, NormalizedSecurityAlert, Notification
from app.providers.base import DataProvider


class GetCompanyParams(BaseModel):
    company_id: str | None = None
    name: str | None = None


async def get_company(provider: DataProvider, params: GetCompanyParams) -> Company | None:
    return await provider.get_company(company_id=params.company_id, name=params.name)


class SearchCompaniesParams(BaseModel):
    query: str = Field(min_length=1)


async def search_companies(provider: DataProvider, params: SearchCompaniesParams) -> list[Company]:
    return await provider.search_companies(params.query)


class GetSecurityAlertsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    category: str | None = None
    risk_level: str | list[str] | None = None


async def get_security_alerts(
    provider: DataProvider, params: GetSecurityAlertsParams
) -> list[NormalizedSecurityAlert]:
    return await provider.get_security_alerts(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )


class GetSecurityMetricsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    category: str | None = None
    risk_level: str | list[str] | None = None


async def get_security_metrics(provider: DataProvider, params: GetSecurityMetricsParams) -> AlertMetrics:
    return await provider.get_security_metrics(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )


class GetNotificationsParams(BaseModel):
    alert_ids: list[str]


async def get_notifications(provider: DataProvider, params: GetNotificationsParams) -> list[Notification]:
    return await provider.get_notifications(params.alert_ids)


class GetAlarmRecordParams(BaseModel):
    alarm_id: str = Field(min_length=1)


async def get_alarm_record(provider: DataProvider, params: GetAlarmRecordParams) -> NormalizedSecurityAlert | None:
    return await provider.get_alert_by_id(params.alarm_id)


class GetAlertsByCategoryParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime


async def get_alerts_by_category(
    provider: DataProvider, params: GetAlertsByCategoryParams
) -> dict[str, list[NormalizedSecurityAlert]]:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )
    grouped: dict[str, list[NormalizedSecurityAlert]] = {}
    for alert in alerts:
        grouped.setdefault(alert.category, []).append(alert)
    return grouped


class GetAlertsBySeverityParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime


async def get_alerts_by_severity(
    provider: DataProvider, params: GetAlertsBySeverityParams
) -> dict[str, list[NormalizedSecurityAlert]]:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )
    grouped: dict[str, list[NormalizedSecurityAlert]] = {}
    for alert in alerts:
        grouped.setdefault(alert.risk_level.value, []).append(alert)
    return grouped


class GetAlertTrendsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    category: str | None = None
    risk_level: str | list[str] | None = None
    granularity: str = "month"  # "day" | "week" | "month"


class TrendPoint(BaseModel):
    period: str
    total_alerts: int
    critico_alerts: int
    average_severity_score: float


def _period_key(ts: datetime, granularity: str) -> str:
    if granularity == "day":
        return ts.strftime("%Y-%m-%d")
    if granularity == "week":
        year, week, _ = ts.isocalendar()
        return f"{year}-W{week:02d}"
    return ts.strftime("%Y-%m")


async def get_alert_trends(provider: DataProvider, params: GetAlertTrendsParams) -> list[TrendPoint]:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )
    buckets: dict[str, list[NormalizedSecurityAlert]] = {}
    for alert in alerts:
        key = _period_key(alert.event_timestamp, params.granularity)
        buckets.setdefault(key, []).append(alert)

    trends = []
    for period in sorted(buckets):
        bucket_alerts = buckets[period]
        total = len(bucket_alerts)
        scored = [a.severity_score for a in bucket_alerts if a.severity_score is not None]
        avg_score = round(sum(scored) / len(scored), 1) if scored else 0.0
        trends.append(
            TrendPoint(
                period=period,
                total_alerts=total,
                critico_alerts=sum(1 for a in bucket_alerts if a.risk_level.value == "Critico"),
                average_severity_score=avg_score,
            )
        )
    return trends


class GetSecuritySummaryParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    category: str | None = None
    risk_level: str | list[str] | None = None


class SecuritySummary(BaseModel):
    metrics: AlertMetrics
    alerts_by_category: dict[str, int]
    alerts_by_risk_level: dict[str, int]
    top_risk_alerts: list[NormalizedSecurityAlert]


async def get_security_summary(provider: DataProvider, params: GetSecuritySummaryParams) -> SecuritySummary:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )
    metrics = await provider.get_security_metrics(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )
    by_category: dict[str, int] = {}
    by_risk_level: dict[str, int] = {}
    for a in alerts:
        by_category[a.category] = by_category.get(a.category, 0) + 1
        by_risk_level[a.risk_level.value] = by_risk_level.get(a.risk_level.value, 0) + 1

    top_risk = sorted(alerts, key=lambda a: a.severity_score or 0, reverse=True)[:10]

    return SecuritySummary(
        metrics=metrics,
        alerts_by_category=by_category,
        alerts_by_risk_level=by_risk_level,
        top_risk_alerts=top_risk,
    )


class GetMitreAnalysisParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime


class MitreTacticFinding(BaseModel):
    tactic_id: str
    tactic_name: str
    alert_count: int
    alarm_numbers: list[str]


class MitreAnalysis(BaseModel):
    tactics: list[MitreTacticFinding]
    alerts_without_mitre_data: int


async def get_mitre_analysis(provider: DataProvider, params: GetMitreAnalysisParams) -> MitreAnalysis:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )
    buckets: dict[str, MitreTacticFinding] = {}
    without_mitre = 0
    for a in alerts:
        if not a.mitre_tactic_id:
            without_mitre += 1
            continue
        key = a.mitre_tactic_id
        if key not in buckets:
            buckets[key] = MitreTacticFinding(
                tactic_id=key, tactic_name=a.mitre_tactic_name or key, alert_count=0, alarm_numbers=[]
            )
        buckets[key].alert_count += 1
        buckets[key].alarm_numbers.append(a.alarm_number)

    tactics = sorted(buckets.values(), key=lambda t: t.alert_count, reverse=True)
    return MitreAnalysis(tactics=tactics, alerts_without_mitre_data=without_mitre)


class GetResponseMetricsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime


class ResponseMetrics(BaseModel):
    total_alerts: int
    with_response: int
    without_response: int
    response_rate_pct: float
    average_response_time_hours: float | None


async def get_response_metrics(provider: DataProvider, params: GetResponseMetricsParams) -> ResponseMetrics:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )
    total = len(alerts)
    with_response = [a for a in alerts if a.status == "resolved" and a.responded_at]
    rate = round((len(with_response) / total) * 100, 1) if total else 0.0

    response_hours = [
        (a.responded_at - a.created_at).total_seconds() / 3600
        for a in with_response
        if a.responded_at and a.created_at
    ]
    avg_hours = round(sum(response_hours) / len(response_hours), 1) if response_hours else None

    return ResponseMetrics(
        total_alerts=total,
        with_response=len(with_response),
        without_response=total - len(with_response),
        response_rate_pct=rate,
        average_response_time_hours=avg_hours,
    )


class GetEmailSecuritySummaryParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime


class DataLeakSender(BaseModel):
    sender: str
    count: int
    alarm_numbers: list[str]


class EmailSecuritySummary(BaseModel):
    top_rarity_recipients: list[EmailRarityEntry]
    rarity_data_available: bool
    data_leak_senders: list[DataLeakSender]


# Category the client's own alarm export uses for outbound email flagged as a
# possible data leak -- combined with alert_type, matches their "Correos
# Salientes" table exactly (verified against the client's July 2026 report).
_DATA_LEAK_EMAIL_CATEGORY = "Exfiltración por servicio web"
_EMAIL_ALERT_TYPE = "ANTÍGENO CORREO"


async def get_email_security_summary(
    provider: DataProvider, params: GetEmailSecuritySummaryParams
) -> EmailSecuritySummary:
    rarity = await provider.get_top_rarity_email_recipients(params.company_id)

    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )
    senders: dict[str, DataLeakSender] = {}
    for a in alerts:
        if a.alert_type != _EMAIL_ALERT_TYPE or a.category != _DATA_LEAK_EMAIL_CATEGORY:
            continue
        sender = a.raw_record.get("sourceIP") or (a.source_ips[0] if a.source_ips else None)
        if not sender:
            continue
        if sender not in senders:
            senders[sender] = DataLeakSender(sender=sender, count=0, alarm_numbers=[])
        senders[sender].count += 1
        senders[sender].alarm_numbers.append(a.alarm_number)

    return EmailSecuritySummary(
        top_rarity_recipients=rarity or [],
        rarity_data_available=rarity is not None,
        data_leak_senders=sorted(senders.values(), key=lambda s: s.count, reverse=True),
    )


class GetIpIndicatorsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    top_n: int = 5


class IpIndicator(BaseModel):
    ip: str
    count: int
    alarm_numbers: list[str]


class IpIndicators(BaseModel):
    top_source_ips: list[IpIndicator]
    top_external_ips: list[IpIndicator]


class SearchAlertsParams(BaseModel):
    company_id: str
    start_date: datetime
    end_date: datetime
    category: str | None = None
    risk_level: str | None = None
    keyword: str | None = Field(default=None, description="Matched against description/category, case-insensitive.")
    limit: int = 10


async def search_alerts(provider: DataProvider, params: SearchAlertsParams) -> list[NormalizedSecurityAlert]:
    """Read-only, bounded lookup -- backs the agent's answer_question node
    (ad-hoc questions), not the deterministic report pipeline."""
    alerts = await provider.get_security_alerts(
        company_id=params.company_id,
        start_date=params.start_date,
        end_date=params.end_date,
        category=params.category,
        risk_level=params.risk_level,
    )
    if params.keyword:
        needle = params.keyword.lower()
        alerts = [
            a
            for a in alerts
            if needle in (a.description or "").lower() or needle in (a.category or "").lower()
        ]
    return alerts[: params.limit]


async def get_ip_indicators(provider: DataProvider, params: GetIpIndicatorsParams) -> IpIndicators:
    alerts = await provider.get_security_alerts(
        company_id=params.company_id, start_date=params.start_date, end_date=params.end_date
    )

    def _rank(field: str) -> list[IpIndicator]:
        buckets: dict[str, IpIndicator] = {}
        for a in alerts:
            for ip in getattr(a, field):
                if ip not in buckets:
                    buckets[ip] = IpIndicator(ip=ip, count=0, alarm_numbers=[])
                buckets[ip].count += 1
                buckets[ip].alarm_numbers.append(a.alarm_number)
        return sorted(buckets.values(), key=lambda i: i.count, reverse=True)[: params.top_n]

    return IpIndicators(top_source_ips=_rank("source_ips"), top_external_ips=_rank("external_ips"))
