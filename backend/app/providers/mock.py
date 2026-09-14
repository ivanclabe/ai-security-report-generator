import json
from datetime import datetime, timedelta
from pathlib import Path

from app.models.domain import (
    AlertMetrics,
    Company,
    Notification,
    NormalizedSecurityAlert,
    risk_level_from_score,
)
from app.providers.base import DataProvider


class MockDataProvider(DataProvider):
    """Serves synthetic security data loaded from a static JSON fixture.

    Kept for demos/tests independent of any real client file. Emits the same
    NormalizedSecurityAlert shape as ExcelDataProvider.
    """

    def __init__(self, data_path: Path):
        raw = json.loads(data_path.read_text())
        self._companies: list[Company] = [Company(**c) for c in raw["companies"]]
        self._company_names = {c.id: c.name for c in self._companies}
        self._alerts: list[NormalizedSecurityAlert] = [
            self._to_normalized(a) for a in raw["alerts"]
        ]
        self._notifications: list[Notification] = [Notification(**n) for n in raw["notifications"]]

    def _to_normalized(self, raw: dict) -> NormalizedSecurityAlert:
        ts = datetime.fromisoformat(raw["timestamp"])
        severity_score = round(raw["risk_score"])
        is_resolved = raw["status"] == "resolved"
        return NormalizedSecurityAlert(
            id=raw["id"],
            alarm_number=raw["id"],
            original_id=None,
            client=self._company_names.get(raw["company_id"], raw["company_id"]),
            alert_type=raw["source"],
            category=raw["category"],
            severity_score=severity_score,
            risk_level=risk_level_from_score(severity_score),
            is_voided=False,
            event_timestamp=ts,
            created_at=ts,
            reported_at=ts,
            hostnames=[raw["affected_asset"]],
            description=raw["description"],
            mitre_tactic_id=None,
            mitre_tactic_name=None,
            recommendations=None,
            response="Alert marked resolved by the security team (synthetic demo data)."
            if is_resolved
            else None,
            responded_at=(ts + timedelta(hours=4)) if is_resolved else None,
            status="resolved" if is_resolved else "open",
            raw_record=raw,
        )

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

    def _company_id_to_name(self, company_id: str) -> str | None:
        return self._company_names.get(company_id)

    def _filter_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None,
        risk_level: str | list[str] | None,
    ) -> list[NormalizedSecurityAlert]:
        client_name = self._company_id_to_name(company_id)
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
        alert_id_set = set(alert_ids)
        return [n for n in self._notifications if n.alert_id in alert_id_set]

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
