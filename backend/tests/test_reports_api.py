"""First HTTP-level test in the repo (ARCHITECTURE_ASSESSMENT.md flagged zero
API-layer coverage as a real gap). Exercises the deterministic-flow endpoint
end to end through FastAPI's TestClient -- auth, SSE streaming, persistence,
and download -- with Supabase mocked (no network) and the LLM stubbed."""
import shutil

import pytest

from tests.conftest import auth_headers, parse_sse_events


def test_unauthenticated_request_is_rejected(api_client):
    res = api_client.get("/api/companies")
    assert res.status_code == 401


def test_companies_and_templates_are_listed(api_client):
    headers = auth_headers(api_client)
    companies = api_client.get("/api/companies", headers=headers).json()
    assert any(c["id"] == "acme-corp" and c["name"] == "ACME Corp" for c in companies)

    templates = api_client.get("/api/report-templates", headers=headers).json()
    assert any(t["key"] == "csoc_mensual" for t in templates)


def test_generate_report_end_to_end_and_download(api_client):
    headers = auth_headers(api_client)

    res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2025-08-01", "end_date": "2025-08-31"},
    )
    assert res.status_code == 200, res.text
    events = parse_sse_events(res.text)

    progress_events = [e for e in events if e["event"] == "progress"]
    assert len(progress_events) >= 5  # conversation_created + the 5 pipeline stages

    result = events[-1]
    assert result["event"] == "result"
    assert result["status"] == "ready", result
    report = result["report"]
    assert report["section_count"] > 0
    assert report["objective"]

    download = api_client.get(f"/api/reports/{report['report_id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(download.content) > 0


def test_generate_report_with_unknown_company_returns_error_result(api_client):
    headers = auth_headers(api_client)
    res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "No Existe SA", "start_date": "2025-08-01", "end_date": "2025-08-31"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    assert events[-1]["status"] == "error"
    assert events[-1]["report"] is None


def test_generate_report_rejects_unsupported_format_before_any_io(api_client):
    headers = auth_headers(api_client)
    res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2025-08-01", "end_date": "2025-08-31", "format": "xlsx"},
    )
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    assert events[-1]["status"] == "error"
    assert any("xlsx" in e.lower() for e in events[-1]["errors"])


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed in this environment")
def test_generate_report_as_pdf_end_to_end_and_download(api_client):
    headers = auth_headers(api_client)
    res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2025-08-01", "end_date": "2025-08-31", "format": "pdf"},
    )
    assert res.status_code == 200, res.text
    events = parse_sse_events(res.text)
    result = events[-1]
    assert result["status"] == "ready", result
    assert result["report"]["format"] == "pdf"

    download = api_client.get(f"/api/reports/{result['report']['report_id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content[:4] == b"%PDF"
