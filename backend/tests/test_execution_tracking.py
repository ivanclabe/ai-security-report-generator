"""Mocks the Supabase REST layer -- same pattern as test_ingestion_service.py,
runs offline."""
import pytest

from app.services import supabase_rest as db
from app.services.report import execution_tracking
from app.services.report.request import ReportRequest


class _FakeTable:
    def __init__(self):
        self.rows: list[dict] = []

    def insert(self, data):
        row = dict(data)
        self.rows.append(row)
        return row

    def update(self, filters, data):
        for row in self.rows:
            if all(row.get(k) == v for k, v in filters.items()):
                row.update(data)
                return row
        return None


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, _FakeTable] = {}

    def _table(self, name):
        return self.tables.setdefault(name, _FakeTable())

    async def insert(self, table, data):
        return self._table(table).insert(data)

    async def update(self, table, filters, data):
        return self._table(table).update(filters, data)


@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(db, "insert", fake.insert)
    monkeypatch.setattr(db, "update", fake.update)
    return fake


async def test_start_execution_records_running_status(fake_supabase):
    request = ReportRequest(company="ACME", start_date="2026-01-01", end_date="2026-01-31")
    execution_id = await execution_tracking.start_execution(
        conversation_id="conv-1", company_id=None, mode="conversational", request=request
    )

    row = fake_supabase.tables["in_agent_executions"].rows[0]
    assert row["id"] == execution_id
    assert row["status"] == "running"
    assert row["mode"] == "conversational"
    assert row["request_params"]["company"] == "ACME"


async def test_finish_execution_updates_the_same_row(fake_supabase):
    execution_id = await execution_tracking.start_execution(
        conversation_id="conv-1", company_id=None, mode="conversational", request=None
    )
    await execution_tracking.finish_execution(
        execution_id,
        status="ready",
        company_id="acme-corp",
        report_id="report-1",
        report_version_id="ver-1",
        duration_ms=1234,
    )

    row = fake_supabase.tables["in_agent_executions"].rows[0]
    assert row["status"] == "ready"
    assert row["company_id"] == "acme-corp"
    assert row["report_id"] == "report-1"
    assert row["duration_ms"] == 1234
    assert row["completed_at"] is not None


async def test_start_execution_records_triggered_by(fake_supabase):
    await execution_tracking.start_execution(
        conversation_id="conv-1", company_id=None, mode="conversational", request=None, triggered_by="user-master"
    )
    row = fake_supabase.tables["in_agent_executions"].rows[0]
    assert row["triggered_by"] == "user-master"


async def test_finish_execution_records_usage_and_estimated_cost(fake_supabase):
    execution_id = await execution_tracking.start_execution(
        conversation_id="conv-1", company_id=None, mode="conversational", request=None
    )
    usage = {"claude-sonnet-5": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
    await execution_tracking.finish_execution(execution_id, status="ready", usage_metadata=usage)

    row = fake_supabase.tables["in_agent_executions"].rows[0]
    assert row["usage_metadata"] == usage
    assert row["estimated_cost_usd"] == 18.0


async def test_finish_execution_without_usage_leaves_cost_untouched(fake_supabase):
    execution_id = await execution_tracking.start_execution(
        conversation_id="conv-1", company_id=None, mode="conversational", request=None
    )
    await execution_tracking.finish_execution(execution_id, status="error")

    row = fake_supabase.tables["in_agent_executions"].rows[0]
    assert "usage_metadata" not in row or row["usage_metadata"] == {}
    assert row.get("estimated_cost_usd") is None
