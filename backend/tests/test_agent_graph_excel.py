"""End-to-end agent run against the real THOMAS TGS-TPS Excel export (LLM stubbed).

Distinct from test_agent_graph.py (which runs against MockDataProvider/ACME) --
this is the regression that proves the full pipeline (understand -> collect ->
analyze -> narrative -> assemble -> validate -> docx) works against the real
client data shape, including evidence validation against real alarm_numbers.
"""
from pathlib import Path

import pytest

from app.agents.state import ReportRequestUpdate
from app.schemas.report_spec import EvidenceRef, KeyFinding
from app.services.report.narrative import ReportNarrative


class _FakeStructuredRunnable:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response() if callable(self._response) else self._response


class _FakeChatModel:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredRunnable(self._response)


def _make_narrative(recommendations: list[KeyFinding] | None = None) -> ReportNarrative:
    return ReportNarrative(
        objective="Evaluar la postura de seguridad de julio 2026.",
        inventory_summary="Inventario estable.",
        siem_summary="Actividad SIEM normal.",
        network_summary="Actividad de red normal.",
        email_summary="Actividad de correo normal.",
        threat_intel_summary="Sin actividad destacada.",
        compromise_indicators_summary="Sin indicadores destacados.",
        highlighted_activities=["Sin novedades destacadas."],
        recommendations=recommendations if recommendations is not None else [KeyFinding(statement="Revisar monitoreo de conectividad de agentes.")],
    )


@pytest.fixture(autouse=True)
def use_excel_provider(monkeypatch, isolated_settings):
    monkeypatch.setenv("DATA_PROVIDER", "excel")
    from app.config.settings import get_settings
    from app.providers.factory import get_data_provider

    get_settings.cache_clear()
    get_data_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_data_provider.cache_clear()


@pytest.fixture
async def compiled_graph(isolated_settings):
    from app.agents.graph import get_compiled_graph

    graph, ctx = await get_compiled_graph(str(isolated_settings.sqlite_checkpoint_db_path))
    yield graph
    await ctx.__aexit__(None, None, None)


async def test_new_report_flow_against_real_excel_data(compiled_graph, monkeypatch, excel_provider):
    real_alert = excel_provider._alerts[0]  # a real alarm_number to cite as evidence

    understand_response = ReportRequestUpdate(
        intent="new_report",
        company="THOMAS TGS-TPS",
        start_date="2026-07-01",
        end_date="2026-07-31",
    )
    narrative = _make_narrative(
        recommendations=[
            KeyFinding(
                statement="Reforzar el monitoreo de agentes desconectados.",
                evidence=EvidenceRef(source_alarm_numbers=[real_alert.alarm_number], metric="1 alarma"),
            )
        ]
    )

    monkeypatch.setattr(
        "app.agents.nodes.understand_request.get_chat_model", lambda: _FakeChatModel(understand_response)
    )
    monkeypatch.setattr(
        "app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(narrative)
    )

    config = {"configurable": {"thread_id": "conv-excel-1"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-excel-1", "user_request": "Genera un informe de seguridad de THOMAS TGS-TPS para julio 2026."},
        config=config,
    )

    assert final["status"] == "ready", final.get("errors")
    assert final["company"] == "THOMAS TGS-TPS"
    assert Path(final["report_file_path"]).exists()
    assert final["report_file_path"].endswith(".docx")
    assert final["collected_data"]["metrics"]["total_alerts"] == 169

    spec = final["report_specification"]
    assert len(spec["sections"]) == 8  # 3,4,5,6,7,8,9,10
    # 6.1 (email rarity) should be populated with real data from the client's file
    email_section = next(s for s in spec["sections"] if s["number"] == "6")
    sub_61 = next(s for s in email_section["subsections"] if s["number"] == "6.1")
    assert sub_61["available"] is True
    assert sub_61["table"]["rows"][0][0] == "cristian.bermudez@thomasgreg.com"
    # 7.2 (vulnerabilities) has no data source -- must say so, not be silently dropped
    threat_section = next(s for s in spec["sections"] if s["number"] == "7")
    sub_72 = next(s for s in threat_section["subsections"] if s["number"] == "7.2")
    assert sub_72["available"] is False
    assert sub_72["unavailable_reason"]


async def test_fabricated_evidence_is_rejected(compiled_graph, monkeypatch):
    understand_response = ReportRequestUpdate(
        intent="new_report", company="THOMAS TGS-TPS", start_date="2026-07-01", end_date="2026-07-31"
    )
    narrative_with_fake_citation = _make_narrative(
        recommendations=[
            KeyFinding(statement="Suspicious spike", evidence=EvidenceRef(source_alarm_numbers=["ALARMA-QUE-NO-EXISTE"]))
        ]
    )

    monkeypatch.setattr(
        "app.agents.nodes.understand_request.get_chat_model", lambda: _FakeChatModel(understand_response)
    )
    monkeypatch.setattr(
        "app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(narrative_with_fake_citation)
    )

    config = {"configurable": {"thread_id": "conv-excel-2"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-excel-2", "user_request": "Genera un informe de THOMAS TGS-TPS para julio 2026."},
        config=config,
    )

    assert final["status"] == "error"
    assert any("ALARMA-QUE-NO-EXISTE" in e for e in final["errors"])
