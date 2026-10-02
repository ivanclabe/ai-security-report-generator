"""indicadores.php -> SourceIndicators, against a fixture that keeps the live
page's exact markup (synthetic data), plus the edge cases of a web dashboard."""
from datetime import date, datetime

import pytest

from app.ingestion.encoding import decode_source_text
from app.ingestion.errors import SourceFormatError
from app.ingestion.indicators_parser import parse_indicators_page
from tests.conftest import INDICATORS_FIXTURE_PATH
from tests.source_fakes import SOURCE_CLIENT_OPTIONS


@pytest.fixture(scope="module")
def indicators():
    return parse_indicators_page(INDICATORS_FIXTURE_PATH.read_bytes())


def test_summary(indicators):
    assert indicators.client == "THOMAS TGS-TPS"
    assert (indicators.start_date, indicators.end_date) == (date(2026, 8, 1), date(2026, 8, 31))
    assert indicators.total_alarms == 12
    assert indicators.principal_source_ip == "192.0.2.10"
    assert indicators.warnings == []


def test_risk_table_keeps_the_sources_own_bands(indicators):
    assert [(r.level, r.range_label, r.percent) for r in indicators.risk_distribution] == [
        ("Bajo", "0-25", 16.67),
        ("Medio", "26-50", 16.67),
        ("Alto", "51-75", 33.33),
        ("Critico", "76-100", 33.33),
    ]


def test_top_tables(indicators):
    assert [(c.label, c.count) for c in indicators.top_source_ips][:2] == [("192.0.2.10", 5), ("192.0.2.11", 2)]
    assert indicators.top_destination_ips[0].label == "203.0.113.7" and indicators.top_destination_ips[0].count == 5
    assert [(c.label, c.count) for c in indicators.top_hostnames][:2] == [("srv-demo-01", 4), ("pc-demo-02", 2)]
    # descriptions are truncated with CSS on screen; the full text comes from title=
    assert indicators.top_descriptions[0].label == "Transferencia inusual de datos hacia el exterior (sintético)."
    assert indicators.top_descriptions[0].count == 3


def test_inline_script_data(indicators):
    assert len(indicators.records) == 12
    first = indicators.records[0]
    assert first.alert_type == "ANTÍGENO DE RED"
    assert first.timestamp == datetime(2026, 8, 1, 10, 15, 2)
    assert (first.source_ip, first.external_ip, first.hostname) == ("192.0.2.10", "203.0.113.7", "srv-demo-01")
    assert first.severity_score == 37 and first.reported_by == "Analista Demo"
    assert "\r\n" not in first.description
    assert sum(c.count for c in indicators.alarms_by_day) == 12
    assert indicators.alarms_by_day[0].label == "2026-08-01"
    assert [(c.label, c.count) for c in indicators.top_categories][0] == ("Volcado de credenciales", 4)
    assert [(c.label, c.count) for c in indicators.alarms_by_type][0] == ("ANTÍGENO DE RED", 6)


def test_client_list_is_every_value_the_source_accepts(indicators):
    assert indicators.available_clients == SOURCE_CLIENT_OPTIONS


def test_mixed_encoding_bytes_are_decoded_without_breaking_utf8_text():
    page = INDICATORS_FIXTURE_PATH.read_bytes().replace(b"Top 5 Descripciones", b"Top 5 Descripci\xf3nes")
    parsed = parse_indicators_page(page)
    assert parsed.top_descriptions  # heading with a stray Latin-1 byte is still recognized
    assert parsed.records[0].alert_type == "ANTÍGENO DE RED"  # valid UTF-8 untouched
    assert decode_source_text(b"Descripci\xf3n: Ejecuci\xc3\xb3n") == "Descripción: Ejecución"


def test_script_strings_containing_brackets_do_not_cut_the_data():
    # the page embeds DATA as JSON (non-ASCII escaped as \\uXXXX); inject brackets and quotes into one string
    page = INDICATORS_FIXTURE_PATH.read_text(encoding="utf-8")
    original = "Recomendaci\\u00f3n sint\\u00e9tica."
    assert original in page
    page = page.replace(original, 'Texto con ]; y } y \\"comillas\\" adentro.', 1)
    parsed = parse_indicators_page(page.encode("utf-8"))
    assert len(parsed.records) == 12
    assert parsed.records[0].description.endswith('Texto con ]; y } y "comillas" adentro.')


def test_page_without_alarms_reports_zero():
    page = """<html><body><select name="cliente"><option value="BAC" selected>BAC</option></select>
      <input name="fecha_inicio" value="2026-08-01"><input name="fecha_fin" value="2026-08-31">
      <div class="no-data">No hay alarmas para los filtros seleccionados.</div></body></html>"""
    parsed = parse_indicators_page(page.encode())
    assert parsed.total_alarms == 0 and parsed.records == []
    assert parsed.client == "BAC" and parsed.start_date == date(2026, 8, 1)


def test_summary_and_listed_records_disagreeing_is_reported():
    page = INDICATORS_FIXTURE_PATH.read_text(encoding="utf-8").replace("<strong>12</strong>", "<strong>15</strong>")
    parsed = parse_indicators_page(page.encode("utf-8"))
    assert parsed.total_alarms == 15
    assert any("15" in w and "12" in w for w in parsed.warnings)


def test_a_login_page_is_rejected():
    login = b"<html><form action='/login.php' method='post'><input name='usuario'><input type='password' name='clave'></form></html>"
    with pytest.raises(SourceFormatError) as excinfo:
        parse_indicators_page(login)
    assert "inicio de sesión" in str(excinfo.value)


@pytest.mark.parametrize("body", [b"<html><body><h1>Error 500</h1></body></html>", b"{\"ok\": true}", b""])
def test_anything_that_is_not_the_indicators_page_is_rejected(body):
    with pytest.raises(SourceFormatError):
        parse_indicators_page(body)
