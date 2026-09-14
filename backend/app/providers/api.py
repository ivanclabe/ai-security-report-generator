"""Placeholder for a future REST/JSON DataProvider.

The client has said they will eventually expose security data via API instead
of (or alongside) the monthly Excel export. There is no real endpoint to
integrate against yet, so this class implements the DataProvider contract
with explicit NotImplementedError messages instead of fabricating request
logic against a service that doesn't exist -- it exists to make the
extension point concrete in code, not to be usable today.

When a real API exists, implement each method here: fetch via httpx (already
a dependency), map the JSON response into NormalizedSecurityAlert with the
same validation rigor ingestion_service.py already applies to Excel
(required fields, dates, duplicates), and reuse ingestion_service.py to
record import metadata -- its contract (data_source_id, a hash/sync marker,
warnings) is already agnostic of whether the source was a file or an HTTP
response.
"""
from datetime import datetime

from app.models.domain import (
    AlertMetrics,
    Company,
    EmailRarityEntry,
    NormalizedSecurityAlert,
    Notification,
)
from app.providers.base import DataProvider

_NOT_IMPLEMENTED = (
    "ApiDataProvider is a placeholder for a future client API integration -- "
    "no real endpoint, authentication, or payload mapping exists yet. "
    "Implement this method when that API is available (see INGESTION_ARCHITECTURE.md §6)."
)


class ApiDataProvider(DataProvider):
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key

    async def get_company(self, *, company_id: str | None = None, name: str | None = None) -> Company | None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def search_companies(self, query: str) -> list[Company]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_security_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> list[NormalizedSecurityAlert]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_alert_by_id(self, alert_id: str) -> NormalizedSecurityAlert | None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_notifications(self, alert_ids: list[str]) -> list[Notification]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_security_metrics(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> AlertMetrics:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def get_top_rarity_email_recipients(self, company_id: str) -> list[EmailRarityEntry] | None:
        raise NotImplementedError(_NOT_IMPLEMENTED)
