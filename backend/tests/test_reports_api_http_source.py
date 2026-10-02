"""The two product entry points (company selector + form generation) end to end
through the API, on data delivered by the remote source (in-memory fake)."""
import pytest

from app.providers.http_source import HttpSourceDataProvider
from app.services.company_registry import get_company_registry
from tests.conftest import auth_headers, parse_sse_events
from tests.source_fakes import build_acquisition


@pytest.fixture
def source_backed_api(api_client, fake_supabase, source_server, monkeypatch):
    """api_client with the HTTP provider serving the pipeline and the TPS
    company present in the (fake) in_companies table the registry reads."""
    fake_supabase.table("in_companies").insert(
        {
            "id": "thomas-tgs-tps",
            "name": "THOMAS TGS TPS",
            "logo_key": "Thomas TPS",
            "consecutivo": "TGS TPS",
            "source_client": "THOMAS TGS-TPS",
            "is_active": True,
        }
    )
    get_company_registry().invalidate()
    provider = HttpSourceDataProvider(build_acquisition(source_server), get_company_registry())
    monkeypatch.setattr("app.services.report.collection.get_data_provider", lambda: provider)
    return api_client


def test_company_selector_lists_the_registered_companies_with_their_logo_and_series(source_backed_api):
    companies = source_backed_api.get("/api/companies", headers=auth_headers(source_backed_api)).json()

    tps = next(c for c in companies if c["id"] == "thomas-tgs-tps")
    assert tps == {"id": "thomas-tgs-tps", "name": "THOMAS TGS TPS", "logo_key": "Thomas TPS", "consecutivo": "TGS TPS"}


def test_form_generation_requests_the_source_with_the_registered_name_and_delivers_a_report(
    source_backed_api, source_server
):
    headers = auth_headers(source_backed_api)

    res = source_backed_api.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "THOMAS TGS TPS", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    assert res.status_code == 200, res.text
    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "ready", result
    assert "THOMAS TGS TPS" in result["message"]
    assert source_server.alarm_requests[0].url.params["cliente"] == "THOMAS TGS-TPS"
    assert source_backed_api.get(f"/api/reports/{result['report']['report_id']}/download", headers=headers).status_code == 200


def test_source_failure_ends_the_stream_with_a_readable_error_and_no_credentials(source_backed_api, source_server):
    source_server.password = "changed-by-admin"

    res = source_backed_api.post(
        "/api/reports/generate",
        headers=auth_headers(source_backed_api),
        json={"company": "THOMAS TGS TPS", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    assert res.status_code == 200
    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "error" and result["report"] is None
    assert "rechazó las credenciales" in result["message"] and "SOURCE_PASSWORD" in result["message"]
    assert "changed-by-admin" not in res.text and "not-a-real-password" not in res.text


def test_ambiguous_company_in_the_form_lists_the_options(source_backed_api, fake_supabase):
    fake_supabase.table("in_companies").insert({"id": "peru-sss", "name": "PERU SSS", "is_active": True})
    fake_supabase.table("in_companies").insert({"id": "thomas-tgs-peru", "name": "THOMAS TGS PERU", "is_active": True})
    get_company_registry().invalidate()

    res = source_backed_api.post(
        "/api/reports/generate",
        headers=auth_headers(source_backed_api),
        json={"company": "peru", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "error"
    assert "PERU SSS" in result["message"] and "THOMAS TGS PERU" in result["message"]
