# AI Security Report Generator

Conversational AI agent that turns a chat request ("Genera el informe de gestión CSOC de THOMAS
TGS-TPS para julio de 2026") into a Word (.docx) management report matching the client's own
recurring "Informe de Gestión CSOC" template, and keeps the conversation and report editable
afterward ("enfócalo solo en Agente desconectado", "hazlo más ejecutivo").

All data is **synthetic** — including `data/thomas_tgs_tps_alarmas_julio.xlsx`, a client-shaped
alarm export the project owner provided for realism, which does not represent any real company,
incident, or security posture.

## Architecture

Modular monolith: a FastAPI backend runs a LangGraph agent behind a `DataProvider` abstraction
(`ExcelDataProvider` by default, `MockDataProvider` for a purely synthetic alternative, a real
API/DB provider later — none of it touches the agent or tools), and a React chat UI drives it
over REST + SSE.

The report's **section skeleton is fixed** (11 sections, matching the client's own recurring
"Informe de Gestión CSOC" Word template — see the real file the client shared), not something the
LLM decides turn to turn. `generate_report_spec.py` assembles it in code from tool output; the
LLM's only job is writing short grounded prose for a handful of fields
(`ReportNarrative`) plus evidence-backed recommendations. Sections with no backing data source
(vulnerability management, brand monitoring, behavioral analytics — none of which exist in the
current data) render an explicit "no disponible" notice instead of being silently dropped or
guessed at. `python-docx` then builds the `.docx` from the final, validated
`ReportSpecification` — never free-form LLM output, and never a fabricated alarm citation
(`ReportSpecification.validate_evidence` checks every cited `alarm_number` against what was
actually collected).

```
frontend/   React + TypeScript + Vite + Tailwind chat UI
backend/    FastAPI + LangGraph agent + tools + providers (excel/mock) + python-docx builder
data/       thomas_tgs_tps_alarmas_julio.xlsx (default source), mitre_tactics.json (static
            MITRE ATT&CK catalog), mock_security_data.json (+ scripts/generate_mock_data.py)
```

### Data providers

- **`excel` (default)** — `ExcelDataProvider` normalizes the client's own "Alarmas" sheet export
  into `NormalizedSecurityAlert` records (`backend/app/providers/excel_ingestion.py`). It handles
  the source format's real quirks: severity is a 1-100 score (or the string `"ANULADO"` for
  voided alarms), risk tier (`Critico`/`Alto`/`Medio`/`Bajo`) is derived from that score using the
  client's own thresholds — verified empirically against every row's own `Riesgo` label, not
  assumed from the sheet's printed (and slightly misleading) ranges — IP/hostname fields can hold
  multiple values, and free-text fields carry Excel `_x000D_` artifacts that get cleaned.
- **`mock`** — `MockDataProvider`, fully synthetic, no external file dependency beyond the
  generated JSON. Useful for demos/tests independent of the client file.
- Switch with `DATA_PROVIDER=excel|mock` in `backend/.env`.

See `backend/app/agents/graph.py` for the full agent workflow and `backend/app/agents/state.py`
for the conversation state schema.

### Login and conversation storage

The app sits behind a single hardcoded operator login (`AUTH_USERNAME`/`AUTH_PASSWORD` in
`backend/.env`, default `master`/`123456`) rather than per-user accounts — there's only ever one
credential pair, so full Supabase Auth would be more machinery than the requirement calls for.
`POST /api/auth/login` issues a signed JWT (`backend/app/auth.py`); every `/api/conversations*`
and `/api/reports*` route requires it as a Bearer token.

Conversations, messages, reports, and report versions live in Supabase Postgres, in tables
prefixed `in_` (`in_conversations`, `in_messages`, `in_reports`, `in_report_versions` —
see `backend/app/services/repositories.py` and `backend/app/services/supabase_rest.py`) so they
don't collide with anything else in a shared Supabase project. The backend talks to them over
PostgREST using the project's anon key, kept server-side only (`backend/.env`, never sent to the
frontend); RLS policies on just those four tables grant that key full access. Conversations can
be renamed, pinned, and deleted from the sidebar — pinned conversations sort to the top.
The LangGraph checkpointer (agent state per conversation) is unrelated and still uses its own
local SQLite file.

## Prerequisites

- An Anthropic API key (the agent uses Claude via `langchain-anthropic`)
- A Supabase project (for conversation/report storage — see above)
- Docker + Docker Compose, **or** Python 3.12+ and Node 20+ for running the two apps directly

## Run with Docker Compose

```bash
cp backend/.env.example backend/.env   # fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (docs at `/docs`)

## Run locally without Docker

Backend:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Regenerating the mock dataset

```bash
python3 scripts/generate_mock_data.py
```

## Tests

```bash
# backend
cd backend && source .venv/bin/activate && pytest

# frontend
cd frontend && npm test
```

The agent's LangGraph tests stub the LLM calls (see `backend/tests/test_agent_graph.py`), so the
full workflow — new report, clarification pause, and in-context modification without
re-fetching data — is verified without needing a live API key.

### LLM quality eval (TruLens)

Pytest checks code correctness; it doesn't check whether the LLM's narrative is actually
grounded in the data it was given. `backend/evals/` has a TruLens-based groundedness eval that
runs the real narrative-generation call against real client data and scores it with Claude as
judge — see `backend/evals/README.md`. Needs a live API key and a separate venv (Streamlit/TruLens
aren't part of the app's own dependencies).

## Example flow

```
User: Genera el informe de gestión CSOC de THOMAS TGS-TPS para julio de 2026.
AI:   [retrieves data, analyzes it, builds the report] Tu informe está listo — 8 secciones.
      [Download Informe (.docx)]

User: Enfócalo solo en la categoría "Agente desconectado".
AI:   [re-collects data filtered to that category, regenerates] Aquí está v2.

User: Hazlo más ejecutivo.
AI:   [reuses already-collected data, only regenerates the narrative] Aquí está v3.
```

Each regeneration is stored as a new `report_versions` row (see `backend/app/services/db.py`),
so past versions remain retrievable via `GET /api/reports/{report_id}`.

## Notes on deviations from the original tech-stack list

- **python-docx instead of PptxGenJS/python-pptx** — the client's real recurring report turned
  out to be a Word document (`.docx`), not a slide deck; see the "TGS TPS Informe de Gestión
  CSOC" file the client shared. Switched from PowerPoint to Word generation to match, keeping the
  generator in the same language as the backend/agent.
- Conversation state persistence uses LangGraph's own `AsyncSqliteSaver` checkpointer (keyed by
  `conversation_id`) rather than hand-rolled state storage — it already does exactly what §17/§2
  require (durable, resumable agent state per conversation) without extra code.
- MITRE ATT&CK tactic names/descriptions are resolved against a static catalog
  (`data/mitre_tactics.json`, sourced from the client's own "ID Mitre" reference sheet) rather
  than trusting each row's free-text label — keeps naming consistent across the whole dataset.
- Section 6.1 (top email-rarity recipients) reads the client's own precomputed pivot
  (`ingest_email_rarity_ranking`) instead of recomputing it from the 34k-row raw email log —
  their numbers are the trusted source of truth already published in their report, and
  re-deriving the aggregation risks silently disagreeing with them.
