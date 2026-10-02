"""Audit log, observability, user preferences, request ids and secret redaction."""
import json

from app.security.redaction import REDACTED, redact, redact_text
from app.services.observability import get_observability, route_template
from tests.conftest import ADMIN_AUTH_ID, auth_headers, parse_sse_events

# ---- redaction --------------------------------------------------------------------


def test_redaction_removes_secrets_whatever_the_call_site_passes():
    context = {
        "password": "p4ss",
        "SOURCE_PASSWORD": "x",
        "access_token": "eyJ...",
        "Authorization": "Bearer abc.def.ghi",
        "password_changed": True,  # a flag reveals nothing: kept
        "nested": {"api_key": "k", "host": "10.2.85.8"},
        "note": "header was Bearer abcdefghijklmnop and url http://user:pw@10.2.85.8/x",
    }
    out = redact(context)
    assert out["password"] == REDACTED and out["SOURCE_PASSWORD"] == REDACTED
    assert out["access_token"] == REDACTED and out["Authorization"] == REDACTED
    assert out["password_changed"] is True
    assert out["nested"] == {"api_key": REDACTED, "host": "10.2.85.8"}
    assert "abcdefghijklmnop" not in out["note"] and "user:pw" not in out["note"]


def test_jwts_are_redacted_from_free_text():
    jwt_like = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLWhlcmU"
    assert jwt_like not in redact_text(f"token {jwt_like} rejected")


def test_route_templates_hide_identifiers():
    assert route_template("/api/conversations/conv-1a2b3c4d5e6f/messages") == "/api/conversations/{id}/messages"
    assert route_template("/api/reports/report-0123456789ab/download") == "/api/reports/{id}/download"


# ---- audit log ----------------------------------------------------------------------


def test_report_generation_and_download_are_audited(api_client, fake_supabase):
    headers = auth_headers(role="operator")
    res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "ready", result
    report_id = result["report"]["report_id"]
    assert api_client.get(f"/api/reports/{report_id}/download", headers=headers).status_code == 200

    actions = [r["action"] for r in fake_supabase.audit()]
    assert actions[:3] == ["report.generation_requested", "report.generated", "report.downloaded"]
    generated = fake_supabase.audit("report.generated")[0]
    assert generated["actor_email"] == "operador@soc.test" and generated["resource_id"] == report_id
    assert generated["operation_id"].startswith("req-")
    conversation = fake_supabase.table("in_conversations").rows[0]
    assert conversation["created_by"] == "user-operator"
    execution = fake_supabase.table("in_agent_executions").rows[0]
    assert execution["triggered_by"] == "user-operator"


def test_admins_query_the_audit_log_with_filters(api_client, fake_supabase):
    for event in ("login", "logout"):
        api_client.post("/api/me/session-events", headers=auth_headers(role="operator"), json={"event": event})
    api_client.post("/api/auth/events", json={"action": "login_failed", "email": "x@soc.test", "reason": "bad"})

    page = api_client.get("/api/audit", headers=auth_headers(), params={"module": "auth"}).json()
    assert page["total"] == 3 and {i["action"] for i in page["items"]} == {"auth.login", "auth.logout", "auth.login_failed"}

    failures = api_client.get("/api/audit", headers=auth_headers(), params={"result": "failure"}).json()
    assert [i["action"] for i in failures["items"]] == ["auth.login_failed"]

    search = api_client.get("/api/audit", headers=auth_headers(), params={"q": "operador"}).json()
    assert search["total"] == 2

    by_prefix = api_client.get("/api/audit", headers=auth_headers(), params={"action": "auth"}).json()
    assert by_prefix["total"] == 3


def test_free_text_cannot_inject_postgrest_operators(api_client, fake_supabase):
    res = api_client.get("/api/audit", headers=auth_headers(), params={"q": "x),actor_auth_id.is.null,(y"})
    assert res.status_code == 200  # parentheses/commas are stripped before building or=(...)


def test_audit_export_is_csv_and_is_itself_audited(api_client, fake_supabase):
    api_client.post("/api/me/session-events", headers=auth_headers(), json={"event": "login"})
    res = api_client.get("/api/audit/export.csv", headers=auth_headers())
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "auth.login" in res.text
    assert fake_supabase.audit("audit.exported")


# ---- preferences --------------------------------------------------------------------


def test_preferences_default_then_persist_per_user(api_client, fake_supabase):
    headers = auth_headers(role="operator")
    assert api_client.get("/api/me/preferences", headers=headers).json()["theme"] == "system"

    saved = api_client.put(
        "/api/me/preferences",
        headers=headers,
        json={"theme": "dark", "preferences": {"default_format": "pdf", "start_page": "/asistente"}},
    ).json()
    assert saved["theme"] == "dark" and saved["preferences"]["default_format"] == "pdf"

    again = api_client.get("/api/me/preferences", headers=headers).json()
    assert again["theme"] == "dark" and again["preferences"]["start_page"] == "/asistente"
    # another member keeps their own
    assert api_client.get("/api/me/preferences", headers=auth_headers()).json()["theme"] == "system"
    assert fake_supabase.audit("settings.preferences_updated")


def test_invalid_preferences_are_rejected(api_client):
    res = api_client.put("/api/me/preferences", headers=auth_headers(), json={"theme": "neon"})
    assert res.status_code == 422


# ---- observability -------------------------------------------------------------------


def test_requests_carry_an_id_and_are_measured(api_client):
    res = api_client.get("/api/me", headers=auth_headers())
    assert res.headers["x-request-id"].startswith("req-")

    body = api_client.get("/api/observability/requests", headers=auth_headers()).json()
    first = body["items"][-1]
    assert first["route"] == "/api/me" and first["status"] == 200 and first["actor_email"] == "admin@soc.test"
    assert body["stats"]["total"] >= 1


def test_auth_failures_show_up_in_request_stats(api_client):
    api_client.get("/api/me", headers={"Authorization": "Bearer garbage"})
    stats = api_client.get("/api/observability/requests", headers=auth_headers()).json()["stats"]
    assert stats["auth_failures"] == 1


def test_report_runs_become_ops_events_and_feed_the_summary(api_client, fake_supabase):
    api_client.post(
        "/api/reports/generate",
        headers=auth_headers(),
        json={"company": "ACME Corp", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    events = fake_supabase.table("in_ops_events").rows
    completed = [e for e in events if e["event"] == "report.generation.completed"]
    assert completed and completed[0]["level"] == "INFO" and completed[0]["actor_auth_id"] == ADMIN_AUTH_ID
    assert completed[0]["duration_ms"] is not None

    summary = api_client.get("/api/observability/summary", headers=auth_headers()).json()
    assert summary["events_24h"]["by_category"].get("report") >= 1
    assert summary["agent_24h"]["total"] == 1 and summary["reports_24h"] == 1

    listed = api_client.get("/api/observability/events", headers=auth_headers(), params={"category": "report"}).json()
    assert listed["total"] >= 1


def test_ops_events_never_persist_secrets(api_client, fake_supabase):
    import asyncio

    from app.security.context import CurrentUser, set_current_user

    async def emit():
        set_current_user(CurrentUser(ADMIN_AUTH_ID, "user-admin", "admin@soc.test", "admin"))
        await get_observability().emit(
            "ERROR", "source", "source.test", "falló con Bearer abcdefghijklmnopqrst",
            context={"password": "p4ss", "host": "10.2.85.8"},
        )

    asyncio.run(emit())
    stored = json.dumps(fake_supabase.table("in_ops_events").rows)
    assert "p4ss" not in stored and "abcdefghijklmnopqrst" not in stored and "10.2.85.8" in stored


def test_recent_reports_are_listed_for_inicio(api_client, fake_supabase):
    api_client.post(
        "/api/reports/generate",
        headers=auth_headers(),
        json={"company": "ACME Corp", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    items = api_client.get("/api/reports", headers=auth_headers(role="operator")).json()
    assert len(items) == 1 and items[0]["company"] == "ACME Corp" and items[0]["version"] == 1
