"""Request construction: the exact query the source expects, company names
taken from the registry, and safe encoding."""
from datetime import date, datetime

import httpx

from app.ingestion.requests import build_alarms_request, build_indicators_request
from tests.source_fakes import make_config


def _query(request) -> dict:
    return dict(httpx.URL(request.url, params=request.params).params)


def test_alarms_request_matches_the_sources_export_url():
    config = make_config(base_url="https://192.168.80.50", alarms_limit=1000)
    request = build_alarms_request(
        config, "THOMAS TGS-TPS", datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 31, 23, 59, 59)
    )

    assert request.url == "https://192.168.80.50/detallado_alarmas.php"
    assert request.params == {
        "desde": "2026-08-01T00:00",
        "hasta": "2026-08-31T23:59",
        "cliente": "THOMAS TGS-TPS",
        "analista": "",
        "q": "",
        "limite": "1000",
        "export": "csv",
    }
    assert str(httpx.URL(request.url, params=request.params)) == (
        "https://192.168.80.50/detallado_alarmas.php?desde=2026-08-01T00%3A00&hasta=2026-08-31T23%3A59"
        "&cliente=THOMAS+TGS-TPS&analista=&q=&limite=1000&export=csv"
    )


def test_indicators_request_matches_the_sources_url():
    request = build_indicators_request(make_config(), "THOMAS TGS-TPS", date(2026, 8, 1), date(2026, 9, 4))
    assert request.url == "https://source.test/indicadores.php"
    assert request.params == {"cliente": "THOMAS TGS-TPS", "fecha_inicio": "2026-08-01", "fecha_fin": "2026-09-04"}


def test_company_names_with_special_characters_are_encoded_not_injected():
    request = build_alarms_request(
        make_config(), "THOMAS TGS GREG & SON", datetime(2026, 8, 1), datetime(2026, 8, 31)
    )
    url = str(httpx.URL(request.url, params=request.params))
    assert "cliente=THOMAS+TGS+GREG+%26+SON" in url  # the '&' cannot start a new parameter
    assert _query(request)["cliente"] == "THOMAS TGS GREG & SON"

    nasty = build_alarms_request(make_config(), "X&limite=999999&export=json", datetime(2026, 8, 1), datetime(2026, 8, 2))
    assert _query(nasty)["limite"] == "1000" and _query(nasty)["export"] == "csv"


def test_limit_comes_from_configuration():
    request = build_alarms_request(make_config(alarms_limit=5000), "BAC", datetime(2026, 8, 1), datetime(2026, 8, 2))
    assert request.params["limite"] == "5000"
