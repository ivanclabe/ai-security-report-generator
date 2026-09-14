"""answer_question is the one node with real (bounded) tool-calling in this
agent -- these tests exercise the tool-call loop and, crucially, the citation
check that rejects any alarm_number the model claims but that no tool call
actually returned this turn (see AGENT_ARCHITECTURE.md)."""
from langchain_core.messages import AIMessage

from app.agents.nodes.answer_question import AnswerWithEvidence, _make_tools, answer_question


class _FakeStructuredRunnable:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeToolCallingModel:
    """Stands in for get_chat_model(): the node calls .bind_tools(...) for the
    tool-calling rounds and a fresh .with_structured_output(...) for the final
    citation-checked answer -- both need to be served by this one fake."""

    def __init__(self, ai_responses: list[AIMessage], final_answer: AnswerWithEvidence):
        self._ai_responses = ai_responses
        self._final_answer = final_answer
        self._idx = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        response = self._ai_responses[self._idx]
        self._idx += 1
        return response

    def with_structured_output(self, schema):
        return _FakeStructuredRunnable(self._final_answer)


def _base_state(**overrides) -> dict:
    state = {
        "company_id": "acme-corp",
        "company": "ACME Corp",
        "start_date": "2020-01-01",
        "end_date": "2030-01-01",
        "user_request": "pregunta de prueba",
    }
    state.update(overrides)
    return state


async def test_answers_using_a_verified_alarm_lookup(monkeypatch, mock_provider):
    real_alert = mock_provider._alerts[0]

    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "consultar_alarma",
                "args": {"alarm_number": real_alert.alarm_number},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    no_more_tools_msg = AIMessage(content="Ya tengo lo que necesito.", tool_calls=[])
    final_answer = AnswerWithEvidence(
        answer=f"La alarma {real_alert.alarm_number} corresponde a {real_alert.description}.",
        cited_alarm_numbers=[real_alert.alarm_number],
    )

    model = _FakeToolCallingModel([tool_call_msg, no_more_tools_msg], final_answer)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_chat_model", lambda: model)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: mock_provider)

    result = await answer_question(_base_state(user_request=f"Cuéntame sobre {real_alert.alarm_number}"))

    assert result["status"] == "answered"
    assert real_alert.alarm_number in result["assistant_message"]


async def test_rejects_answer_citing_an_alarm_never_actually_fetched(monkeypatch, mock_provider):
    no_tools_msg = AIMessage(content="No necesito herramientas.", tool_calls=[])
    final_answer = AnswerWithEvidence(
        answer="La alarma FAKE-999 muestra actividad sospechosa.", cited_alarm_numbers=["FAKE-999"]
    )

    model = _FakeToolCallingModel([no_tools_msg], final_answer)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_chat_model", lambda: model)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: mock_provider)

    result = await answer_question(_base_state(user_request="¿Qué pasó con la alarma FAKE-999?"))

    assert result["status"] == "answered"
    assert "FAKE-999" not in result["assistant_message"]
    assert "no pude verificar" in result["assistant_message"].lower()


async def test_answer_with_no_citations_is_accepted_as_is(monkeypatch, mock_provider):
    no_tools_msg = AIMessage(content="", tool_calls=[])
    final_answer = AnswerWithEvidence(
        answer="No encontré alarmas relacionadas con esa pregunta.", cited_alarm_numbers=[]
    )

    model = _FakeToolCallingModel([no_tools_msg], final_answer)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_chat_model", lambda: model)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: mock_provider)

    result = await answer_question(_base_state(user_request="¿Hay algo raro?"))

    assert result == {
        "assistant_message": "No encontré alarmas relacionadas con esa pregunta.",
        "status": "answered",
    }


async def test_trend_analysis_tool_returns_real_data_and_answer_passes_through(monkeypatch, mock_provider):
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "analizar_tendencia", "args": {"risk_level": "Critico"}, "id": "call-1", "type": "tool_call"}],
    )
    no_more_tools_msg = AIMessage(content="Listo.", tool_calls=[])
    final_answer = AnswerWithEvidence(
        answer="Las alarmas críticas se mantuvieron estables durante el período.", cited_alarm_numbers=[]
    )

    model = _FakeToolCallingModel([tool_call_msg, no_more_tools_msg], final_answer)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_chat_model", lambda: model)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: mock_provider)

    result = await answer_question(
        _base_state(user_request="¿Cómo han evolucionado las alarmas críticas?")
    )

    assert result["status"] == "answered"
    assert result["assistant_message"] == final_answer.answer


async def test_tools_report_missing_company_period_instead_of_failing(mock_provider):
    """buscar_alarmas / analizar_tendencia are also reachable before any report has
    been generated in a conversation (company_id/start_date/end_date still None) --
    they must degrade to a clear message, not raise."""
    tools_list, _ = _make_tools(mock_provider, None, None, None)
    by_name = {t.name: t for t in tools_list}

    search_result = await by_name["buscar_alarmas"].ainvoke({})
    trend_result = await by_name["analizar_tendencia"].ainvoke({})

    assert "no hay una empresa" in search_result.lower()
    assert "no hay una empresa" in trend_result.lower()


def test_leaked_tool_syntax_is_stripped_from_the_answer():
    """Regression: observed intermittently in production testing (~1 in 6-8 real
    calls) -- with_structured_output occasionally leaks a malformed
    re-serialization of its own schema onto a long answer's tail."""
    corrupted = (
        'La tendencia fue creciente hasta la semana 30.</answer>\n'
        '<parameter name="cited_alarm_numbers">[]'
    )
    answer = AnswerWithEvidence(answer=corrupted, cited_alarm_numbers=[])
    assert answer.answer == "La tendencia fue creciente hasta la semana 30."


def test_answer_with_no_leak_is_left_untouched():
    answer = AnswerWithEvidence(answer="Respuesta normal, sin nada raro.", cited_alarm_numbers=[])
    assert answer.answer == "Respuesta normal, sin nada raro."


def test_stripping_never_yields_an_empty_answer():
    # If the entire string were somehow just leaked syntax, keep the original
    # rather than showing the user a blank message.
    only_garbage = '</answer>\n<parameter name="cited_alarm_numbers">[]'
    answer = AnswerWithEvidence(answer=only_garbage, cited_alarm_numbers=[])
    assert answer.answer == only_garbage


async def test_tool_call_loop_is_capped(monkeypatch, mock_provider):
    """Even if the model keeps calling tools forever, the loop must stop after
    MAX_TOOL_ITERATIONS -- bounding cost/latency, not just correctness."""
    keeps_calling = AIMessage(
        content="",
        tool_calls=[{"name": "buscar_alarmas", "args": {}, "id": "call-x", "type": "tool_call"}],
    )
    final_answer = AnswerWithEvidence(answer="Respuesta final forzada.", cited_alarm_numbers=[])

    # 3 rounds of "keeps calling" (MAX_TOOL_ITERATIONS) is all ainvoke() should
    # be asked for during the tool-calling phase -- no 4th entry needed.
    model = _FakeToolCallingModel([keeps_calling, keeps_calling, keeps_calling], final_answer)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_chat_model", lambda: model)
    monkeypatch.setattr("app.agents.nodes.answer_question.get_data_provider", lambda: mock_provider)

    result = await answer_question(_base_state())

    assert result["assistant_message"] == "Respuesta final forzada."
    assert model._idx == 3  # never attempted a 4th tool-calling round
