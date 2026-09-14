import re
from datetime import datetime
from pathlib import Path

from app.models.domain import AlertMetrics, Company, EmailRarityEntry, Notification, NormalizedSecurityAlert
from app.providers.base import DataProvider
from app.providers.excel_ingestion import ingest_alarmas_sheet, ingest_email_rarity_ranking, load_mitre_catalog


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "client"


class ExcelDataProvider(DataProvider):
    """Serves security alerts normalized from a client's Excel alarm export.

    The client column in the source file becomes the "company" -- there is
    no separate company metadata sheet, so industry/country are left
    unspecified rather than invented.
    """

    def __init__(self, excel_path: Path, mitre_tactics_path: Path, sheet_name: str = "Alarmas"):
        mitre_catalog = load_mitre_catalog(mitre_tactics_path)
        result = ingest_alarmas_sheet(excel_path, mitre_catalog, sheet_name=sheet_name)
        self._alerts: list[NormalizedSecurityAlert] = result.alerts
        self.ingestion_warnings: list[str] = result.warnings

        client_names = sorted({a.client for a in self._alerts})
        self._companies: list[Company] = [
            Company(id=_slugify(name), name=name, industry="No especificado", country="No especificado")
            for name in client_names
        ]
        self._company_names = {c.id: c.name for c in self._companies}

        rarity_entries = ingest_email_rarity_ranking(excel_path)
        self._email_rarity_ranking = [EmailRarityEntry(email=e, count=c) for e, c in rarity_entries]

    @property
    def alerts(self) -> list[NormalizedSecurityAlert]:
        """Read-only view of every alert ingested, unfiltered -- for callers outside
        the DataProvider contract that need the full set (e.g. ingestion_service.py
        recording import metadata), not for use by tools/ or the agent."""
        return list(self._alerts)

    @property
    def companies(self) -> list[Company]:
        return list(self._companies)

    async def get_company(self, *, company_id: str | None = None, name: str | None = None) -> Company | None:
        if company_id:
            return next((c for c in self._companies if c.id == company_id), None)
        if name:
            needle = name.strip().lower()
            for c in self._companies:
                if c.name.lower() == needle:
                    return c
            for c in self._companies:
                if needle in c.name.lower() or c.name.lower() in needle:
                    return c
        return None

    async def search_companies(self, query: str) -> list[Company]:
        needle = query.strip().lower()
        return [c for c in self._companies if needle in c.name.lower()]

    def _filter_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None,
        risk_level: str | list[str] | None,
    ) -> list[NormalizedSecurityAlert]:
        client_name = self._company_names.get(company_id)
        risk_levels = None
        if risk_level:
            risk_levels = {risk_level} if isinstance(risk_level, str) else set(risk_level)
        result = []
        for a in self._alerts:
            if a.client != client_name:
                continue
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

    async def get_security_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> list[NormalizedSecurityAlert]:
        return self._filter_alerts(company_id, start_date, end_date, category, risk_level)

    async def get_alert_by_id(self, alert_id: str) -> NormalizedSecurityAlert | None:
        return next((a for a in self._alerts if a.id == alert_id or a.alarm_number == alert_id), None)

    async def get_notifications(self, alert_ids: list[str]) -> list[Notification]:
        # The alarm export has no separate notification log -- nothing to invent here.
        return []

    async def get_security_metrics(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> AlertMetrics:
        alerts = self._filter_alerts(company_id, start_date, end_date, category, risk_level)
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
        if company_id not in self._company_names:
            return None
        return self._email_rarity_ranking or None
