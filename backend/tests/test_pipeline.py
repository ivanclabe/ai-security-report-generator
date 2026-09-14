"""run_deterministic is the Modalidad 1 entry point into the same services
the conversational graph uses -- these tests exercise it directly, with no
LangGraph involved, mirroring test_agent_graph.py's LLM-stubbing pattern."""
from pathlib import Path

from app.schemas.report_spec import EvidenceRef, KeyFinding
from app.services.report.pipeline import run_deterministic, validate_request
from app.services.report.request import ReportRequest


class _FakeStructuredRunnable:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeChatModel:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredRunnable(self._response)


def _make_narrative():
    from app.services.report.narrative import ReportNarrative

    return ReportNarrative(
        objective="Evaluar la postura de seguridad.",
        inventory_summary="Inventario estable.",
        siem_summary="Actividad normal.",
        network_summary="Actividad normal.",
        email_summary="Actividad normal.",
        threat_intel_summary="Sin novedades.",
        compromise_indicators_summary="Sin novedades.",
        highlighted_activities=["Sin novedades."],
        recommendations=[KeyFinding(statement="Reforzar monitoreo.", evidence=EvidenceRef(source_alarm_numbers=[]))],
    )


def test_validate_request_flags_start_after_end():
    request = ReportRequest(company="ACME", start_date="2026-02-01", end_date="2026-01-01")
    errors = validate_request(request)
    assert any("fecha inicial" in e.lower() for e in errors)


def test_validate_request_flags_unknown_report_type():
    request = ReportRequest(company="ACME", start_date="2026-01-01", end_date="2026-01-31", report_type="no_existe")
    errors = validate_request(request)
    assert any("Unknown report template" in e for e in errors)


def test_validate_request_flags_unsupported_format():
    request = ReportRequest(company="ACME", start_date="2026-01-01", end_date="2026-01-31", format="xlsx")
    errors = validate_request(request)
    assert any("xlsx" in e.lower() for e in errors)


def test_validate_request_accepts_pdf_format():
    request = ReportRequest(company="ACME", start_date="2026-01-01", end_date="2026-01-31", format="pdf")
    assert validate_request(request) == []


def test_validate_request_accepts_well_formed_request():
    request = ReportRequest(company="ACME", start_date="2026-01-01", end_date="2026-01-31")
    assert validate_request(request) == []


async def test_run_deterministic_end_to_end(monkeypatch, isolated_settings):
    monkeypatch.setattr("app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(_make_narrative()))

    request = ReportRequest(company="ACME Corp", start_date="2025-08-01", end_date="2025-08-31")
    events = [event async for event in run_deterministic(request, conversation_id="det-1")]

    progress_nodes = [e["node"] for e in events if e["event"] == "progress"]
    assert progress_nodes == ["collect_data", "analyze_data", "generate_report_specification", "validate_report_specification", "generate_document"]

    result = events[-1]
    assert result["event"] == "result"
    assert result["status"] == "ready"
    assert result["company"].id == "acme-corp"
    assert Path(result["document_path"]).exists()
    assert len(result["specification"].sections) > 0


async def test_run_deterministic_unknown_company_yields_error(isolated_settings):
    request = ReportRequest(company="Empresa Que No Existe", start_date="2025-08-01", end_date="2025-08-31")
    events = [event async for event in run_deterministic(request, conversation_id="det-2")]

    assert events[-1]["event"] == "result"
    assert events[-1]["status"] == "error"
    assert any("Empresa Que No Existe" in e for e in events[-1]["errors"])


async def test_run_deterministic_param_errors_short_circuit_before_any_io(isolated_settings):
    request = ReportRequest(company="ACME", start_date="not-a-date", end_date="2025-08-31")
    events = [event async for event in run_deterministic(request, conversation_id="det-3")]

    assert len(events) == 1  # straight to the error result, no progress events emitted
    assert events[0]["status"] == "error"
