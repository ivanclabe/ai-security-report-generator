"""DataProvider abstraction.

Everything the agent knows about a client's security posture flows through
this interface, always as NormalizedSecurityAlert. Swapping the source --
synthetic mock data, the remote alarm source (HTTP), a future database --
requires no changes to tools or the agent, only a different DataProvider
implementation returning the same normalized shape.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from app.models.domain import (
    AlertMetrics,
    Company,
    EmailRarityEntry,
    NormalizedSecurityAlert,
    Notification,
    SourceIndicators,
)


class DataProvider(ABC):
    @abstractmethod
    async def get_company(self, *, company_id: str | None = None, name: str | None = None) -> Company | None:
        ...

    @abstractmethod
    async def search_companies(self, query: str) -> list[Company]:
        ...

    @abstractmethod
    async def get_security_alerts(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> list[NormalizedSecurityAlert]:
        ...

    @abstractmethod
    async def get_alert_by_id(self, alert_id: str) -> NormalizedSecurityAlert | None:
        """Lookup by technical id, alarm number, or original_id -- for citing evidence."""
        ...

    @abstractmethod
    async def get_notifications(self, alert_ids: list[str]) -> list[Notification]:
        ...

    @abstractmethod
    async def get_security_metrics(
        self,
        company_id: str,
        start_date: datetime,
        end_date: datetime,
        category: str | None = None,
        risk_level: str | list[str] | None = None,
    ) -> AlertMetrics:
        ...

    async def get_top_rarity_email_recipients(self, company_id: str) -> list[EmailRarityEntry] | None:
        """Top inbound-email recipients by rarity-score volume, if this provider has that data.

        Not part of the core alarm model, so it's a concrete (non-abstract) method
        that defaults to "not available" rather than forcing every provider to implement it.
        """
        return None

    async def get_source_indicators(
        self, company_id: str, start_date: datetime, end_date: datetime
    ) -> SourceIndicators | None:
        """The source's own dashboard figures for the period (totals, tops, per-day,
        categories), when the provider has them. Not part of the core alarm model."""
        return None
