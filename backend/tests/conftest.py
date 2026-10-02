import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

REAL_MOCK_DATA_PATH = PROJECT_ROOT / "data" / "mock_security_data.json"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
# 169 alarms of THOMAS TGS-TPS (July 2026), in the exact shape of the live export
# (detallado_alarmas.php?export=csv): UTF-8 with BOM, its 28 columns in its order.
ALARMS_FIXTURE_PATH = FIXTURES_DIR / "alarmas_tps_julio.csv"
ALARMS_EXPECTED_RISK_PATH = FIXTURES_DIR / "alarmas_tps_julio_riesgo_esperado.json"
# A real response of the export with no rows (header only), as delivered by the source.
ALARMS_EMPTY_EXPORT_PATH = FIXTURES_DIR / "alarmas_export_vacio.csv"
# Synthetic data inside the exact markup of the live indicators page (indicadores.php).
INDICATORS_FIXTURE_PATH = FIXTURES_DIR / "indicadores_albatrus_sintetico.html"
MITRE_CATALOG_PATH = PROJECT_ROOT / "data" / "mitre_tactics.json"
COMPANIES_FILE_PATH = PROJECT_ROOT / "data" / "companies.json"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point every path-based setting at a throwaway location per test.

    Defaults the test env to the mock provider even though the app's own
    default is "http" -- tests that want the HTTP source construct it directly
    (see the http_provider fixture, which serves the CSV fixture through an
    in-memory transport) rather than relying on the global default, so no test
    ever tries to reach a real server.
    """
    from app.config.settings import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DATA_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_DATA_PATH", str(REAL_MOCK_DATA_PATH))
    monkeypatch.setenv("MITRE_TACTICS_PATH", str(MITRE_CATALOG_PATH))
    monkeypatch.setenv("SQLITE_APP_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("SQLITE_CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite3"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def mock_provider():
    from app.providers.mock import MockDataProvider

    return MockDataProvider(REAL_MOCK_DATA_PATH)


@pytest.fixture
def source_server():
    """In-memory stand-in for the alarm source: serves the CSV fixture for the
    company it is asked for, enforces Basic Auth, and records every request."""
    from tests.source_fakes import FakeSourceServer

    return FakeSourceServer(ALARMS_FIXTURE_PATH.read_bytes())


@pytest.fixture
def http_provider(source_server):
    from app.providers.http_source import HttpSourceDataProvider
    from app.services.company_registry import get_company_registry
    from tests.source_fakes import build_acquisition

    return HttpSourceDataProvider(build_acquisition(source_server), get_company_registry())


@pytest.fixture(autouse=True)
def _hermetic_company_registry():
    """The company registry normally reads Supabase (in_companies). Tests get one
    backed by the repo's official list (data/companies.json) so no test depends
    on the network or on whatever is currently in the real table. Tests that
    exercise the Supabase loader use the fake_supabase fixture below."""
    from app.services.company_registry import (
        CompanyRegistry,
        load_companies_from_file,
        set_company_registry,
    )

    async def _from_file():
        return load_companies_from_file(COMPANIES_FILE_PATH)

    set_company_registry(CompanyRegistry(_from_file))
    yield
    set_company_registry(None)


@pytest.fixture(autouse=True)
def _reset_sse_starlette_exit_event():
    """sse_starlette caches a asyncio.Event on a module-level singleton the
    first time any EventSourceResponse runs; TestClient spins up a fresh event
    loop per `with TestClient(app) as c:` block, and reusing an Event bound to
    a previous loop raises "bound to a different event loop". Resetting it
    before each test forces sse_starlette to recreate it on the current loop."""
    import sse_starlette.sse

    sse_starlette.sse.AppStatus.should_exit_event = None
    yield


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """See app.auth.reset_login_rate_limit -- the limiter's attempt log is
    process-global, so without this, tests accumulate real login attempts
    against each other and start tripping 429 partway through a full run."""
    from app.auth import reset_login_rate_limit

    reset_login_rate_limit()
    yield


class _FakeSupabaseTable:
    """Returns copies from every read, matching real PostgREST semantics (a
    fresh JSON payload per request) -- some repository methods mutate the
    dict they get back (e.g. `row.pop("specification_json")`), and if that
    were the same object stored here, a later select() would return the
    already-mutated row and misbehave."""

    def __init__(self):
        self.rows: list[dict] = []

    def insert(self, data):
        row = dict(data)
        self.rows.append(row)
        return dict(row)

    def select(self, filters=None, order=None, limit=None):
        rows = [dict(r) for r in self.rows if all(r.get(k) == v for k, v in (filters or {}).items())]
        if order:
            # PostgREST-style "field.dir,field2.dir2" -- sort least-significant key
            # first so the final (most-significant) sort wins, since list.sort() is
            # stable. Real usage in this app never sorts on a column with mixed
            # None/non-None values, so no None-safety wrapper is needed here.
            for clause in reversed(order.split(",")):
                field, _, direction = clause.strip().partition(".")
                rows.sort(key=lambda r, f=field: r.get(f), reverse=(direction == "desc"))
        if limit is not None:
            rows = rows[:limit]
        return rows

    def update(self, filters, data):
        updated = None
        for row in self.rows:
            if all(row.get(k) == v for k, v in filters.items()):
                row.update(data)
                updated = dict(row)
        return updated

    def delete(self, filters):
        self.rows = [r for r in self.rows if not all(r.get(k) == v for k, v in filters.items())]


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, _FakeSupabaseTable] = {}

    def table(self, name: str) -> _FakeSupabaseTable:
        return self.tables.setdefault(name, _FakeSupabaseTable())

    async def select(self, table, filters=None, order=None, limit=None):
        return self.table(table).select(filters, order=order, limit=limit)

    async def insert(self, table, data):
        return self.table(table).insert(data)

    async def update(self, table, filters, data):
        return self.table(table).update(filters, data)

    async def delete(self, table, filters):
        self.table(table).delete(filters)


@pytest.fixture
def fake_supabase(monkeypatch, isolated_settings):
    """In-memory stand-in for Supabase (see app/services/supabase_rest.py) --
    HTTP-level tests use this instead of real network calls. Pre-seeds the
    reference-data tables the deterministic-flow selectors read from."""
    from app.services import supabase_rest as db
    from app.services.company_registry import (
        CompanyRegistry,
        load_companies_from_supabase,
        set_company_registry,
    )

    fake = FakeSupabase()
    fake.table("in_companies").insert({"id": "acme-corp", "name": "ACME Corp", "is_active": True})
    set_company_registry(CompanyRegistry(load_companies_from_supabase))
    fake.table("in_report_templates").insert(
        {"key": "csoc_mensual", "name": "Informe de Gestión CSOC Mensual", "description": "...", "is_active": True}
    )
    monkeypatch.setattr(db, "select", fake.select)
    monkeypatch.setattr(db, "insert", fake.insert)
    monkeypatch.setattr(db, "update", fake.update)
    monkeypatch.setattr(db, "delete", fake.delete)
    return fake


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


def _make_test_narrative():
    from app.schemas.report_spec import EvidenceRef, KeyFinding
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


@pytest.fixture
def api_client(fake_supabase, monkeypatch):
    """TestClient against the real app, Supabase mocked, narrative LLM stubbed."""
    monkeypatch.setattr(
        "app.services.report.narrative.get_chat_model", lambda: _FakeChatModel(_make_test_narrative())
    )
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def auth_headers(client) -> dict:
    res = client.post("/api/auth/login", json={"username": "master", "password": "123456"})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def parse_sse_events(text: str) -> list[dict]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events
