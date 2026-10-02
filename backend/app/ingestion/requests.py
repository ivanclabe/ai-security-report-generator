"""Builds the HTTP requests sent to the data source.

The shape of each request mirrors the source's own export URLs, e.g.

    <base>/detallado_alarmas.php?desde=2026-08-01T00:00&hasta=2026-09-01T00:00
        &cliente=THOMAS TGS-TPS&analista=&q=&limite=1000&export=csv
    <base>/indicadores.php?cliente=THOMAS TGS-TPS&fecha_inicio=2026-08-01&fecha_fin=2026-09-01

(both for the period 2026-08-01 .. 2026-08-31, see "Period boundaries" below).

`cliente` always comes from the company registry (Company.request_client_name),
never from free text. Query values are passed as params and percent-encoded by
httpx, so a name such as "THOMAS TGS GREG & SON" cannot break out of its value.

Period boundaries (verified against the live source, see INGESTION_ARCHITECTURE.md §8):
* the alarms export filters on the alarm's *creation* time with minute precision and
  an inclusive `hasta` (created <= hasta): an end of 23:59:59 is sent as 00:00 of the
  next day, otherwise alarms created during the last minute of the period are lost;
* the indicators page treats `fecha_fin` as *exclusive* (midnight): an inclusive end
  date is sent as the next day, otherwise the whole last day is missing from its totals.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.ingestion.config import SourceConfig

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


def _ceil_to_minute(value: datetime) -> datetime:
    if value.second or value.microsecond:
        return value.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return value


@dataclass(frozen=True)
class SourceRequest:
    url: str
    params: dict[str, str] = field(default_factory=dict)
    label: str = "request"


def build_alarms_request(config: SourceConfig, client_name: str, start: datetime, end: datetime) -> SourceRequest:
    return SourceRequest(
        url=config.url_for(config.alarms_path),
        params={
            "desde": start.strftime(_DATETIME_FORMAT),
            "hasta": _ceil_to_minute(end).strftime(_DATETIME_FORMAT),
            "cliente": client_name,
            "analista": "",
            "q": "",
            "limite": str(config.alarms_limit),
            "export": "csv",
        },
        label="alarmas",
    )


def build_indicators_request(config: SourceConfig, client_name: str, start: date, end: date) -> SourceRequest:
    """`end` is inclusive; the page's fecha_fin is not, so the next day is sent."""
    return SourceRequest(
        url=config.url_for(config.indicators_path),
        params={
            "cliente": client_name,
            "fecha_inicio": start.isoformat(),
            "fecha_fin": (end + timedelta(days=1)).isoformat(),
        },
        label="indicadores",
    )
