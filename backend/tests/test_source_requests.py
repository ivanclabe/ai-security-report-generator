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
        "hasta": "2026-09-01T00:00",  # end of period 23:59:59 -> next minute boundary
        "cliente": "THOMAS TGS-TPS",
        "analista": "",
        "q": "",
        "limite": "1000",
        "export": "csv",
    }
    assert str(httpx.URL(request.url, params=request.params)) == (
        "https://192.168.80.50/detallado_alarmas.php?desde=2026-08-01T00%3A00&hasta=2026-09-01T00%3A00"
        "&cliente=THOMAS+TGS-TPS&analista=&q=&limite=1000&export=csv"
    )


def test_indicators_request_matches_the_sources_url():
    request = build_indicators_request(make_config(), "THOMAS TGS-TPS", date(2026, 8, 1), date(2026, 9, 4))
    assert request.url == "https://source.test/indicadores.php"
    assert request.params == {"cliente": "THOMAS TGS-TPS", "fecha_inicio": "2026-08-01", "fecha_fin": "2026-09-05"}


def test_alarms_end_never_drops_the_last_minute_of_the_period():
    # The export compares creation time (to the second) with `hasta` (to the minute):
    # hasta=23:59 would leave out alarms created at 23:59:xx, so the end is rounded up.
    config = make_config()
    end_of_day = build_alarms_request(config, "BAC", datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59, 999999))
    assert end_of_day.params["hasta"] == "2026-09-01T00:00"
    mid_minute = build_alarms_request(config, "BAC", datetime(2026, 8, 1), datetime(2026, 8, 31, 22, 47, 29))
    assert mid_minute.params["hasta"] == "2026-08-31T22:48"
    exact_minute = build_alarms_request(config, "BAC", datetime(2026, 8, 1), datetime(2026, 8, 31, 22, 47))
    assert exact_minute.params["hasta"] == "2026-08-31T22:47"


def test_indicators_end_date_is_sent_exclusive_so_the_last_day_is_counted():
    # The dashboard treats fecha_fin as midnight (exclusive): a month ending on the 31st
    # must be requested with fecha_fin = the 1st of the next month.
    request = build_indicators_request(make_config(), "BAC", date(2026, 8, 1), date(2026, 8, 31))
    assert request.params["fecha_fin"] == "2026-09-01"
    december = build_indicators_request(make_config(), "BAC", date(2026, 12, 1), date(2026, 12, 31))
    assert december.params["fecha_fin"] == "2027-01-01"


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
