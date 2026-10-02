"""Fuente de Datos: settings in Supabase (password encrypted), admin-only editing,
connection tests, audit of every change, runtime pickup of a new IP, and the
"configure the source first" flow."""
from datetime import datetime

import pytest

from app.ingestion.client import SourceClient
from app.providers.http_source import HttpSourceDataProvider
from app.services import source_settings_service as sss
from app.services.company_registry import get_company_registry
from tests.conftest import auth_headers, parse_sse_events
from tests.source_fakes import (
    TEST_PASSWORD,
    TEST_USERNAME,
    FakeSourceServer,
    build_acquisition,
)

PAYLOAD = {
    "scheme": "https",
    "host": "source.test",
    "base_path": "",
    "alarms_path": "/detallado_alarmas.php",
    "notifications_path": "/indicadores.php",
    "username": TEST_USERNAME,
    "password": TEST_PASSWORD,
    "verify_tls": True,
    "timeout_seconds": 30,
    "alarms_limit": 1000,
    "reconcile_indicators": True,
}


@pytest.fixture
def server():
    return FakeSourceServer(b"id,cliente\n1,X\n")


@pytest.fixture
def api(api_client, server, monkeypatch):
    monkeypatch.setattr(
        "app.api.source_settings._make_client", lambda config: SourceClient(config, transport=server.transport)
    )
    return api_client


def _row(fake_supabase) -> dict | None:
    rows = fake_supabase.table("in_source_settings").rows
    return rows[0] if rows else None


# ---- validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "host, hint",
    [
        ("", "Indica la IP"),
        ("http://10.2.85.8", "sin http://"),
        ("10.2.85.8/ProyectoSOC", "sin http://"),
        ("10.2.85.8:99999", "puerto"),
        ("bad_host!", "no es una IP"),
        ("user@10.2.85.8", "sin http://"),
    ],
)
def test_bad_hosts_are_rejected_with_a_readable_reason(host, hint):
    with pytest.raises(sss.SourceSettingsError) as excinfo:
        sss.normalize_host(host)
    assert hint in str(excinfo.value)


def test_hosts_ips_ports_and_ipv6_are_accepted():
    assert sss.normalize_host(" 10.2.85.8 ") == "10.2.85.8"
    assert sss.normalize_host("Soc.Example.com:8443") == "soc.example.com:8443"
    assert sss.normalize_host("[fd00::1]:8080") == "[fd00::1]:8080"


def test_endpoints_accept_relative_paths_or_full_urls_but_not_parameters():
    assert sss.normalize_endpoint("detallado_alarmas.php", "Alertas") == "/detallado_alarmas.php"
    assert sss.normalize_endpoint("https://otro.test/x.php", "Alertas") == "https://otro.test/x.php"
    with pytest.raises(sss.SourceSettingsError):
        sss.normalize_endpoint("/x.php?cliente=TPS", "Alertas")
    with pytest.raises(sss.SourceSettingsError):
        sss.normalize_endpoint("https://u:p@otro.test/x.php", "Alertas")
    with pytest.raises(sss.SourceSettingsError):
        sss.normalize_base_path("/../etc")


# ---- storage ---------------------------------------------------------------------


def test_saving_stores_the_password_encrypted_and_never_returns_it(api, fake_supabase):
    res = api.put("/api/source-settings", headers=auth_headers(), json=PAYLOAD)

    body = res.json()
    assert res.status_code == 200 and body["saved"] is True and body["test"]["ok"] is True
    row = _row(fake_supabase)
    assert row["host"] == "source.test" and row["updated_by"] == "user-admin" and row["revision"] == 1
    assert TEST_PASSWORD not in str(row) and row["password_ciphertext"]
    assert sss.decrypt_password(row["password_ciphertext"]) == TEST_PASSWORD
    assert TEST_PASSWORD not in res.text and body["settings"]["password_set"] is True
    assert body["settings"]["alarms_url"] == "https://source.test/detallado_alarmas.php"
    assert body["settings"]["notifications_url"] == "https://source.test/indicadores.php"


def test_get_shows_values_but_only_whether_a_password_exists(api, fake_supabase):
    api.put("/api/source-settings", headers=auth_headers(), json=PAYLOAD)
    res = api.get("/api/source-settings", headers=auth_headers())
    assert res.json()["password_set"] is True and res.json()["origin"] == "app"
    assert TEST_PASSWORD not in res.text and "ciphertext" not in res.text


def test_an_empty_password_keeps_the_stored_one(api, fake_supabase):
    api.put("/api/source-settings", headers=auth_headers(), json=PAYLOAD)
    first = _row(fake_supabase)["password_ciphertext"]

    res = api.put(
        "/api/source-settings",
        headers=auth_headers(),
        json={**PAYLOAD, "password": "", "timeout_seconds": 45, "expected_revision": 1},
    )

    assert res.json()["saved"] is True
    assert _row(fake_supabase)["password_ciphertext"] == first and _row(fake_supabase)["timeout_seconds"] == 45


def test_saving_does_not_store_values_that_fail_the_connection_test(api, fake_supabase):
    res = api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "password": "mala"})
    assert res.json()["saved"] is False and "rechazó" in res.json()["test"]["message"]
    assert _row(fake_supabase) is None
    assert "mala" not in res.text


def test_saving_without_testing_when_the_source_is_unreachable(api, server, fake_supabase):
    res = api.put(
        "/api/source-settings",
        headers=auth_headers(),
        json={**PAYLOAD, "scheme": "http", "host": "10.2.85.9", "base_path": "/ProyectoSOC/views",
              "skip_connection_test": True},
    )
    assert res.json()["saved"] is True and res.json()["test"] is None
    assert server.requests == []
    assert res.json()["settings"]["alarms_url"] == "http://10.2.85.9/ProyectoSOC/views/detallado_alarmas.php"


def test_two_admins_cannot_silently_overwrite_each_other(api, fake_supabase):
    api.put("/api/source-settings", headers=auth_headers(), json=PAYLOAD)
    api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "password": "", "expected_revision": 1})
    stale = api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "password": "", "expected_revision": 1})
    assert stale.status_code == 409


def test_operators_cannot_read_test_or_change_the_source(api, fake_supabase):
    headers = auth_headers(role="operator")
    assert api.get("/api/source-settings", headers=headers).status_code == 403
    assert api.post("/api/source-settings/test", headers=headers, json=PAYLOAD).status_code == 403
    assert api.put("/api/source-settings", headers=headers, json=PAYLOAD).status_code == 403
    assert _row(fake_supabase) is None


def test_invalid_input_is_a_400_with_the_reason(api):
    res = api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "host": "http://10.2.85.8"})
    assert res.status_code == 400 and "sin http://" in res.json()["detail"]


def test_connection_tests_are_rate_limited_to_protect_the_source_account(api):
    codes = [api.post("/api/source-settings/test", headers=auth_headers(), json=PAYLOAD).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_without_an_encryption_key_the_password_is_not_stored(api, monkeypatch, fake_supabase):
    monkeypatch.setenv("SOURCE_SECRET_KEY", "")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    res = api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "skip_connection_test": True})
    assert res.status_code == 400 and "SOURCE_SECRET_KEY" in res.json()["detail"]
    assert _row(fake_supabase) is None


# ---- audit -------------------------------------------------------------------------


def test_every_change_is_audited_without_the_password(api, fake_supabase):
    api.put("/api/source-settings", headers=auth_headers(), json=PAYLOAD)
    api.put(
        "/api/source-settings",
        headers=auth_headers(),
        json={**PAYLOAD, "host": "10.20.30.40", "password": "", "skip_connection_test": True},
    )

    tests = fake_supabase.audit("source.connection_tested")
    assert tests and tests[0]["result"] == "success" and tests[0]["actor_email"] == "admin@soc.test"
    updates = fake_supabase.audit("source.settings_updated")
    assert len(updates) == 2
    assert updates[1]["context"]["changes"]["host"] == {"antes": "source.test", "despues": "10.20.30.40"}
    assert updates[1]["context"]["password_changed"] is False
    moved = fake_supabase.audit("source.address_changed")
    assert moved and moved[-1]["context"] == {"antes": "https://source.test", "despues": "https://10.20.30.40"}
    assert TEST_PASSWORD not in str(fake_supabase.table("in_audit_log").rows)


# ---- runtime pickup ------------------------------------------------------------------


async def test_a_new_ip_reaches_the_running_provider_without_a_restart(api, fake_supabase, monkeypatch):
    source = FakeSourceServer(__import__("tests.conftest", fromlist=["x"]).ALARMS_FIXTURE_PATH.read_bytes())
    fake_supabase.table("in_companies").insert(
        {"id": "thomas-tgs-tps", "name": "THOMAS TGS TPS", "source_client": "THOMAS TGS-TPS", "is_active": True}
    )
    get_company_registry().invalidate()
    acquisition = build_acquisition(source, base_url="https://source.test")
    acquisition._config_provider = sss.effective_config
    provider = HttpSourceDataProvider(acquisition, get_company_registry())
    api.put("/api/source-settings", headers=auth_headers(), json={**PAYLOAD, "skip_connection_test": True})

    # the request context of a signed-in member, as during a report
    from app.security.context import CurrentUser, set_access_token, set_current_user

    set_access_token("token-admin")
    set_current_user(CurrentUser("a", "user-admin", "admin@soc.test", "admin"))
    company = await get_company_registry().get(name="THOMAS TGS TPS")
    start, end = datetime(2026, 7, 1), datetime(2026, 7, 31, 23, 59, 59)
    await provider.get_security_alerts(company.id, start, end)
    assert source.alarm_requests[-1].url.host == "source.test"

    api.put(
        "/api/source-settings",
        headers=auth_headers(),
        json={**PAYLOAD, "host": "10.20.30.40", "base_path": "/albatrus", "password": "",
              "skip_connection_test": True},
    )
    source.served.clear()
    await provider.get_security_alerts(company.id, start, end)

    request = source.alarm_requests[0]  # fetched again: the old cache was dropped
    assert request.url.host == "10.20.30.40" and request.url.path == "/albatrus/detallado_alarmas.php"
    assert "cookie" not in request.headers  # and so was the old server's session


# ---- "configure the source first" ---------------------------------------------------------


def test_status_tells_every_member_what_is_missing(api, monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "http")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    body = api.get("/api/source-settings/status", headers=auth_headers(role="operator")).json()
    assert body["configured"] is False
    assert body["missing"] == ["la IP o el host del servidor", "el usuario", "la contraseña"]


def test_a_report_is_not_attempted_until_the_source_is_configured(api, fake_supabase, monkeypatch, server):
    monkeypatch.setenv("DATA_PROVIDER", "http")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    res = api.post(
        "/api/reports/generate",
        headers=auth_headers(role="operator"),
        json={"company": "ACME Corp", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    result = parse_sse_events(res.text)[-1]
    assert result["status"] == "error" and result["error_code"] == "source_not_configured"
    assert "Fuente de Datos" in result["message"] and "la contraseña" in result["message"]
    assert fake_supabase.table("in_conversations").rows == []  # nothing was started
    assert server.requests == []  # and nothing was sent to the source
    assert fake_supabase.audit("report.generation_blocked")
