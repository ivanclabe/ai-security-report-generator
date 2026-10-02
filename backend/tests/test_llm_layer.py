"""LLM Provider Layer: provider/model selection, AUTO, health checks, fallback,
parameter normalization, persistence, API, audit, observability and the
integration with the report pipeline and LangGraph."""
import httpx
import pytest

from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.llm.errors import LLMProviderError, NoProviderAvailableError, classify_error
from app.llm.layer import LLMProviderLayer, Resolution, Target
from app.llm.types import HealthStatus, LLMParams, LLMSelection, ProviderKind
from app.services import llm_settings_service as llm_settings
from tests.conftest import auth_headers, parse_sse_events
from tests.llm_fakes import ScriptedChatModel


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://llm-server:8000")
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-32B")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("LLM_AUTO_ORDER", "vllm,cloud")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    llm_settings.invalidate_cache()
    yield
    get_settings.cache_clear()


def _layer(**routing) -> LLMProviderLayer:
    from dataclasses import replace

    return LLMProviderLayer(llm_settings.providers_from_env(), replace(llm_settings.routing_from_env(), **routing))


# ---- selection ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider, model, vendor",
    [("cloud", "claude-sonnet-5", "anthropic"), ("vllm", "Qwen/Qwen3-32B", "vllm"), ("local", "llama3.1:8b", "ollama")],
)
async def test_each_provider_can_be_selected_with_its_default_model(provider, model, vendor):
    resolution = await _layer().resolve(LLMSelection(provider))
    assert (resolution.active.provider, resolution.active.model, resolution.active.settings.vendor) == (provider, model, vendor)
    assert resolution.fallbacks == []  # an explicit choice never falls back


async def test_a_specific_model_can_be_selected():
    resolution = await _layer().resolve(LLMSelection("vllm", "meta-llama/Llama-3.3-70B-Instruct"))
    assert resolution.active.model == "meta-llama/Llama-3.3-70B-Instruct"


async def test_a_model_the_provider_does_not_serve_is_rejected_before_running():
    with pytest.raises(LLMProviderError) as excinfo:
        await _layer().resolve(LLMSelection("vllm", "no-existe-7b"))
    assert excinfo.value.status == HealthStatus.MODEL_UNAVAILABLE


async def test_an_unavailable_explicit_provider_is_not_silently_replaced(llm_servers):
    llm_servers.fail("llm-server", "timeout")
    with pytest.raises(LLMProviderError) as excinfo:
        await _layer().resolve(LLMSelection("vllm"))
    assert excinfo.value.status == HealthStatus.TIMEOUT


# ---- AUTO -------------------------------------------------------------------------------------


async def test_auto_uses_the_primary_when_available_and_keeps_the_rest_as_fallback():
    resolution = await _layer().resolve(LLMSelection("auto"))
    assert resolution.active.provider == "vllm"
    assert [t.provider for t in resolution.fallbacks] == ["cloud"]
    assert resolution.attempts == []


async def test_auto_falls_back_when_the_primary_times_out_and_records_why(llm_servers):
    llm_servers.fail("llm-server", "timeout")
    resolution = await _layer().resolve(LLMSelection("auto"))
    assert resolution.active.provider == "cloud"
    assert [(a.provider, a.status) for a in resolution.attempts] == [("vllm", "timeout")]


async def test_auto_order_is_configuration_not_code(llm_servers):
    resolution = await _layer(auto_order=("cloud", "vllm")).resolve(LLMSelection("auto"))
    assert [t.provider for t in resolution.targets] == ["cloud", "vllm"]


async def test_auto_with_nothing_available_fails_clearly(llm_servers):
    llm_servers.fail("llm-server", "connect")
    llm_servers.fail("api.anthropic.com", "500")
    with pytest.raises(NoProviderAvailableError) as excinfo:
        await _layer().resolve(LLMSelection("auto"))
    assert {a.status for a in excinfo.value.attempts} == {"connection_error", "server_error"}


# ---- health checks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure, status",
    [(None, HealthStatus.AVAILABLE), ("401", HealthStatus.AUTH_ERROR), ("timeout", HealthStatus.TIMEOUT),
     ("connect", HealthStatus.CONNECTION_ERROR), ("500", HealthStatus.SERVER_ERROR), ("429", HealthStatus.RATE_LIMITED)],
)
async def test_health_check_reports_each_failure_mode(llm_servers, failure, status):
    if failure:
        llm_servers.fail("llm-server", failure)
    result = await _layer().health("vllm", use_cache=False)
    assert result.status == status
    assert result.latency_ms is not None


async def test_health_of_a_disabled_or_unconfigured_provider(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    result = await _layer().health("vllm", use_cache=False)
    assert result.status == HealthStatus.DISABLED  # no base URL -> slot not enabled


async def test_health_results_are_cached_for_the_configured_ttl(llm_servers):
    layer = _layer(health_ttl_seconds=60)
    await layer.health("vllm")
    await layer.health("vllm")
    assert sum(1 for r in llm_servers.requests if r.url.host == "llm-server" and r.url.path.endswith("/models")) == 1


async def test_model_discovery_per_vendor():
    layer = _layer()
    assert await layer.list_models("vllm") == ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"]
    assert await layer.list_models("local") == ["llama3.1:8b", "mistral:7b"]  # Ollama /api/tags
    assert "claude-sonnet-5" in await layer.list_models("cloud")


def test_errors_are_classified_without_vendor_specific_code():
    request = httpx.Request("GET", "http://x")
    assert classify_error(httpx.ReadTimeout("t", request=request)) == HealthStatus.TIMEOUT
    assert classify_error(httpx.ConnectError("c", request=request)) == HealthStatus.CONNECTION_ERROR

    class AuthenticationError(Exception):
        status_code = 401

    assert classify_error(AuthenticationError()) == HealthStatus.AUTH_ERROR
    assert classify_error(ValueError("schema mismatch")) is None  # not a provider failure


# ---- parameters -------------------------------------------------------------------------------------


def test_parameters_are_normalized_per_provider():
    params = LLMParams(temperature=0.2, top_p=0.9, max_tokens=4000)
    assert AnthropicAdapter().supported(params) == {"temperature": 0.2, "max_tokens": 4000}  # top_p dropped
    assert OpenAICompatibleAdapter().supported(params) == {"temperature": 0.2, "top_p": 0.9, "max_tokens": 4000}
    assert OpenAICompatibleAdapter().supported(LLMParams(max_tokens=None)) == {}


def test_each_adapter_builds_its_client_with_the_endpoint():
    providers = llm_settings.providers_from_env()
    layer = _layer()
    vllm = layer.create_llm(Target("vllm", "Qwen/Qwen3-32B", providers[ProviderKind.VLLM]))
    assert str(vllm.openai_api_base) == "http://llm-server:8000/v1"
    cloud = layer.create_llm(Target("cloud", "claude-sonnet-5", providers[ProviderKind.CLOUD]))
    assert cloud.model == "claude-sonnet-5"


# ---- runtime fallback ------------------------------------------------------------------------------


class _Observer:
    def __init__(self):
        self.calls, self.switches = [], []

    async def on_call(self, target, **kw):
        self.calls.append((target.provider, kw["ok"], kw["status"], kw["usage"]))

    async def on_switch(self, a, b, *, status, detail):
        self.switches.append((a.provider, b.provider, status))


def _scripted(monkeypatch, models: dict):
    monkeypatch.setattr(LLMProviderLayer, "create_llm", lambda self, target: models[target.provider])


async def test_auto_fails_over_at_call_time_and_reports_the_switch(monkeypatch):
    from app.agents.state import ReportRequestUpdate

    update = ReportRequestUpdate(intent="question")
    _scripted(monkeypatch, {
        "vllm": ScriptedChatModel("vllm", fail=httpx.ReadTimeout("t", request=httpx.Request("POST", "http://x"))),
        "cloud": ScriptedChatModel("cloud", {ReportRequestUpdate: update}),
    })
    layer = _layer()
    observer = _Observer()
    model = layer.chat_model(await layer.resolve(LLMSelection("auto")), observer)

    assert await model.with_structured_output(ReportRequestUpdate).ainvoke([]) == update
    assert observer.switches == [("vllm", "cloud", HealthStatus.TIMEOUT)]
    assert [(c[0], c[1]) for c in observer.calls] == [("vllm", False), ("cloud", True)]
    assert observer.calls[1][3] == {"input_tokens": 100, "output_tokens": 20}
    assert model.active.provider == "cloud"  # later calls stay on the fallback


async def test_explicit_selection_never_fails_over(monkeypatch):
    _scripted(monkeypatch, {"vllm": ScriptedChatModel("vllm", fail=httpx.ConnectError("x", request=httpx.Request("POST", "http://x")))})
    layer = _layer()
    model = layer.chat_model(await layer.resolve(LLMSelection("vllm")))
    with pytest.raises(LLMProviderError) as excinfo:
        await model.bind_tools([]).ainvoke([])
    assert excinfo.value.status == HealthStatus.CONNECTION_ERROR


async def test_output_problems_do_not_trigger_a_provider_switch(monkeypatch):
    _scripted(monkeypatch, {"vllm": ScriptedChatModel("vllm", fail=ValueError("bad json")),
                            "cloud": ScriptedChatModel("cloud")})
    layer = _layer()
    model = layer.chat_model(await layer.resolve(LLMSelection("auto")), _Observer())
    with pytest.raises(ValueError):
        await model.bind_tools([]).ainvoke([])


async def test_structured_output_method_is_passed_to_openai_compatible_servers(monkeypatch):
    log: list = []
    _scripted(monkeypatch, {"vllm": ScriptedChatModel("vllm", {str: "x"}, log=log)})
    layer = _layer()
    model = layer.chat_model(Resolution("vllm", [layer._target("vllm", None)]))
    await model.with_structured_output(str).ainvoke([])
    assert log[0][2] == {"method": "json_schema"}


# ---- persistence & API -----------------------------------------------------------------------------------

PROVIDER_BODY = {
    "vendor": "vllm",
    "enabled": True,
    "base_url": "http://llm-server:8000",
    "api_key": "sk-vllm-secreta-1234567890",
    "default_model": "Qwen/Qwen3-32B",
    "manual_models": ["mi-modelo-propio"],
    "discovery_enabled": True,
    "params": {"temperature": 0.1, "max_tokens": 4096, "timeout_seconds": 90},
}


def test_saving_a_provider_encrypts_the_key_and_never_returns_it(api_client, fake_supabase):
    res = api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json=PROVIDER_BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["api_key_set"] is True and body["api_key_hint"] == "7890"
    assert "sk-vllm-secreta" not in res.text
    row = fake_supabase.table("in_llm_providers").rows[0]
    assert "sk-vllm-secreta" not in str(row) and row["api_key_ciphertext"]
    assert row["params"]["temperature"] == 0.1

    listed = api_client.get("/api/llm/providers", headers=auth_headers())
    assert "sk-vllm-secreta" not in listed.text and "ciphertext" not in listed.text

    audit_row = fake_supabase.audit("llm.provider_settings_updated")[0]
    assert audit_row["context"]["api_key_changed"] is True and "sk-vllm" not in str(audit_row)


def test_an_empty_key_keeps_the_stored_one_and_model_changes_are_audited(api_client, fake_supabase):
    api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json=PROVIDER_BODY)
    first = fake_supabase.table("in_llm_providers").rows[0]["api_key_ciphertext"]
    res = api_client.put("/api/llm/providers/vllm", headers=auth_headers(),
                         json={**PROVIDER_BODY, "api_key": "", "default_model": "meta-llama/Llama-3.3-70B-Instruct",
                               "expected_revision": 1})
    assert res.status_code == 200
    assert fake_supabase.table("in_llm_providers").rows[0]["api_key_ciphertext"] == first
    changed = fake_supabase.audit("llm.model_changed")[0]["context"]
    assert changed == {"antes": "Qwen/Qwen3-32B", "despues": "meta-llama/Llama-3.3-70B-Instruct"}


def test_invalid_provider_settings_are_rejected(api_client):
    bad_vendor = api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json={**PROVIDER_BODY, "vendor": "anthropic"})
    assert bad_vendor.status_code == 400
    bad_url = api_client.put("/api/llm/providers/vllm", headers=auth_headers(),
                             json={**PROVIDER_BODY, "base_url": "http://user:pw@llm-server:8000"})
    assert bad_url.status_code == 400 and "contraseña" in bad_url.json()["detail"]
    stale = api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json=PROVIDER_BODY)
    assert stale.status_code == 200
    conflict = api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json={**PROVIDER_BODY, "expected_revision": 0})
    assert conflict.status_code == 409


def test_provider_configuration_is_admin_only(api_client):
    headers = auth_headers(role="operator")
    assert api_client.get("/api/llm/providers", headers=headers).status_code == 403
    assert api_client.put("/api/llm/providers/vllm", headers=headers, json=PROVIDER_BODY).status_code == 403
    assert api_client.put("/api/llm/routing", headers=headers,
                          json={"default_provider": "auto", "auto_order": ["vllm"]}).status_code == 403
    # ...but every member sees what can be selected, without secrets
    catalog = api_client.get("/api/llm/catalog", headers=headers)
    assert catalog.status_code == 200 and "api_key" not in catalog.text
    assert [p["provider"] for p in catalog.json()["providers"]] == ["cloud", "local", "vllm"]


def test_testing_and_refreshing_models_from_the_api(api_client, fake_supabase, llm_servers):
    api_client.put("/api/llm/providers/vllm", headers=auth_headers(), json=PROVIDER_BODY)
    tested = api_client.post("/api/llm/providers/vllm/test", headers=auth_headers(), json=PROVIDER_BODY).json()
    assert tested["status"] == "available" and "Qwen/Qwen3-32B" in tested["models"]
    refreshed = api_client.post("/api/llm/providers/vllm/models/refresh", headers=auth_headers()).json()
    assert refreshed["models"] == ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"]
    models = api_client.get("/api/llm/catalog", headers=auth_headers()).json()["providers"][2]["models"]
    assert models[:2] == ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"] and "mi-modelo-propio" in models
    assert fake_supabase.audit("llm.provider_tested") and fake_supabase.audit("llm.models_refreshed")

    llm_servers.fail("llm-server", "401")
    auth = api_client.post("/api/llm/health", headers=auth_headers(role="operator"),
                           json={"provider": "vllm", "refresh": True}).json()
    assert auth["status"] == "auth_error" and auth["label"] == "Error de autenticación"


def test_routing_is_persisted_and_audited(api_client, fake_supabase):
    res = api_client.put("/api/llm/routing", headers=auth_headers(),
                         json={"default_provider": "auto", "auto_order": ["vllm", "cloud"], "health_ttl_seconds": 15})
    assert res.status_code == 200 and res.json()["auto_order"] == ["vllm", "cloud"]
    catalog = api_client.get("/api/llm/catalog", headers=auth_headers(role="operator")).json()
    assert catalog["routing"]["default_provider"] == "auto"
    assert catalog["default_selection"] == {"provider": "auto", "model": None}
    assert fake_supabase.audit("llm.routing_updated")[0]["context"]["changes"]["default_provider"]["despues"] == "auto"


def test_a_users_saved_choice_is_their_default(api_client):
    api_client.put("/api/me/preferences", headers=auth_headers(role="operator"),
                   json={"theme": "system", "preferences": {"llm_provider": "vllm", "llm_model": "Qwen/Qwen3-32B"}})
    catalog = api_client.get("/api/llm/catalog", headers=auth_headers(role="operator")).json()
    assert catalog["default_selection"] == {"provider": "vllm", "model": "Qwen/Qwen3-32B"}


# ---- end to end: report generation through the layer -------------------------------------------------------


@pytest.fixture
def real_llm_path(monkeypatch):
    """Undo api_client's narrative stub: the pipeline asks the LLM layer, which hands out scripted
    clients per provider (instead of real HTTP clients)."""
    from app.agents import llm as agents_llm
    from tests.conftest import _make_test_narrative

    monkeypatch.setattr("app.services.report.narrative.get_chat_model", agents_llm.get_chat_model)
    from app.services.report.narrative import ReportNarrative

    log: list = []
    clients = {
        "cloud": ScriptedChatModel("cloud", {ReportNarrative: _make_test_narrative}, log=log),
        "vllm": ScriptedChatModel("vllm", {ReportNarrative: _make_test_narrative}, log=log),
        "local": ScriptedChatModel("local", {ReportNarrative: _make_test_narrative}, log=log),
    }
    monkeypatch.setattr(LLMProviderLayer, "create_llm", lambda self, target: clients[target.provider])
    return clients, log


REPORT = {"company": "ACME Corp", "start_date": "2025-07-01", "end_date": "2025-07-31"}


def test_the_selected_provider_generates_the_report_and_is_recorded(api_client, fake_supabase, real_llm_path):
    clients, log = real_llm_path
    res = api_client.post("/api/reports/generate", headers=auth_headers(),
                          json={**REPORT, "llm": {"provider": "vllm", "model": "Qwen/Qwen3-32B"}})
    events = parse_sse_events(res.text)
    result = events[-1]
    assert result["status"] == "ready", result
    assert result["llm"]["provider"] == "vllm" and result["llm"]["model"] == "Qwen/Qwen3-32B"
    assert [e for e in events if e.get("event") == "llm"][0]["phase"] == "selected"
    assert {entry[0] for entry in log} == {"vllm"}  # only vLLM answered

    execution = fake_supabase.table("in_agent_executions").rows[0]
    assert execution["llm_provider"] == "vllm" and execution["model"] == "Qwen/Qwen3-32B"
    assert execution["fallback_used"] is False and execution["llm_metrics"]["calls"] == 1
    generated = fake_supabase.audit("report.generated")[0]["context"]["llm"]
    assert generated["provider"] == "vllm" and generated["input_tokens"] == 100
    calls = [e for e in fake_supabase.table("in_ops_events").rows if e["event"] == "llm.call.completed"]
    assert calls and calls[0]["context"]["provider"] == "vllm" and calls[0]["context"]["model"] == "Qwen/Qwen3-32B"
    assert calls[0]["operation_id"].startswith("req-") and calls[0]["duration_ms"] is not None


def test_auto_falls_back_mid_report_and_says_so(api_client, fake_supabase, real_llm_path):
    clients, log = real_llm_path
    clients["vllm"].fail = httpx.ReadTimeout("t", request=httpx.Request("POST", "http://llm-server:8000"))
    res = api_client.post("/api/reports/generate", headers=auth_headers(), json={**REPORT, "llm": {"provider": "auto"}})
    events = parse_sse_events(res.text)
    result = events[-1]
    assert result["status"] == "ready", result
    assert result["llm"]["requested"] == "auto" and result["llm"]["provider"] == "cloud" and result["llm"]["switched"]
    assert any(e.get("event") == "llm" and e["phase"] == "fallback" for e in events)

    fallback = fake_supabase.audit("llm.provider_fallback")[0]["context"]
    assert (fallback["from"], fallback["to"], fallback["reason"], fallback["stage"]) == ("vllm", "cloud", "timeout", "runtime")
    warning = [e for e in fake_supabase.table("in_ops_events").rows if e["event"] == "llm.provider_fallback"][0]
    assert warning["level"] == "WARNING" and "vLLM → Cloud" in warning["message"]
    execution = fake_supabase.table("in_agent_executions").rows[0]
    assert execution["fallback_used"] is True and execution["fallback_reason"] == "timeout"


def test_an_unavailable_provider_stops_the_report_before_anything_starts(api_client, fake_supabase, llm_servers, real_llm_path):
    llm_servers.fail("llm-server", "connect")
    res = api_client.post("/api/reports/generate", headers=auth_headers(), json={**REPORT, "llm": {"provider": "vllm"}})
    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "error" and result["error_code"] == "llm_unavailable"
    assert "Error de conexión" in result["message"]
    assert fake_supabase.table("in_conversations").rows == []
    assert fake_supabase.audit("llm.provider_error") and fake_supabase.audit("report.generation_blocked")


async def test_langgraph_nodes_use_the_requested_provider_without_knowing_it(isolated_settings, monkeypatch, real_llm_path):
    """The conversational graph (understand_request -> ... -> narrative) runs on whatever the layer resolved."""
    from app.agents.graph import get_compiled_graph
    from app.agents.state import ReportRequestUpdate
    from app.services import llm_runtime

    clients, log = real_llm_path
    clients["local"].responses[ReportRequestUpdate] = ReportRequestUpdate(
        intent="new_report", company="ACME Corp", start_date="2025-08-01", end_date="2025-08-31"
    )
    graph, ctx = await get_compiled_graph(str(isolated_settings.sqlite_checkpoint_db_path))
    try:
        await llm_runtime.start_run(LLMSelection("local"), purpose="test")
        final = await graph.ainvoke(
            {"conversation_id": "conv-llm", "user_request": "Informe de ACME de agosto 2025"},
            config={"configurable": {"thread_id": "conv-llm"}},
        )
    finally:
        llm_runtime.end_run()
        await ctx.__aexit__(None, None, None)
    assert final["status"] == "ready", final.get("errors")
    assert [entry[:2] for entry in log] == [("local", "ReportRequestUpdate"), ("local", "ReportNarrative")]
