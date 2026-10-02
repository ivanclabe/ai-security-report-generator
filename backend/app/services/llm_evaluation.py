"""Quality evaluation across LLM providers/models: same cases, same prompts, comparable numbers.

    Input (fixed cases, synthetic data) -> Claude -> Qwen/vLLM -> ... -> compare

Each candidate runs through the REAL code paths of the app -- the request
understanding prompt (understand_request), the report narrative prompt
(narrative.generate_narrative) and the report validation -- inside its own
LLM run (explicit provider, no fallback), so a candidate is never silently
replaced by another. All data comes from data/mock_security_data.json:
comparing providers never sends client data to any of them.

Metrics (0..1 unless stated):
* extraction_accuracy   -- fields of the user request extracted correctly
* severity_accuracy     -- risk level classification vs. the app's own thresholds
* risk_identification   -- the narrative names the period's top alarm categories
* recommendation_quality-- recommendations grounded in real alarm numbers, substantive
* report_quality        -- the assembled report passes validation, narrative complete
* consistency           -- same input twice -> same evidence/categories (needs >= 2 repetitions)
* latency / errors / tokens -- from the LLM run (calls, failures, input/output tokens)
"""
import json
import logging
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agents.llm import get_chat_model
from app.agents.nodes.understand_request import SYSTEM_PROMPT as UNDERSTAND_PROMPT
from app.agents.state import ReportRequestUpdate
from app.config.settings import PROJECT_ROOT, get_settings
from app.llm.errors import LLMProviderError, safe_error_message
from app.llm.types import LLMSelection
from app.models.domain import risk_level_from_score
from app.providers.mock import MockDataProvider
from app.services import llm_runtime
from app.services.report.collection import collect
from app.services.report.request import ReportRequest
from app.services.report.specification import assemble_specification, narrative_for
from app.services.report.validation import validate

logger = logging.getLogger(__name__)

CASES_PATH = PROJECT_ROOT / "data" / "llm_eval_cases.json"

WEIGHTS = {
    "extraction_accuracy": 0.2,
    "severity_accuracy": 0.15,
    "risk_identification": 0.15,
    "recommendation_quality": 0.2,
    "report_quality": 0.2,
    "consistency": 0.1,
}
# A candidate scoring this much below the baseline (first candidate) is flagged as a degradation.
DEGRADATION_THRESHOLD = 0.05


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str | None = None


def load_cases(path: Path = CASES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


class SeverityAnswer(BaseModel):
    level: Literal["Bajo", "Medio", "Alto", "Critico"]


SEVERITY_PROMPT = """Eres analista de un SOC. Clasifica el nivel de riesgo de la alarma según la escala \
del cliente, usando su puntaje de severidad (0-100): Bajo si es 50 o menos; Medio si es mayor que 50 y \
hasta 70; Alto si es mayor que 70 y hasta 90; Critico si es mayor que 90. Responde solo el nivel."""


def _field_matches(expected, actual) -> bool:
    if isinstance(expected, list):
        return sorted(_plain(str(v)) for v in expected) == sorted(_plain(str(v)) for v in (actual or []))
    return _plain(str(expected)) == _plain(str(actual or ""))


async def _extraction(cases: dict, errors: list[str]) -> float:
    scores = []
    system = UNDERSTAND_PROMPT.format(today=cases["today"], current_state="- (conversación nueva: aún no hay datos)")
    for case in cases["extraction"]:
        expected = case["expected"]
        try:
            update = await get_chat_model().with_structured_output(ReportRequestUpdate).ainvoke(
                [{"role": "system", "content": system}, {"role": "user", "content": case["prompt"]}]
            )
            got = update.model_dump()
            scores.append(sum(_field_matches(v, got.get(k)) for k, v in expected.items()) / len(expected))
        except Exception as exc:  # noqa: BLE001 - an error is a measured outcome, not a crash
            errors.append(f"extracción: {safe_error_message(exc, 160)}")
            scores.append(0.0)
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def _severity_sample(provider: MockDataProvider, size: int) -> list:
    alerts = sorted(provider._alerts, key=lambda a: a.id)  # noqa: SLF001 - synthetic fixture data
    by_level: dict[str, list] = {}
    for alert in alerts:
        by_level.setdefault(risk_level_from_score(alert.severity_score).value, []).append(alert)
    sample, i = [], 0
    while len(sample) < size and any(by_level.values()):
        for level in sorted(by_level):
            if by_level[level] and len(sample) < size:
                sample.append(by_level[level].pop(i % len(by_level[level])))
        i += 1
    return sample


async def _severity(provider: MockDataProvider, size: int, errors: list[str]) -> float:
    sample = _severity_sample(provider, size)
    correct = 0
    for alert in sample:
        expected = risk_level_from_score(alert.severity_score).value
        content = (
            f"Categoría: {alert.category}\nDescripción: {alert.description}\n"
            f"Activo: {', '.join(alert.hostnames)}\nPuntaje de severidad: {alert.severity_score}"
        )
        try:
            answer = await get_chat_model().with_structured_output(SeverityAnswer).ainvoke(
                [{"role": "system", "content": SEVERITY_PROMPT}, {"role": "user", "content": content}]
            )
            correct += answer.level == expected
        except Exception as exc:  # noqa: BLE001
            errors.append(f"severidad: {safe_error_message(exc, 160)}")
    return round(correct / len(sample), 3) if sample else 0.0


def _narrative_text(narrative) -> str:
    parts = [
        narrative.objective, narrative.inventory_summary, narrative.siem_summary, narrative.network_summary,
        narrative.email_summary, narrative.threat_intel_summary, narrative.compromise_indicators_summary,
        *narrative.highlighted_activities, *(r.statement for r in narrative.recommendations),
    ]
    return " ".join(p for p in parts if p)


async def _report(provider: MockDataProvider, case: dict, errors: list[str]) -> dict | None:
    request = ReportRequest(company=case["company"], company_id=case["company_id"],
                            start_date=case["start_date"], end_date=case["end_date"])
    try:
        collected = (await collect(request, provider=provider)).data
        narrative = await narrative_for(request, collected)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"informe: {safe_error_message(exc, 160)}")
        return None
    known = {a["alarm_number"] for a in collected.get("alerts", []) if a.get("alarm_number")}
    spec = assemble_specification(request, collected, narrative)
    validation_errors = validate(spec, known)

    text = _plain(_narrative_text(narrative))
    top_categories = [c for c, _ in Counter(a["category"] for a in collected.get("alerts", [])).most_common(3)]
    risk_hits = sum(_plain(c) in text for c in top_categories)

    recs = narrative.recommendations
    grounded = [
        r for r in recs
        if r.evidence and r.evidence.source_alarm_numbers and set(r.evidence.source_alarm_numbers) <= known
    ]
    substantive = [r for r in recs if len((r.statement or "").strip()) >= 40]
    rec_quality = (len(grounded) / len(recs) * 0.6 + len(substantive) / len(recs) * 0.4) if recs else 0.0

    string_fields = [narrative.objective, narrative.inventory_summary, narrative.siem_summary, narrative.network_summary,
                     narrative.email_summary, narrative.threat_intel_summary, narrative.compromise_indicators_summary]
    completeness = (sum(len((f or "").strip()) >= 20 for f in string_fields) + bool(narrative.highlighted_activities)
                    + bool(recs)) / (len(string_fields) + 2)
    report_quality = (1.0 if not validation_errors else 0.0) * 0.5 + completeness * 0.5

    cited = {n for r in recs if r.evidence for n in r.evidence.source_alarm_numbers}
    return {
        "risk_identification": round(risk_hits / len(top_categories), 3) if top_categories else 0.0,
        "recommendation_quality": round(rec_quality, 3),
        "report_quality": round(report_quality, 3),
        "validation_errors": len(validation_errors),
        "recommendations": len(recs),
        "cited_alarms": sorted(cited),
        "categories_mentioned": sorted(c for c in top_categories if _plain(c) in text),
    }


def _jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _consistency(runs: list[dict]) -> float | None:
    if len(runs) < 2:
        return None
    pairs = [(runs[i], runs[j]) for i in range(len(runs)) for j in range(i + 1, len(runs))]
    scores = [
        (_jaccard(set(x["cited_alarms"]), set(y["cited_alarms"])) + _jaccard(set(x["categories_mentioned"]),
                                                                             set(y["categories_mentioned"]))) / 2
        for x, y in pairs
    ]
    return round(sum(scores) / len(scores), 3)


def _overall(metrics: dict) -> float:
    available = {k: v for k, v in metrics.items() if k in WEIGHTS and v is not None}
    weight = sum(WEIGHTS[k] for k in available)
    return round(sum(WEIGHTS[k] * v for k, v in available.items()) / weight, 3) if weight else 0.0


async def evaluate_candidate(candidate: Candidate, cases: dict, *, repetitions: int = 2) -> dict:
    started = time.monotonic()
    base = {"provider": candidate.provider, "requested_model": candidate.model}
    try:
        run = await llm_runtime.start_run(LLMSelection(candidate.provider, candidate.model), purpose="evaluacion")
    except LLMProviderError as exc:
        return {**base, "status": "unavailable", "error": str(exc), "duration_ms": int((time.monotonic() - started) * 1000)}

    errors: list[str] = []
    provider = MockDataProvider(get_settings().mock_data_path)
    try:
        extraction = await _extraction(cases, errors)
        severity = await _severity(provider, int(cases.get("severity_sample_size", 12)), errors)
        report_runs = []
        for _ in range(max(1, repetitions)):
            for case in cases["report"]:
                if (result := await _report(provider, case, errors)) is not None:
                    report_runs.append(result)
    finally:
        summary = run.summary()
        llm_runtime.end_run()

    def avg(key: str) -> float | None:
        values = [r[key] for r in report_runs]
        return round(sum(values) / len(values), 3) if values else 0.0

    metrics = {
        "extraction_accuracy": extraction,
        "severity_accuracy": severity,
        "risk_identification": avg("risk_identification"),
        "recommendation_quality": avg("recommendation_quality"),
        "report_quality": avg("report_quality"),
        "consistency": _consistency(report_runs),
    }
    return {
        **base,
        "status": "completed",
        "model": summary["model"],
        "vendor": summary["vendor"],
        "metrics": metrics,
        "overall": _overall(metrics),
        "calls": summary["calls"],
        "failed_calls": summary["failed_calls"],
        "avg_latency_ms": round(summary["latency_ms"] / summary["calls"]) if summary["calls"] else None,
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "errors": errors[:20],
        "error_count": len(errors),
        "validation_errors": sum(r["validation_errors"] for r in report_runs),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def compare(results: list[dict]) -> dict:
    """Ranking + degradation flags against the first (baseline) candidate."""
    completed = [r for r in results if r.get("status") == "completed"]
    if not completed:
        return {"baseline": None, "ranking": [], "degradations": []}
    baseline = completed[0]
    ranking = sorted(completed, key=lambda r: r["overall"], reverse=True)
    degradations = []
    for r in completed[1:]:
        delta = round(r["overall"] - baseline["overall"], 3)
        worse = {k: round(r["metrics"][k] - baseline["metrics"][k], 3)
                 for k in WEIGHTS
                 if r["metrics"].get(k) is not None and baseline["metrics"].get(k) is not None
                 and r["metrics"][k] < baseline["metrics"][k] - DEGRADATION_THRESHOLD}
        degradations.append({"provider": r["provider"], "model": r["model"], "overall_delta": delta,
                             "degraded": delta < -DEGRADATION_THRESHOLD, "worse_metrics": worse})
    return {
        "baseline": {"provider": baseline["provider"], "model": baseline["model"], "overall": baseline["overall"]},
        "ranking": [{"provider": r["provider"], "model": r["model"], "overall": r["overall"]} for r in ranking],
        "degradations": degradations,
    }
