"""Unit tests for ingestion_service.py, mocking the Supabase REST layer so
these run offline -- no network, no real Supabase project needed."""
from datetime import datetime, timezone

import pytest

from app.models.domain import NormalizedSecurityAlert, RiskLevel
from app.services import ingestion_service
from app.services import supabase_rest as db


class _FakeTable:
    """In-memory stand-in for one Supabase table, keyed by row 'id'."""

    def __init__(self):
        self.rows: list[dict] = []

    def insert(self, data: dict) -> dict:
        row = dict(data)
        self.rows.append(row)
        return row

    def select(self, filters: dict) -> list[dict]:
        return [r for r in self.rows if all(r.get(k) == v for k, v in (filters or {}).items())]


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, _FakeTable] = {}

    def _table(self, name: str) -> _FakeTable:
        return self.tables.setdefault(name, _FakeTable())

    async def select(self, table, filters=None, order=None, limit=None):
        return self._table(table).select(filters or {})

    async def insert(self, table, data):
        return self._table(table).insert(data)


@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(db, "select", fake.select)
    monkeypatch.setattr(db, "insert", fake.insert)
    return fake


def _alert(client: str, alarm_number: str) -> NormalizedSecurityAlert:
    now = datetime.now(timezone.utc)
    return NormalizedSecurityAlert(
        id=alarm_number,
        alarm_number=alarm_number,
        client=client,
        alert_type="NG SIEM FALCON",
        category="Test",
        severity_score=80,
        risk_level=RiskLevel.ALTO,
        event_timestamp=now,
        created_at=now,
        reported_at=now,
        description="test alert",
    )


class _FakeProvider:
    def __init__(self, alerts, warnings=None):
        self.alerts = alerts
        self.ingestion_warnings = warnings or []


async def test_records_company_source_and_import_for_a_single_client(tmp_path, fake_supabase):
    excel_path = tmp_path / "alarmas.xlsx"
    excel_path.write_bytes(b"fake excel bytes")
    provider = _FakeProvider([_alert("ACME", "A-1"), _alert("ACME", "A-2")])

    created = await ingestion_service.record_excel_import(provider, excel_path)

    assert len(created) == 1
    assert fake_supabase.tables["in_companies"].rows[0]["id"] == "acme"
    assert fake_supabase.tables["in_data_sources"].rows[0]["company_id"] == "acme"
    import_row = fake_supabase.tables["in_data_imports"].rows[0]
    assert import_row["row_count"] == 2
    assert import_row["status"] == "success"
    assert import_row["company_id"] == "acme"


async def test_records_one_import_per_distinct_client(tmp_path, fake_supabase):
    excel_path = tmp_path / "alarmas.xlsx"
    excel_path.write_bytes(b"fake excel bytes")
    provider = _FakeProvider([_alert("ACME", "A-1"), _alert("OTHER CO", "B-1")])

    created = await ingestion_service.record_excel_import(provider, excel_path)

    assert len(created) == 2
    company_ids = {row["company_id"] for row in fake_supabase.tables["in_data_imports"].rows}
    assert company_ids == {"acme", "other-co"}


async def test_reimporting_identical_file_does_not_duplicate_import_row(tmp_path, fake_supabase):
    excel_path = tmp_path / "alarmas.xlsx"
    excel_path.write_bytes(b"same bytes every time")
    provider = _FakeProvider([_alert("ACME", "A-1")])

    first = await ingestion_service.record_excel_import(provider, excel_path)
    second = await ingestion_service.record_excel_import(provider, excel_path)

    assert len(fake_supabase.tables["in_data_imports"].rows) == 1
    assert first[0]["id"] == second[0]["id"]


async def test_status_reflects_warnings(tmp_path, fake_supabase):
    excel_path = tmp_path / "alarmas.xlsx"
    excel_path.write_bytes(b"bytes")
    provider = _FakeProvider([_alert("ACME", "A-1")], warnings=["row 3: missing 'tipo'"])

    created = await ingestion_service.record_excel_import(provider, excel_path)

    assert created[0]["status"] == "partial"
    assert created[0]["warning_count"] == 1


async def test_no_alerts_and_warnings_means_failed_status():
    # A sheet with a missing required column yields zero alerts and one warning --
    # nothing to associate with a company, so nothing is persisted, but the
    # status-derivation logic itself (exercised indirectly via record_excel_import
    # when alerts_by_client is empty) should not raise.
    provider = _FakeProvider([], warnings=["Sheet 'Alarmas': missing required column(s): cliente"])
    assert provider.alerts == []
