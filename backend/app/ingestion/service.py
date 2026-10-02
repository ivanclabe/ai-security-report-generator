"""Alarm acquisition: ask the source for one company's alarms in a period,
decode and normalize them, and keep the result in a small cache.

This module is the whole boundary between "the outside world" (HTTP, CSV,
column names, company spellings) and the rest of the app. It knows nothing
about LangGraph, tools or reports: the DataProvider adapter in
app/providers/http_source.py turns an AlarmBatch into the objects the agent
consumes.

Why a cache: building one report asks the provider for the same company/period
~10 times (summary, trends, MITRE, response metrics, ...); each of those must
not become an HTTP request. Entries expire after SOURCE_CACHE_TTL_SECONDS for
fresh fetches but are kept (bounded) for alarm lookups by number, so the agent
can still cite an alarm from a report generated a few minutes ago.

Two sources, one truth: the detailed alarms come from the CSV export; the
source's own indicators page (indicadores.php) states how many alarms it counts
for the same company/period. Every fresh alarms download is reconciled against
it: an empty export while the dashboard reports alarms stops the report (instead
of producing an empty one), and any other difference is reported as a warning.
"""
import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from app.ingestion.client import SourceClient
from app.ingestion.csv_decoder import decode_alarms_csv
from app.ingestion.errors import SourceError, SourceFormatError
from app.ingestion.indicators_parser import parse_indicators_page
from app.ingestion.normalizer import normalize_alarm_rows
from app.ingestion.requests import build_alarms_request, build_indicators_request
from app.models.domain import (
    Company,
    MitreTactic,
    NormalizedSecurityAlert,
    SourceIndicators,
)
from app.services.company_registry import normalize_company_key

logger = logging.getLogger(__name__)

_KEY_FORMAT = "%Y-%m-%dT%H:%M"


def _company_keys(company: Company) -> set[str]:
    """Every spelling under which the source may name this company."""
    return {
        normalize_company_key(v)
        for v in (company.name, company.source_client, company.consecutivo, company.request_client_name)
        if v
    }


@dataclass
class AlarmBatch:
    company: Company
    start: datetime
    end: datetime
    alerts: list[NormalizedSecurityAlert]
    warnings: list[str]
    rows_received: int
    content_hash: str
    request_url: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: float = 0.0


FetchListener = Callable[[AlarmBatch], Awaitable[None]]


class AlarmAcquisitionService:
    def __init__(
        self,
        client: SourceClient,
        mitre_catalog: dict[str, MitreTactic],
        *,
        clock: Callable[[], float] = time.monotonic,
        on_fetch: FetchListener | None = None,
        max_entries: int = 32,
    ):
        self._client = client
        self._mitre_catalog = mitre_catalog
        self._clock = clock
        self._on_fetch = on_fetch
        self._max_entries = max_entries
        self._batches: OrderedDict[tuple[str, str, str], AlarmBatch] = OrderedDict()
        self._indicators: OrderedDict[tuple[str, str, str], tuple[float, SourceIndicators]] = OrderedDict()
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_batch(self, company: Company, start: datetime, end: datetime) -> AlarmBatch:
        key = (company.id, start.strftime(_KEY_FORMAT), end.strftime(_KEY_FORMAT))
        cached = self._batches.get(key)
        if cached is not None and self._clock() < cached.expires_at:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._batches.get(key)  # another task may have fetched while we waited
            if cached is not None and self._clock() < cached.expires_at:
                return cached
            batch = await self._acquire(company, start, end)
            batch.expires_at = self._clock() + self._client.config.cache_ttl_seconds
            self._batches[key] = batch
            self._batches.move_to_end(key)
            while len(self._batches) > self._max_entries:
                self._batches.popitem(last=False)

        if self._on_fetch is not None:
            try:
                await self._on_fetch(batch)
            except Exception:
                logger.warning("No se pudo registrar la importación de %s", company.name, exc_info=True)
        return batch

    async def get_indicators(self, company: Company, start: date, end: date) -> SourceIndicators:
        """The source's indicators page for one company/period (cached like the alarms)."""
        key = (company.id, start.isoformat(), end.isoformat())
        cached = self._indicators.get(key)
        if cached is not None and self._clock() < cached[0]:
            return cached[1]

        async with self._locks.setdefault(("indicadores", *key), asyncio.Lock()):
            cached = self._indicators.get(key)
            if cached is not None and self._clock() < cached[0]:
                return cached[1]
            request = build_indicators_request(self._client.config, company.request_client_name, start, end)
            indicators = parse_indicators_page((await self._client.fetch(request)).content)

            if indicators.client is None:
                indicators.warnings.append("La página de indicadores no indica qué cliente está mostrando.")
            elif normalize_company_key(indicators.client) not in _company_keys(company):
                raise SourceFormatError(
                    f"La página de indicadores corresponde al cliente '{indicators.client}', no a {company.name}: "
                    "revisa el valor de cliente= de la empresa (in_companies.source_client)."
                )
            sent_end = end + timedelta(days=1)  # the page's fecha_fin is exclusive (see requests.py)
            if (indicators.start_date, indicators.end_date) not in ((start, sent_end), (None, None)):
                indicators.warnings.append(
                    f"La página de indicadores muestra el período {indicators.start_date} a {indicators.end_date}, "
                    f"no el solicitado ({start} a {sent_end}, fin exclusivo)."
                )
            indicators.end_date = end  # expose the inclusive period the figures cover

            self._indicators[key] = (self._clock() + self._client.config.cache_ttl_seconds, indicators)
            self._indicators.move_to_end(key)
            while len(self._indicators) > self._max_entries:
                self._indicators.popitem(last=False)
        return indicators

    async def _reconcile(
        self, company: Company, start: datetime, end: datetime, alerts: list[NormalizedSecurityAlert]
    ) -> list[str]:
        try:
            indicators = await self.get_indicators(company, start.date(), end.date())
        except SourceError as exc:
            return [f"No se pudo comparar el total con el panel de indicadores de la fuente: {exc}"]

        expected = indicators.total_alarms
        if expected and not alerts:
            raise SourceFormatError(
                f"El panel de indicadores de la fuente reporta {expected} alarmas de {company.name} entre "
                f"{start.date()} y {end.date()}, pero el export de alarmas (CSV) no trajo ninguna. Se detuvo la "
                "generación para no producir un informe vacío: revisa el export detallado_alarmas "
                "(SOURCE_ALARMS_PATH) o los permisos del usuario configurado."
            )
        if expected != len(alerts):
            return [
                f"El export de alarmas trae {len(alerts)} alarmas de {company.name} y el panel de indicadores "
                f"de la fuente reporta {expected} para el mismo período."
            ]
        return []

    def find_alert(self, alert_id: str) -> NormalizedSecurityAlert | None:
        """Look an alarm up by id or alarm number in the batches fetched so far
        (newest first) -- the source has no by-number endpoint."""
        for batch in sorted(self._batches.values(), key=lambda b: b.fetched_at, reverse=True):
            for alert in batch.alerts:
                if alert.id == alert_id or alert.alarm_number == alert_id:
                    return alert
        return None

    async def _acquire(self, company: Company, start: datetime, end: datetime) -> AlarmBatch:
        config = self._client.config
        request = build_alarms_request(config, company.request_client_name, start, end)
        response = await self._client.fetch(request)

        df = decode_alarms_csv(response.content)
        rows_received = len(df)
        result = normalize_alarm_rows(df, self._mitre_catalog, source_label=f"alarmas de {company.name}")
        warnings = list(result.warnings)
        if rows_received == 0:
            warnings = [
                f"La fuente no devolvió alarmas para cliente={company.request_client_name!r} entre "
                f"{start.date()} y {end.date()}. Si se esperaban datos, verifica el valor de cliente= "
                "de la empresa (in_companies.source_client) con scripts/probe_sources.py."
            ]

        if rows_received > 0 and not result.alerts:
            detail = "; ".join(warnings[:3]) or "ninguna fila es válida"
            raise SourceFormatError(
                f"La fuente devolvió {rows_received} filas para {company.name} pero ninguna se pudo interpretar "
                f"como alarma ({detail})."
            )

        accepted = _company_keys(company)
        kept = [a for a in result.alerts if normalize_company_key(a.client) in accepted]
        foreign = [a for a in result.alerts if normalize_company_key(a.client) not in accepted]
        if result.alerts and not kept:
            seen = sorted({a.client for a in foreign})[:5]
            raise SourceFormatError(
                f"La fuente devolvió {len(foreign)} alarmas pero ninguna pertenece a {company.name} "
                f"(clientes recibidos: {', '.join(seen)}). Revisa el valor de cliente= configurado para esta "
                "empresa (in_companies.source_client)."
            )
        if foreign:
            seen = sorted({a.client for a in foreign})[:5]
            warnings.append(
                f"Se descartaron {len(foreign)} alarmas de otras empresas devueltas por la fuente "
                f"({', '.join(seen)})."
            )

        # From here on the company is identified by the registry name, whatever spelling the source uses.
        alerts = [a.model_copy(update={"client": company.name}) for a in kept]

        if rows_received >= config.alarms_limit:
            warnings.append(
                f"La fuente devolvió {rows_received} filas, igual al límite SOURCE_ALARMS_LIMIT="
                f"{config.alarms_limit}: el resultado puede estar truncado."
            )
        if alerts and self._mostly_outside_period(alerts, start, end):
            warnings.append(
                "Más de la mitad de las alarmas tienen fecha fuera del período solicitado: "
                "revisa el formato de fecha del CSV (día/mes vs mes/día)."
            )

        if config.reconcile_with_indicators:
            warnings += await self._reconcile(company, start, end, alerts)

        if warnings:
            logger.warning(
                "Alarmas de %s (%s a %s): %d advertencias, p. ej. %s",
                company.name, start.date(), end.date(), len(warnings), warnings[:3],
            )

        return AlarmBatch(
            company=company,
            start=start,
            end=end,
            alerts=alerts,
            warnings=warnings,
            rows_received=rows_received,
            content_hash=hashlib.sha256(response.content).hexdigest(),
            request_url=str(httpx.URL(request.url, params=request.params)),
        )

    @staticmethod
    def _mostly_outside_period(alerts: list[NormalizedSecurityAlert], start: datetime, end: datetime) -> bool:
        low = start.replace(tzinfo=None) - timedelta(days=1)
        high = end.replace(tzinfo=None) + timedelta(days=1)
        outside = sum(1 for a in alerts if not (low <= a.event_timestamp.replace(tzinfo=None) <= high))
        return outside * 2 > len(alerts)
