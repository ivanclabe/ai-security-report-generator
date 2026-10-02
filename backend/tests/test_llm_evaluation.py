"""Provider quality comparison: same cases, real prompts, comparable metrics."""
import pytest

from app.agents.state import ReportRequestUpdate
from app.llm.layer import LLMProviderLayer
from app.models.domain import risk_level_from_score
from app.services import llm_evaluation as evaluation
from app.services import llm_settings_service as llm_settings
from app.services.report.narrative import ReportNarrative
from tests.conftest import auth_headers
from tests.llm_fakes import ScriptedChatModel


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://llm-server:8000")
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-32B")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    llm_settings.invalidate_cache()
    yield
    get_settings.cache_clear()


def _perfect_extraction(cases):
    answers = iter(cases["extraction"])

    def next_update():
        return ReportRequestUpdate(intent="new_report", **next(answers)["expected"])

    return next_update


def _narrative_citing(alarms: list[str]):
    from app.schemas.report_spec import EvidenceRef, KeyFinding

    def build():
        return ReportNarrative(
            objective="Evaluar la postura de seguridad de ACME Corp en junio, con foco en Authentication y Malware.",
            inventory_summary="El inventario de activos se mantuvo estable durante el período analizado.",
            siem_summary="La actividad del SIEM mostró picos asociados a Authentication y Network.",
            network_summary="La actividad de red fue la esperada para el período, sin anomalías mayores.",
            email_summary="Los antígenos de correo no registraron campañas relevantes en el período.",
            threat_intel_summary="No se identificaron indicadores de amenaza nuevos de relevancia.",
            compromise_indicators_summary="Las IP observadas no coinciden con indicadores de compromiso.",
            highlighted_activities=["Se atendieron las alarmas de Authentication y Malware del período."],
            recommendations=[KeyFinding(statement="Reforzar MFA en accesos remotos tras los intentos fallidos registrados.",
                                        evidence=EvidenceRef(source_alarm_numbers=alarms))],
        )

    return build


async def test_a_candidate_is_scored_on_the_real_prompts(monkeypatch):
    cases = evaluation.load_cases()
    from app.config.settings import get_settings
    from app.providers.mock import MockDataProvider

    mock = MockDataProvider(get_settings().mock_data_path)
    june = [a.alarm_number for a in mock._alerts if a.client == "ACME Corp" and a.event_timestamp.strftime("%Y-%m") == "2025-06"]
    sample = evaluation._severity_sample(mock, cases["severity_sample_size"])
    levels = iter([risk_level_from_score(a.severity_score).value for a in sample])

    log: list = []
    client = ScriptedChatModel("vllm", {
        ReportRequestUpdate: _perfect_extraction(cases),
        evaluation.SeverityAnswer: lambda: evaluation.SeverityAnswer(level=next(levels)),
        ReportNarrative: _narrative_citing(june[:2]),
    }, log=log)
    monkeypatch.setattr(LLMProviderLayer, "create_llm", lambda self, target: client)

    result = await evaluation.evaluate_candidate(evaluation.Candidate("vllm"), {**cases}, repetitions=2)

    assert result["status"] == "completed" and result["model"] == "Qwen/Qwen3-32B"
    metrics = result["metrics"]
    assert metrics["extraction_accuracy"] == 1.0
    assert metrics["severity_accuracy"] == 1.0
    assert metrics["recommendation_quality"] == 1.0  # grounded in real alarms and substantive
    assert metrics["report_quality"] == 1.0
    assert metrics["consistency"] == 1.0  # same evidence both times
    assert 0 <= metrics["risk_identification"] <= 1
    assert result["calls"] == len(cases["extraction"]) + cases["severity_sample_size"] + 2
    assert result["input_tokens"] == 100 * result["calls"] and result["error_count"] == 0
    assert {entry[0] for entry in log} == {"vllm"}  # the candidate is never replaced


async def test_errors_and_unavailable_candidates_are_measured_not_fatal(monkeypatch, llm_servers):
    cases = evaluation.load_cases()
    failing = ScriptedChatModel("cloud", fail=ValueError("salida inválida"))
    monkeypatch.setattr(LLMProviderLayer, "create_llm", lambda self, target: failing)
    result = await evaluation.evaluate_candidate(evaluation.Candidate("cloud"), cases, repetitions=1)
    assert result["status"] == "completed" and result["error_count"] > 0
    assert result["metrics"]["extraction_accuracy"] == 0.0 and result["failed_calls"] == result["calls"]

    llm_servers.fail("llm-server", "timeout")
    unavailable = await evaluation.evaluate_candidate(evaluation.Candidate("vllm"), cases)
    assert unavailable["status"] == "unavailable" and "Tiempo de espera" in unavailable["error"]


def test_comparison_flags_degradations_against_the_baseline():
    base = {"status": "completed", "provider": "cloud", "model": "claude", "overall": 0.9,
            "metrics": {k: 0.9 for k in evaluation.WEIGHTS}}
    worse = {"status": "completed", "provider": "vllm", "model": "qwen", "overall": 0.7,
             "metrics": {**{k: 0.9 for k in evaluation.WEIGHTS}, "recommendation_quality": 0.5}}
    summary = evaluation.compare([base, worse])
    assert summary["baseline"]["provider"] == "cloud"
    assert summary["ranking"][0]["provider"] == "cloud"
    degradation = summary["degradations"][0]
    assert degradation["degraded"] is True and "recommendation_quality" in degradation["worse_metrics"]


def test_evaluations_are_admin_only_and_validated(api_client):
    body = {"candidates": [{"provider": "cloud"}, {"provider": "vllm"}], "repetitions": 1}
    assert api_client.post("/api/llm/evaluations", headers=auth_headers(role="operator"), json=body).status_code == 403
    too_many = {"candidates": [{"provider": "cloud"}] * 5}
    assert api_client.post("/api/llm/evaluations", headers=auth_headers(), json=too_many).status_code == 422


def test_starting_an_evaluation_is_audited(api_client, fake_supabase, monkeypatch):
    async def fake_run(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.llm_evaluations._run", fake_run)
    res = api_client.post("/api/llm/evaluations", headers=auth_headers(),
                          json={"candidates": [{"provider": "cloud"}, {"provider": "vllm", "model": "Qwen/Qwen3-32B"}]})
    assert res.status_code == 200 and res.json()["status"] == "queued"
    started = fake_supabase.audit("llm.evaluation_started")[0]["context"]
    assert started["candidates"][1] == {"provider": "vllm", "model": "Qwen/Qwen3-32B"}
    listed = api_client.get("/api/llm/evaluations", headers=auth_headers()).json()
    assert listed[0]["id"] == res.json()["id"]
