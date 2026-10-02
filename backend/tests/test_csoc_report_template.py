"""The CSOC monthly template (client reference: "Informe de Gestión CSOC").

Acceptance: the July 2026 export fixture is the same period as the client's
reference report, so the deterministic facts must reproduce its figures. Only
counts are asserted here -- no addresses or mailboxes from the fixture.
"""
from datetime import date

import pytest

from app.document.font_embedding import _obfuscate, embed_font
from app.schemas.report_spec import (
    AlertBoxBlock,
    ChartBlock,
    ChartSeries,
    EvidenceRef,
    KeyFinding,
    NoticeBlock,
    TableBlock,
)
from app.services.report import collection
from app.services.report import csoc_facts as f
from app.services.report.request import ReportRequest
from app.services.report.validation import ground_recommendations, validate_layout

JULY = ReportRequest(company="THOMAS TGS TPS", start_date="2026-07-01", end_date="2026-07-31")


@pytest.fixture
async def july(http_provider):
    result = await collection.collect(JULY, provider=http_provider)
    return result.data


@pytest.fixture
def facts(july):
    return f.build_facts(july["alerts"], july["history_3mo"], date(2026, 7, 1), date(2026, 7, 31))


async def test_totals_match_the_reference_report(facts):
    assert (facts["total_alarms"], facts["effective_alarms"], facts["voided_alarms"]) == (169, 166, 3)
    assert facts["alarms_by_service"] == {
        f.SIEM: 27, f.RED: 125, f.CORREO: 11, f.INTEL: 2, f.ZABBIX: 1, f.ANULADAS: 3,
    }
    assert (facts["answered"], facts["unanswered"]) == (150, 19)
    assert facts["risk_distribution"] == {"Critico": 19, "Alto": 59, "Medio": 36, "Bajo": 52}
    assert facts["period"] == "julio de 2026"


async def test_per_service_breakdowns_match_the_reference_report(july):
    alerts = july["alerts"]
    assert [n for _, n, _ in f.categories_of(f.of_service(alerts, f.SIEM))] == [15, 6, 4, 2]
    assert [n for _, n, _ in f.categories_of(f.of_service(alerts, f.RED))][:6] == [23, 19, 16, 13, 9, 8]
    assert f.categories_of(f.of_service(alerts, f.INTEL)) == [
        ("Adquisición de infraestructura", 1, "Critico"), ("Manipulación de cuentas", 1, "Medio"),
    ]
    assert [n for _, n in f.top_ips(alerts, "source_ips")] == [15, 14, 14, 8, 5]
    assert len(f.top_leak_senders(alerts)) == 3
    assert len(f.disconnected_agents(alerts)) == 7


async def test_months_without_source_records_are_not_reported_as_zero(july, facts):
    months = july["history_3mo"]["months"]
    assert [m["month"] for m in months] == ["2026-05", "2026-06", "2026-07"]
    assert [f.has_records(m) for m in months] == [False, False, True]
    assert facts["monthly_effective"] == [("2026-07", 166)]


async def test_sections_carry_notices_where_the_data_has_no_evidence(july):
    from app.services.report.templates import build_csoc_mensual_sections
    from tests.conftest import _make_test_narrative

    sections = build_csoc_mensual_sections(july, _make_test_narrative())
    assert [s.number for s in sections] == ["3", "4", "5", "6", "7", "8", "9", "10"]

    inventory = sections[0]
    table = next(b for b in inventory.subsections[0].blocks if isinstance(b, TableBlock))
    assert all(row[1].text == "N/D" and row[2].text == "N/D" for row in table.rows)
    assert any(isinstance(b, NoticeBlock) and "May y Jun" in b.text for b in inventory.subsections[0].blocks)
    chart = next(b for b in inventory.subsections[0].blocks if isinstance(b, ChartBlock))
    assert chart.categories == ["Jul"] and chart.series[0].values == [166]

    threat_intel = next(s for s in sections if s.number == "7")
    brand, vulnerabilities = threat_intel.subsections[0], threat_intel.subsections[1]
    for sub in (brand, vulnerabilities):
        assert [type(b) for b in sub.blocks] == [NoticeBlock]
        assert sub.blocks[0].text.startswith("No se encontró evidencia suficiente en las fuentes de datos disponibles")

    known = {a["alarm_number"] for a in july["alerts"]}
    boxes = [b for s in sections for sub in s.subsections for b in sub.blocks if isinstance(b, AlertBoxBlock)]
    assert boxes and all(b.alarm_number in known for b in boxes)


def test_recommendations_with_unsupported_figures_or_alarms_are_dropped():
    allowed = {"166", "19"}
    known = {"ALARMA TGS TPS 3636"}
    supported = KeyFinding(statement="Se procesaron 166 alarmas; 19 sin respuesta.",
                           evidence=EvidenceRef(source_alarm_numbers=["ALARMA TGS TPS 3636"]))
    invented_figure = KeyFinding(statement="Se identificaron 12.800 vulnerabilidades críticas.")
    invented_alarm = KeyFinding(statement="Revisar la alarma.",
                                evidence=EvidenceRef(source_alarm_numbers=["ALARMA-QUE-NO-EXISTE"]))

    kept, notes = ground_recommendations([supported, invented_figure, invented_alarm], allowed, known)

    assert kept == [supported]
    assert len(notes) == 2
    assert "12.800" in notes[0] and "ALARMA-QUE-NO-EXISTE" in notes[1]


def test_layout_validation_rejects_inconsistent_charts_and_tables():
    from app.schemas.report_spec import Cell, ReportSpecification, Section

    spec = ReportSpecification.model_construct(
        sections=[Section(number="3", title="X", blocks=[
            ChartBlock(chart="bar", title="t", categories=["a", "b"], series=[ChartSeries(name="s", values=[1], color="000000")]),
            ChartBlock(chart="bar", title="t", categories=["a"], series=[ChartSeries(name="s", values=[-1], color="000000")]),
            TableBlock(header_rows=[[Cell(text="A"), Cell(text="B")]], rows=[[Cell(text="1")]]),
        ])],
    )

    errors = validate_layout(spec)

    assert len(errors) == 3


def test_font_obfuscation_is_reversible_and_embeds_a_font_part(tmp_path):
    import uuid

    from docx import Document

    guid = uuid.uuid4()
    data = bytes(range(64)) * 4
    assert _obfuscate(_obfuscate(data, guid), guid) == data
    assert _obfuscate(data, guid)[32:] == data[32:]

    document = Document()
    embed_font(document, "Poppins", {"bold": "Poppins-Bold.ttf"})
    path = tmp_path / "embedded.docx"
    document.save(path)

    import zipfile

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        settings = archive.read("word/settings.xml").decode()
        font_table = archive.read("word/fontTable.xml").decode()
    assert any(n.startswith("word/fonts/") and n.endswith(".odttf") for n in names)
    assert "embedTrueTypeFonts" in settings
    assert "embedBold" in font_table and "Poppins" in font_table
