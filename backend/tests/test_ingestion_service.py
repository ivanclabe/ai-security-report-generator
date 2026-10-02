"""Import audit (ingestion_service.record_import): one in_data_imports row per
distinct payload, recorded against a registered company, no secrets stored."""
from datetime import datetime

import pytest

from app.ingestion.service import AlarmBatch
from app.models.domain import Company
from app.services import ingestion_service


def _batch(*, company_id="thomas-tgs-tps", content_hash="a" * 64, alerts=(), warnings=()) -> AlarmBatch:
    return AlarmBatch(
        company=Company(id=company_id, name="THOMAS TGS TPS"),
        start=datetime(2026, 7, 1),
        end=datetime(2026, 7, 31),
        alerts=list(alerts),
        warnings=list(warnings),
        rows_received=len(alerts),
        content_hash=content_hash,
        request_url="https://source.test/detallado_alarmas.php?cliente=THOMAS+TGS-TPS",
    )


async def test_first_import_creates_the_data_source_and_the_import_row(http_provider, fake_supabase):
    # (http_provider first: it must keep the file-backed registry that knows TPS, not the fake table's)
    company = await http_provider.get_company(name="THOMAS TGS TPS")
    batch = await http_provider._acquisition.get_batch(company, datetime(2026, 7, 1), datetime(2026, 7, 31, 23, 59, 59))

    row = await ingestion_service.record_import(batch)

    sources = fake_supabase.table("in_data_sources").rows
    assert len(sources) == 1
    assert (sources[0]["company_id"], sources[0]["source_type"]) == ("thomas-tgs-tps", "api")
    assert sources[0]["config"] == {}  # nothing about the server or its credentials is stored
    assert row["status"] == "success" and row["row_count"] == 169 and row["warning_count"] == 0
    assert row["file_hash"] == batch.content_hash
    assert row["source_file_ref"].startswith("https://source.test/detallado_alarmas.php?")


async def test_identical_payloads_are_not_recorded_twice(fake_supabase):
    first = await ingestion_service.record_import(_batch())
    again = await ingestion_service.record_import(_batch())

    assert again["id"] == first["id"]
    assert len(fake_supabase.table("in_data_imports").rows) == 1
    assert len(fake_supabase.table("in_data_sources").rows) == 1


async def test_a_changed_payload_is_a_new_import_on_the_same_data_source(fake_supabase):
    await ingestion_service.record_import(_batch(content_hash="a" * 64))
    await ingestion_service.record_import(_batch(content_hash="b" * 64))

    assert len(fake_supabase.table("in_data_imports").rows) == 2
    assert len(fake_supabase.table("in_data_sources").rows) == 1


@pytest.mark.parametrize(
    "alerts, warnings, expected",
    [([], ["sin datos"], "failed"), (["x"], ["algo"], "partial"), (["x"], [], "success")],
)
async def test_status_reflects_warnings(fake_supabase, alerts, warnings, expected):
    row = await ingestion_service.record_import(_batch(alerts=alerts, warnings=warnings))
    assert row["status"] == expected
    assert row["warnings"] == warnings
