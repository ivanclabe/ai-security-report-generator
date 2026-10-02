"""End-to-end agent run on data delivered by the remote source (LLM stubbed).

The regression that proves the whole chain -- company registry -> acquisition
(HTTP/CSV) -> normalization -> provider -> collect -> analyze -> narrative ->
validation -> docx -- hands the agent correct, company-scoped data, and that
the agent never needs to know where the data came from.
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


def _make_narrative(recommendations: list[KeyFinding]) -> ReportNarrative:
    return ReportNarrative(
        objective="Evaluar la postura de seguridad de julio 2026.",
        inventory_summary="Inventario estable.",
        siem_summary="Actividad SIEM normal.",
        network_summary="Actividad de red normal.",
        email_summary="Actividad de correo normal.",
        threat_intel_summary="Sin actividad destacada.",
        compromise_indicators_summary="Sin indicadores destacados.",
        highlighted_activities=["Sin novedades destacadas."],
        recommendations=recommendations,
    )


@pytest.fixture(autouse=True)
def agent_uses_the_http_source(monkeypatch, http_provider):
    """Route the agent's and the pipeline's get_data_provider() to the HTTP provider
    backed by the in-memory source -- the same objects the real factory builds."""
    monkeypatch.setattr("app.services.report.collection.get_data_provider", lambda: http_provider)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: http_provider)


@pytest.fixture
async def compiled_graph(isolated_settings):
    from app.agents.graph import get_compiled_graph

    graph, ctx = await get_compiled_graph(str(isolated_settings.sqlite_checkpoint_db_path))
    yield graph
    await ctx.__aexit__(None, None, None)


def _stub_llm(monkeypatch, understand, narrative):
    monkeypatch.setattr("app.agents.nodes.understand_request.get_chat_model", lambda: _FakeChatModel(understand))
    monkeypatch.setattr("app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(narrative))


async def test_new_report_flow_delivers_the_sources_data_to_the_agent(
    compiled_graph, monkeypatch, http_provider, source_server
):
    company = await http_provider.get_company(name="THOMAS TGS TPS")
    from datetime import datetime, timezone

    real_alert = (
        await http_provider.get_security_alerts(
            company.id, datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
        )
    )[0]
    source_server.requests.clear()
    http_provider._acquisition._batches.clear()  # start the report from a cold cache

    _stub_llm(
        monkeypatch,
        ReportRequestUpdate(
            intent="new_report",
            company="THOMAS TGS-TPS",  # however the user (or the old export) spells it
            start_date="2026-07-01",
            end_date="2026-07-31",
        ),
        _make_narrative(
            [
                KeyFinding(
                    statement="Reforzar el monitoreo de agentes desconectados.",
                    evidence=EvidenceRef(source_alarm_numbers=[real_alert.alarm_number], metric="1 alarma"),
                )
            ]
        ),
    )

    config = {"configurable": {"thread_id": "conv-http-1"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-http-1", "user_request": "Genera un informe de seguridad de THOMAS TGS-TPS para julio 2026."},
        config=config,
    )

    assert final["status"] == "ready", final.get("errors")
    # the agent works with the registry's official name and id
    assert final["company"] == "THOMAS TGS TPS" and final["company_id"] == "thomas-tgs-tps"
    # ...over the data the source delivered, already normalized and scoped to the company
    assert final["collected_data"]["metrics"]["total_alerts"] == 169
    assert final["collected_data"]["metrics"]["critico_alerts"] == 19
    assert {a["client"] for a in final["collected_data"]["alerts"]} == {"THOMAS TGS TPS"}
    # only the two periods the report needs (the month, and the 3-month trend window) were requested
    assert len(source_server.alarm_requests) == 2
    assert {r.url.params["cliente"] for r in source_server.alarm_requests} == {"THOMAS TGS-TPS"}

    assert Path(final["report_file_path"]).exists() and final["report_file_path"].endswith(".docx")
    spec = final["report_specification"]
    assert spec["company"] == "THOMAS TGS TPS" and spec["company_logo"] == "Thomas TPS"
    assert len(spec["sections"]) == 8  # 3,4,5,6,7,8,9,10
    # 6.1 (email rarity) depended on a pivot sheet the alarms export does not carry:
    # the report must say so instead of dropping the section or inventing a ranking
    email_section = next(s for s in spec["sections"] if s["number"] == "6")
    sub_61 = next(s for s in email_section["subsections"] if s["number"] == "6.1")
    assert sub_61["available"] is False and sub_61["unavailable_reason"]
    # 7.2 (vulnerabilities) has no data source either
    threat_section = next(s for s in spec["sections"] if s["number"] == "7")
    sub_72 = next(s for s in threat_section["subsections"] if s["number"] == "7.2")
    assert sub_72["available"] is False and sub_72["unavailable_reason"]


async def test_fabricated_evidence_is_rejected(compiled_graph, monkeypatch):
    _stub_llm(
        monkeypatch,
        ReportRequestUpdate(intent="new_report", company="THOMAS TGS TPS", start_date="2026-07-01", end_date="2026-07-31"),
        _make_narrative(
            [KeyFinding(statement="Pico sospechoso", evidence=EvidenceRef(source_alarm_numbers=["ALARMA-QUE-NO-EXISTE"]))]
        ),
    )

    config = {"configurable": {"thread_id": "conv-http-2"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-http-2", "user_request": "Genera un informe de THOMAS TGS TPS para julio 2026."},
        config=config,
    )

    assert final["status"] == "error"
    assert any("ALARMA-QUE-NO-EXISTE" in e for e in final["errors"])


async def test_an_ambiguous_company_asks_the_user_instead_of_guessing(compiled_graph, monkeypatch, source_server):
    _stub_llm(
        monkeypatch,
        ReportRequestUpdate(intent="new_report", company="peru", start_date="2026-07-01", end_date="2026-07-31"),
        _make_narrative([KeyFinding(statement="n/a")]),
    )

    config = {"configurable": {"thread_id": "conv-http-3"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-http-3", "user_request": "Genera un informe de peru para julio 2026."}, config=config
    )

    assert final["status"] == "awaiting_user_input"
    question = final["assistant_message"]
    assert "PERU SSS" in question and "THOMAS TGS PERU" in question
    assert source_server.requests == []  # nothing was asked of the source for an unidentified company


async def test_source_failures_reach_the_user_as_a_readable_error(compiled_graph, monkeypatch, source_server):
    source_server.password = "changed-by-admin"  # the source now rejects the configured credentials
    _stub_llm(
        monkeypatch,
        ReportRequestUpdate(intent="new_report", company="THOMAS TGS TPS", start_date="2026-07-01", end_date="2026-07-31"),
        _make_narrative([KeyFinding(statement="n/a")]),
    )

    config = {"configurable": {"thread_id": "conv-http-4"}}
    with pytest.raises(Exception) as excinfo:  # the graph surfaces it; ConversationService turns it into a chat message
        await compiled_graph.ainvoke(
            {"conversation_id": "conv-http-4", "user_request": "Genera un informe de THOMAS TGS TPS para julio 2026."},
            config=config,
        )
    from app.ingestion.errors import SourceAuthenticationError

    assert isinstance(excinfo.value, SourceAuthenticationError)
    assert "SOURCE_PASSWORD" in str(excinfo.value)
