"""Builds the HTTP requests sent to the data source.

The shape of each request mirrors the source's own export URLs, e.g.

    <base>/detallado_alarmas.php?desde=2026-08-01T00:00&hasta=2026-08-31T23:59
        &cliente=THOMAS TGS TPS&analista=&q=&limite=1000&export=csv
    <base>/indicadores.php?cliente=THOMAS TGS TPS&fecha_inicio=2026-08-01&fecha_fin=2026-08-31

`cliente` always comes from the company registry (Company.request_client_name),
never from free text. Query values are passed as params and percent-encoded by
httpx, so a name such as "THOMAS TGS GREG & SON" cannot break out of its value.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from app.ingestion.config import SourceConfig

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


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
            "hasta": end.strftime(_DATETIME_FORMAT),
            "cliente": client_name,
            "analista": "",
            "q": "",
            "limite": str(config.alarms_limit),
            "export": "csv",
        },
        label="alarmas",
    )


def build_indicators_request(config: SourceConfig, client_name: str, start: date, end: date) -> SourceRequest:
    return SourceRequest(
        url=config.url_for(config.indicators_path),
        params={
            "cliente": client_name,
            "fecha_inicio": start.isoformat(),
            "fecha_fin": end.isoformat(),
        },
        label="indicadores",
    )
