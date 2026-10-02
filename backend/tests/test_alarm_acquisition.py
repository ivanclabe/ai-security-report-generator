"""AlarmAcquisitionService: fetch -> decode -> normalize -> company guard -> cache."""
import asyncio
import io
from datetime import datetime

import pandas as pd
import pytest

from app.ingestion.errors import SourceFormatError
from app.services.company_registry import get_company_registry
from tests.conftest import ALARMS_FIXTURE_PATH
from tests.source_fakes import build_acquisition

JULY = (datetime(2026, 7, 1, 0, 0), datetime(2026, 7, 31, 23, 59, 59))
MAY_JUNE = (datetime(2026, 5, 1, 0, 0), datetime(2026, 6, 30, 23, 59, 59))


@pytest.fixture
async def tps():
    return await get_company_registry().get(company_id="thomas-tgs-tps")


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _fixture_df() -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(ALARMS_FIXTURE_PATH.read_bytes()), dtype=str, keep_default_na=False)


# ---- the happy path ----------------------------------------------------------


async def test_fetches_and_normalizes_the_companys_alarms(source_server, tps):
    acquisition = build_acquisition(source_server)

    batch = await acquisition.get_batch(tps, *JULY)

    assert len(batch.alerts) == batch.rows_received == 169
    assert batch.warnings == []
    # requests use the registry's value for cliente= ('THOMAS TGS-TPS' for TPS)...
    assert source_server.alarm_requests[0].url.params["cliente"] == "THOMAS TGS-TPS"
    assert source_server.alarm_requests[0].url.params["desde"] == "2026-07-01T00:00"
    assert source_server.alarm_requests[0].url.params["hasta"] == "2026-07-31T23:59"
    # ...and from then on the company carries its official report name, the source's spelling kept in raw_record
    assert {a.client for a in batch.alerts} == {"THOMAS TGS TPS"}
    assert batch.alerts[0].raw_record["cliente"] == "THOMAS TGS-TPS"


async def test_an_import_fingerprint_is_recorded_without_credentials(source_server, tps):
    batch = await build_acquisition(source_server).get_batch(tps, *JULY)

    assert len(batch.content_hash) == 64
    assert "source.test/detallado_alarmas.php" in batch.request_url
    assert "not-a-real-password" not in batch.request_url


# ---- cache ---------------------------------------------------------------------


async def test_repeated_requests_for_the_same_period_hit_the_cache(source_server, tps):
    acquisition = build_acquisition(source_server)

    first = await acquisition.get_batch(tps, *JULY)
    second = await acquisition.get_batch(tps, *JULY)

    assert second is first
    assert len(source_server.alarm_requests) == 1


async def test_a_different_period_is_a_different_request(source_server, tps):
    acquisition = build_acquisition(source_server)
    await acquisition.get_batch(tps, *JULY)
    await acquisition.get_batch(tps, *MAY_JUNE)
    assert len(source_server.alarm_requests) == 2


async def test_cache_expires_after_the_ttl(source_server, tps):
    clock = {"now": 1000.0}
    acquisition = build_acquisition(source_server, clock=lambda: clock["now"], cache_ttl_seconds=300)

    await acquisition.get_batch(tps, *JULY)
    clock["now"] += 299
    await acquisition.get_batch(tps, *JULY)
    assert len(source_server.alarm_requests) == 1
    clock["now"] += 2
    await acquisition.get_batch(tps, *JULY)
    assert len(source_server.alarm_requests) == 2


async def test_concurrent_identical_requests_share_one_fetch(source_server, tps):
    acquisition = build_acquisition(source_server)
    batches = await asyncio.gather(*(acquisition.get_batch(tps, *JULY) for _ in range(5)))
    assert len(source_server.alarm_requests) == 1
    assert all(b is batches[0] for b in batches)


async def test_the_oldest_batches_are_evicted_beyond_the_limit(source_server, tps):
    from app.ingestion.service import AlarmAcquisitionService
    from tests.source_fakes import build_client

    acquisition = AlarmAcquisitionService(build_client(source_server), {}, max_entries=2)
    for month in (1, 2, 3):
        await acquisition.get_batch(tps, datetime(2026, month, 1), datetime(2026, month, 28))
    assert len(acquisition._batches) == 2


# ---- listener (import audit) ----------------------------------------------------


async def test_listener_runs_once_per_fresh_fetch_and_never_breaks_a_report(source_server, tps):
    calls = []

    async def listener(batch):
        calls.append(batch.company.id)
        raise RuntimeError("supabase is down")

    acquisition = build_acquisition(source_server, on_fetch=listener)
    batch = await acquisition.get_batch(tps, *JULY)
    await acquisition.get_batch(tps, *JULY)  # cache hit

    assert len(batch.alerts) == 169  # the failing listener did not fail the fetch
    assert calls == ["thomas-tgs-tps"]


# ---- lookups by alarm number -----------------------------------------------------


async def test_alerts_can_be_found_by_id_or_alarm_number_even_after_the_ttl(source_server, tps):
    clock = {"now": 0.0}
    acquisition = build_acquisition(source_server, clock=lambda: clock["now"], cache_ttl_seconds=60)
    batch = await acquisition.get_batch(tps, *JULY)
    target = batch.alerts[0]
    clock["now"] += 10_000  # long expired for fetching purposes

    assert acquisition.find_alert(target.id).id == target.id
    assert acquisition.find_alert(target.alarm_number).id == target.id
    assert acquisition.find_alert("ALARMA-INEXISTENTE") is None


# ---- guarding against the wrong company -------------------------------------------


async def test_rows_of_other_companies_are_discarded_with_a_warning(source_server, tps):
    df = _fixture_df()
    stranger = df.head(5).copy()
    stranger["cliente"] = "THOMAS TGS COL TTI"
    stranger["alarma_no"] = [f"OTRA-{i}" for i in range(5)]
    stranger["id"] = [f"9{i}" for i in range(5)]
    source_server.alarms_csv = _csv(pd.concat([df, stranger]))
    # a server that ignores the cliente filter and returns everything
    source_server._alarms_for = lambda cliente: source_server.alarms_csv
    acquisition = build_acquisition(source_server)

    batch = await acquisition.get_batch(tps, *JULY)

    assert len(batch.alerts) == 169 and batch.rows_received == 174
    assert any("descartaron 5 alarmas de otras empresas" in w and "THOMAS TGS COL TTI" in w for w in batch.warnings)


async def test_a_response_with_only_other_companies_fails_loudly(source_server, tps):
    df = _fixture_df()
    df["cliente"] = "THOMAS TGS COL TTI"
    source_server.alarms_csv = _csv(df)
    source_server._alarms_for = lambda cliente: source_server.alarms_csv

    with pytest.raises(SourceFormatError) as excinfo:
        await build_acquisition(source_server).get_batch(tps, *JULY)

    assert "ninguna pertenece a THOMAS TGS TPS" in str(excinfo.value)
    assert "source_client" in str(excinfo.value)


async def test_the_source_may_identify_the_company_by_its_albatroz_consecutivo(source_server, tps):
    df = _fixture_df()
    df["cliente"] = "TGS TPS"
    source_server.alarms_csv = _csv(df)
    source_server._alarms_for = lambda cliente: source_server.alarms_csv

    batch = await build_acquisition(source_server).get_batch(tps, *JULY)
    assert len(batch.alerts) == 169


# ---- empty / broken responses ----------------------------------------------------


async def test_no_alarms_is_a_valid_empty_period_but_explains_how_to_check_the_company(source_server):
    bac = await get_company_registry().get(company_id="bac")  # the fixture only holds TPS alarms

    batch = await build_acquisition(source_server).get_batch(bac, *JULY)

    assert batch.alerts == [] and batch.rows_received == 0
    assert source_server.alarm_requests[0].url.params["cliente"] == "BAC"  # no source_client => report name
    assert "source_client" in batch.warnings[0] and "'BAC'" in batch.warnings[0]


async def test_html_instead_of_csv_is_a_format_error(source_server, tps):
    source_server.html_instead_of_csv = True
    with pytest.raises(SourceFormatError) as excinfo:
        await build_acquisition(source_server).get_batch(tps, *JULY)
    assert "HTML" in str(excinfo.value)


async def test_csv_without_the_expected_columns_fails_loudly(source_server, tps):
    source_server.alarms_csv = b"foo,bar\n1,2\n"
    source_server._alarms_for = lambda cliente: source_server.alarms_csv

    with pytest.raises(SourceFormatError) as excinfo:
        await build_acquisition(source_server).get_batch(tps, *JULY)
    assert "missing required column" in str(excinfo.value)


async def test_a_response_at_the_row_limit_is_flagged_as_possibly_truncated(source_server, tps):
    batch = await build_acquisition(source_server, alarms_limit=169).get_batch(tps, *JULY)
    assert any("truncado" in w for w in batch.warnings)
    assert source_server.alarm_requests[0].url.params["limite"] == "169"


async def test_dates_far_outside_the_requested_period_hint_at_a_date_format_problem(source_server, tps):
    df = _fixture_df()
    for column in ("timestamp", "created_at", "fecha_de_creacion_alarma", "hora_reporte", "fecha_respuesta"):
        df[column] = df[column].str.replace("2026-07", "2024-07", regex=False)
    source_server.alarms_csv = _csv(df)
    source_server._alarms_for = lambda cliente: source_server.alarms_csv

    batch = await build_acquisition(source_server).get_batch(tps, *JULY)
    assert any("fuera del período" in w for w in batch.warnings)
