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


def _make_narrative(objective: str = "Assess August security posture.") -> ReportNarrative:
    return ReportNarrative(
        objective=objective,
        inventory_summary="Inventory is stable.",
        siem_summary="SIEM activity was normal.",
        network_summary="Network antigen activity was normal.",
        email_summary="Email antigen activity was normal.",
        threat_intel_summary="No notable threat intel activity.",
        compromise_indicators_summary="No notable compromise indicators.",
        highlighted_activities=["Nothing notable this period."],
        recommendations=[KeyFinding(statement="Enforce MFA", evidence=EvidenceRef(source_alarm_numbers=[]))],
    )


@pytest.fixture
async def compiled_graph(isolated_settings):
    from app.agents.graph import get_compiled_graph

    graph, ctx = await get_compiled_graph(str(isolated_settings.sqlite_checkpoint_db_path))
    yield graph
    await ctx.__aexit__(None, None, None)


async def test_new_report_flow_completes_and_writes_docx(compiled_graph, monkeypatch):
    understand_response = ReportRequestUpdate(
        intent="new_report",
        company="ACME Corp",
        start_date="2025-08-01",
        end_date="2025-08-31",
        missing_info_question=None,
    )

    monkeypatch.setattr(
        "app.agents.nodes.understand_request.get_chat_model", lambda: _FakeChatModel(understand_response)
    )
    monkeypatch.setattr(
        "app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(_make_narrative())
    )

    config = {"configurable": {"thread_id": "conv-1"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-1", "user_request": "Generate a security report for ACME Corp for August 2025."},
        config=config,
    )

    assert final["status"] == "ready", final.get("errors")
    assert final["company_id"] == "acme-corp"
    assert Path(final["report_file_path"]).exists()
    assert final["report_file_path"].endswith(".docx")
    assert len(final["report_specification"]["sections"]) > 0


async def test_missing_info_pauses_for_clarification(compiled_graph, monkeypatch):
    understand_response = ReportRequestUpdate(
        intent="new_report",
        company="ACME Corp",
        missing_info_question="What period would you like to analyze?",
    )
    monkeypatch.setattr(
        "app.agents.nodes.understand_request.get_chat_model", lambda: _FakeChatModel(understand_response)
    )

    config = {"configurable": {"thread_id": "conv-2"}}
    final = await compiled_graph.ainvoke(
        {"conversation_id": "conv-2", "user_request": "Generate a security report for ACME."}, config=config
    )

    assert final["status"] == "awaiting_user_input"
    assert "period" in final["assistant_message"].lower()
    assert final.get("report_file_path") is None


async def test_modification_reuses_data_when_only_narrative_changes(monkeypatch):
    collect_calls = {"count": 0}
    from app.agents.nodes import collect_data as collect_data_module

    original_collect = collect_data_module.collect_data

    async def counting_collect_data(state):
        collect_calls["count"] += 1
        return await original_collect(state)

    monkeypatch.setattr("app.agents.graph.collect_data", counting_collect_data)

    responses = iter(
        [
            ReportRequestUpdate(intent="new_report", company="ACME Corp", start_date="2025-08-01", end_date="2025-08-31"),
            ReportRequestUpdate(intent="modify_report", audience="executive"),
        ]
    )
    narrative_responses = iter([_make_narrative("First pass objective."), _make_narrative("Executive-focused objective.")])

    monkeypatch.setattr(
        "app.agents.nodes.understand_request.get_chat_model",
        lambda: _FakeChatModel(lambda: next(responses)),
    )
    monkeypatch.setattr(
        "app.services.report.narrative.get_chat_model",
        lambda: _FakeChatModel(lambda: next(narrative_responses)),
    )

    from langgraph.checkpoint.memory import MemorySaver

    from app.agents.graph import build_graph

    graph = build_graph().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "conv-3"}}

    first = await graph.ainvoke(
        {"conversation_id": "conv-3", "user_request": "Generate a security report for ACME Corp for August 2025."},
        config=config,
    )
    assert first["status"] == "ready", first.get("errors")
    assert collect_calls["count"] == 1

    second = await graph.ainvoke(
        {"conversation_id": "conv-3", "user_request": "Make it executive."}, config=config
    )
    assert second["status"] == "ready", second.get("errors")
    # the narrative was regenerated (both scripted narratives consumed) without re-collecting data;
    # the objective itself is now the template's fixed text, not LLM prose
    assert next(narrative_responses, None) is None
    assert collect_calls["count"] == 1
