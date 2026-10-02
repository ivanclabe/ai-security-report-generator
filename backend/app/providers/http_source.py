"""DataProvider backed by the remote alarm source (HTTP).

Thin adapter: companies come from the company registry, alarms from the
acquisition layer (app/ingestion). The agent, the tools and the deterministic
pipeline only ever see the DataProvider contract and NormalizedSecurityAlert,
exactly as with the previous sources -- nothing in app/agents or
app/services/report knows this provider talks HTTP.

Period/category/risk filtering happens here, in memory, over the batch the
acquisition layer fetched and cached for (company, period); the many tool calls
that make up one report therefore cost one HTTP request per distinct period.
"""
from datetime import datetime

from app.ingestion.service import AlarmAcquisitionService
from app.models.domain import (
    AlertMetrics,
    Company,
    EmailRarityEntry,
    NormalizedSecurityAlert,
    Notification,
)
from app.providers.base import DataProvider
from app.services.company_registry import CompanyRegistry


class HttpSourceDataProvider(DataProvider):
    def __init__(self, acquisition: AlarmAcquisitionService, registry: CompanyRegistry):
        self._acquisition = acquisition
        self._registry = registry

    async def aclose(self) -> None:
        await self._acquisition.aclose()

    async def get_company(self, *, company_id: str | None = None, name: str | None = None) -> Company | None:
        return await self._registry.get(company_id=company_id, name=name)

    async def search_companies(self, query: str) -> list[Company]:
        return await self._registry.search(query)

    async def get_security_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> list[NormalizedSecurityAlert]:
        company = await self._registry.get(company_id=company_id)
        if company is None:
            return []
        batch = await self._acquisition.get_batch(company, start_date, end_date)

        risk_levels = None
        if risk_level:
            risk_levels = {risk_level} if isinstance(risk_level, str) else set(risk_level)

        result = []
        for a in batch.alerts:
            ts = a.event_timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=start_date.tzinfo)
            if not (start_date <= ts <= end_date):
                continue
            if category and a.category != category:
                continue
            if risk_levels and a.risk_level.value not in risk_levels:
                continue
            result.append(a)
        return result

    async def get_alert_by_id(self, alert_id: str) -> NormalizedSecurityAlert | None:
        return self._acquisition.find_alert(alert_id)

    async def get_notifications(self, alert_ids: list[str]) -> list[Notification]:
        # The alarm export carries no notification log -- nothing to invent here.
        return []

    async def get_security_metrics(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> AlertMetrics:
        alerts = await self.get_security_alerts(company_id, start_date, end_date, category, risk_level)
        total = len(alerts)
        resolved = sum(1 for a in alerts if a.status == "resolved")
        scored = [a.severity_score for a in alerts if a.severity_score is not None]
        avg_score = round(sum(scored) / len(scored), 1) if scored else 0.0
        return AlertMetrics(
            total_alerts=total,
            critico_alerts=sum(1 for a in alerts if a.risk_level.value == "Critico"),
            alto_alerts=sum(1 for a in alerts if a.risk_level.value == "Alto"),
            medio_alerts=sum(1 for a in alerts if a.risk_level.value == "Medio"),
            bajo_alerts=sum(1 for a in alerts if a.risk_level.value == "Bajo"),
            voided_alerts=sum(1 for a in alerts if a.is_voided),
            resolved_alerts=resolved,
            open_alerts=total - resolved,
            average_severity_score=avg_score,
        )

    async def get_top_rarity_email_recipients(self, company_id: str) -> list[EmailRarityEntry] | None:
        # The alarms CSV has no precomputed email-rarity ranking (the old Excel carried one in a
        # separate sheet). Reported as "not available" so the report says so instead of guessing.
        return None
