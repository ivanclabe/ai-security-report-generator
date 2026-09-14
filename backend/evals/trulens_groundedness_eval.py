"""Groundedness eval for the report-narrative LLM call, using TruLens.

Complements (doesn't replace) the deterministic alarm_number citation check
in ReportSpecification.validate_evidence -- that check catches "cited an
alarm that doesn't exist"; this catches the subtler case of "cited a real
alarm but described/interpreted it in a way the data doesn't support."

Runs the REAL production code path (collect_data node + generate_narrative,
the same function the app calls) against the real THOMAS TGS-TPS Excel data,
under a few different filters, and scores each narrative's groundedness
against the exact DATA JSON the LLM was shown, using Anthropic Claude as the
judge via TruLens's Anthropic provider.

Usage (from a separate eval venv -- see requirements-eval.txt):
    source backend/.venv-eval/bin/activate
    python backend/evals/trulens_groundedness_eval.py [--dashboard]
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from trulens.apps.basic import TruBasicApp  # noqa: E402
from trulens.core import Metric, Selector, TruSession  # noqa: E402
from trulens.providers.anthropic import Anthropic as TruAnthropic  # noqa: E402

from app.agents.nodes.collect_data import collect_data  # noqa: E402
from app.services.report.narrative import (  # noqa: E402
    _build_narrative_payload,
    generate_narrative,
)

# --- Workaround for a real incompatibility between TruLens 2.14.0's Anthropic
# provider and anthropic-python 1.5.0 (installed in this eval venv), found by
# actually running this script, not assumed from documentation:
#
# `anthropic.Anthropic().messages.create()` no longer accepts `temperature` OR
# `reasoning_effort` as top-level kwargs at all in this SDK version (confirmed
# via `inspect.signature` -- neither parameter exists on the method anymore).
# TruLens's provider always injects one or the other depending on whether it
# classifies the judge model as a "reasoning model"
# (Anthropic._is_reasoning_model, a hardcoded name-prefix check that doesn't
# know about either failure mode), so there is no judge-model choice that
# avoids this -- only patching the actual call site does.
#
# Fix: force `_is_reasoning_model()` to True (skips the `temperature` default)
# and strip both keys from `_create_chat_completion`'s kwargs right before the
# real SDK call (removes the `reasoning_effort` that being "a reasoning model"
# then triggers instead). Verified directly against the live API before
# wiring in here -- see AGENT_ARCHITECTURE.md/QUALITY_OBSERVABILITY.md for the
# rest of this project's "verify against the real API, not just docs" pattern.
_original_create_chat_completion = TruAnthropic._create_chat_completion


def _patched_create_chat_completion(self, *args, **kwargs):
    kwargs.pop("temperature", None)
    kwargs.pop("reasoning_effort", None)
    return _original_create_chat_completion(self, *args, **kwargs)


TruAnthropic._create_chat_completion = _patched_create_chat_completion
TruAnthropic._is_reasoning_model = lambda self: True

COMPANY = "THOMAS TGS-TPS"
START_DATE = "2026-07-01"
END_DATE = "2026-07-31"

SCENARIOS = [
    {"name": "informe_general", "focus_categories": None, "risk_level_filter": None},
    {"name": "enfoque_agente_desconectado", "focus_categories": ["Agente desconectado"], "risk_level_filter": None},
    {"name": "solo_criticas_y_altas", "focus_categories": None, "risk_level_filter": ["Critico", "Alto"]},
]


async def _build_scenario_payload(scenario: dict) -> str:
    state = {
        "company": COMPANY,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "focus_categories": scenario["focus_categories"],
        "risk_level_filter": scenario["risk_level_filter"],
    }
    result = await collect_data(state)
    collected = result["collected_data"]
    payload = _build_narrative_payload(collected)
    return json.dumps(payload, indent=2, default=str)


def _narrative_to_text(narrative) -> str:
    parts = [
        narrative.objective,
        narrative.inventory_summary,
        narrative.siem_summary,
        narrative.network_summary,
        narrative.email_summary,
        narrative.threat_intel_summary,
        narrative.compromise_indicators_summary,
        *narrative.highlighted_activities,
        *[f.statement for f in narrative.recommendations],
    ]
    return "\n".join(p for p in parts if p)


def _make_narrative_app(scenario_name: str):
    """Returns a sync str->str callable: TruBasicApp records its single
    input as the groundedness `source` and its return value as `statement`."""

    def narrative_app(data_json: str) -> str:
        narrative = asyncio.run(
            generate_narrative(
                data_json, company=COMPANY, start_date=START_DATE, end_date=END_DATE
            )
        )
        return _narrative_to_text(narrative)

    narrative_app.__name__ = f"narrative_app_{scenario_name}"
    return narrative_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", action="store_true", help="Launch the TruLens Streamlit dashboard after scoring")
    args = parser.parse_args()

    db_path = Path(__file__).resolve().parent / "trulens_eval.sqlite"
    session = TruSession(database_url=f"sqlite:///{db_path}")

    # Deliberately a different (cheaper) model than the app's own (see backend/.env) --
    # fine for a judge role. The temperature/reasoning_effort incompatibility patched
    # above applies regardless of which Claude model is used as judge.
    judge = TruAnthropic(model_engine="claude-haiku-4-5")
    groundedness = Metric(
        implementation=judge.groundedness_measure_with_cot_reasons,
        selectors={
            "source": Selector.select_record_input(),
            "statement": Selector.select_record_output(),
        },
    )

    run_label = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    record_ids = []

    for scenario in SCENARIOS:
        print(f"\n=== Escenario: {scenario['name']} ===")
        data_json = asyncio.run(_build_scenario_payload(scenario))
        print(f"  DATA JSON: {len(data_json)} caracteres")

        app = _make_narrative_app(scenario["name"])
        recorder = TruBasicApp(
            app,
            app_name="report_narrative",
            app_version=scenario["name"],
            feedbacks=[groundedness],
        )

        with recorder as recording:
            recorder.app(data_json)

        record = recording.get()
        print(f"  Registrado: record_id={record.record_id}")
        record_ids.append(record.record_id)

    print("\nEsperando resultados de feedback (juez: claude-haiku-4-5)...")
    session.wait_for_feedback_results(record_ids, ["groundedness_measure_with_cot_reasons"], timeout=180)

    print("\n=== Resumen ===")
    df, feedback_cols = session.get_records_and_feedback(app_name="report_narrative")
    cols = ["app_version", *[c for c in feedback_cols if "groundedness" in c.lower() or "score" in c.lower()]]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].to_string(index=False) if cols else df.to_string(index=False))

    out_csv = Path(__file__).resolve().parent / f"results_{run_label.replace(':', '')}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nResultados completos guardados en: {out_csv}")

    if args.dashboard:
        from trulens.dashboard import run_dashboard

        print("\nAbriendo dashboard de TruLens (Ctrl+C para salir)...")
        run_dashboard(session)


if __name__ == "__main__":
    main()
