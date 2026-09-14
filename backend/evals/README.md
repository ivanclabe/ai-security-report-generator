# Evals

Offline quality checks for the LLM parts of the agent, kept separate from the
app's own dependencies (Streamlit + TruLens's tracing stack are real weight
that the running app doesn't need).

## Groundedness eval (`trulens_groundedness_eval.py`)

Complements — doesn't replace — the deterministic check already in
`ReportSpecification.validate_evidence()` (which catches a citation of an
`alarm_number` that doesn't exist at all). This eval catches the subtler
case: a citation of a *real* alarm, described or interpreted in a way the
data doesn't actually support.

It runs the real production code (`collect_data` + `generate_narrative` —
the exact same function the app calls, not a re-typed copy) against the real
THOMAS TGS-TPS Excel data, under a few different filters, and scores each
resulting narrative's groundedness against the exact DATA JSON the model was
shown — using Claude (`claude-haiku-4-5`) as the judge via TruLens's
Anthropic provider.

### Setup (separate venv — don't install this into the app's own venv)

```bash
cd backend
python3.12 -m venv .venv-eval
source .venv-eval/bin/activate
pip install -r requirements.txt -r evals/requirements-eval.txt
```

### Run

```bash
source .venv-eval/bin/activate
python evals/trulens_groundedness_eval.py            # scores + CSV
python evals/trulens_groundedness_eval.py --dashboard # also opens the TruLens Streamlit UI
```

Needs `ANTHROPIC_API_KEY` in `backend/.env` (same file the app uses) and
`DATA_PROVIDER=excel` (the default) so it runs against the real client data.

### What it checks

Three scenarios against July 2026 data: a general report, one focused on
"Agente desconectado", and one filtered to Crítico/Alto risk only. For each,
it joins the narrative's prose fields (objective, per-source summaries,
highlighted activities, recommendation statements) into one block of text
and scores it for groundedness (0-1) against the DATA JSON payload, with
chain-of-thought reasons stored alongside the score.

Results land in `evals/trulens_eval.sqlite` (gitignored) and a timestamped
`evals/results_*.csv`. Re-run after changing the narrative prompt
(`SYSTEM_PROMPT` / `ReportNarrative` in
`app/agents/nodes/generate_report_spec.py`) to check the change didn't
quietly make the model less grounded.

### A note on what this caught

While wiring this up, the eval surfaced two real bugs unrelated to TruLens
itself, both fixed in this same pass:

1. `ReportNarrative.highlighted_activities` / `.recommendations` occasionally
   arrived as a bare string instead of a list from Anthropic's tool-calling
   output (intermittent, not reliably reproducible) — the whole report
   generation failed on it. Fixed with a `field_validator` that coerces a
   string into a one-item list instead of raising.
2. TruLens's own Anthropic provider passes `temperature` by default, which
   `claude-sonnet-5` (the app's model) rejects outright — same quirk we'd
   already hit and fixed in our own `llm.py`. Worked around by pointing the
   *judge* at `claude-haiku-4-5`, which still accepts it (and is cheaper,
   which is fine for a judge role).
