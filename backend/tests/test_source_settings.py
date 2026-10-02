"""Configuración > Fuente de datos: address, username and password changed from
the app -- stored safely, never echoed back, tested before saving, and applied
to the running provider without a restart."""
import json
import os
import stat
from datetime import datetime

import pytest

from app.config.settings import get_settings
from app.ingestion.client import SourceClient
from app.ingestion.source_settings_store import (
    InvalidSourceSettings,
    SourceSettingsStore,
    effective_source_config,
    normalize_base_url,
)
from app.providers.http_source import HttpSourceDataProvider
from app.services.company_registry import get_company_registry
from tests.conftest import auth_headers
from tests.source_fakes import (
    TEST_PASSWORD,
    TEST_USERNAME,
    FakeSourceServer,
    build_acquisition,
)

ENV_URL = "https://source.test"


@pytest.fixture
def source_env(monkeypatch):
    """SOURCE_* as backend/.env would provide them (env vars win over the real .env file)."""
    monkeypatch.setenv("SOURCE_BASE_URL", ENV_URL)
    monkeypatch.setenv("SOURCE_USERNAME", TEST_USERNAME)
    monkeypatch.setenv("SOURCE_PASSWORD", TEST_PASSWORD)
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def server():
    return FakeSourceServer(b"id,cliente\n1,X\n")


@pytest.fixture
def api(api_client, source_env, server, monkeypatch):
    """The settings API, its connection tests answered by the in-memory source."""
    monkeypatch.setattr(
        "app.api.source_settings._make_client", lambda config: SourceClient(config, transport=server.transport)
    )
    return api_client


def _store() -> SourceSettingsStore:
    return SourceSettingsStore(get_settings().source_settings_path)


# ---- store ------------------------------------------------------------------


def test_saved_values_override_the_environment_and_the_file_is_private(source_env):
    store = _store()
    store.save(base_url="http://10.9.9.9/ProyectoSOC/views/", username="otro", password="nueva-clave", updated_by="master")

    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600  # only the backend's OS user can read the password
    assert [p.name for p in store.path.parent.iterdir() if p.name.startswith(".source_settings.")] == []

    config = effective_source_config(get_settings())
    assert (config.base_url, config.username, config.password) == ("http://10.9.9.9/ProyectoSOC/views", "otro", "nueva-clave")
    assert "nueva-clave" not in repr(store.load()) and "nueva-clave" not in repr(config)


def test_without_saved_values_the_environment_is_used(source_env):
    config = effective_source_config(get_settings())
    assert (config.base_url, config.username, config.password) == (ENV_URL, TEST_USERNAME, TEST_PASSWORD)


def test_an_unreadable_settings_file_falls_back_to_the_environment(source_env):
    _store().path.write_text("{ not json", encoding="utf-8")
    assert effective_source_config(get_settings()).base_url == ENV_URL


@pytest.mark.parametrize(
    "value, hint",
    [
        ("", "Indica la dirección"),
        ("10.2.85.8/ProyectoSOC/views", "http://"),
        ("ftp://10.2.85.8", "http://"),
        ("http://user:pw@10.2.85.8", "No incluyas usuario"),
        ("http://10.2.85.8/views?cliente=X", "parámetros"),
        ("http://10.2.85.8:99999", "puerto"),
        ("http:///views", "servidor"),
    ],
)
def test_bad_addresses_are_rejected_with_a_readable_reason(value, hint):
    with pytest.raises(InvalidSourceSettings) as excinfo:
        normalize_base_url(value)
    assert hint in str(excinfo.value)


def test_addresses_keep_their_path_and_lose_the_trailing_slash():
    assert normalize_base_url(" http://10.2.85.8/ProyectoSOC/views/ ") == "http://10.2.85.8/ProyectoSOC/views"
    assert normalize_base_url("https://soc.example:8443") == "https://soc.example:8443"


# ---- API ----------------------------------------------------------------------


def test_every_route_requires_the_app_login(api):
    assert api.get("/api/source-settings").status_code == 401
    assert api.post("/api/source-settings/test", json={"base_url": ENV_URL, "username": "x"}).status_code == 401
    assert api.put("/api/source-settings", json={"base_url": ENV_URL, "username": "x"}).status_code == 401


def test_current_settings_never_include_the_password(api):
    res = api.get("/api/source-settings", headers=auth_headers(api))

    assert res.status_code == 200
    assert res.json() == {
        "base_url": ENV_URL,
        "username": TEST_USERNAME,
        "password_set": True,
        "uses_https": True,
        "origin": "env",
        "updated_at": None,
        "updated_by": None,
        "provider_active": False,  # tests run with DATA_PROVIDER=mock
    }
    assert TEST_PASSWORD not in res.text


def test_connection_test_logs_in_with_the_proposed_values_without_saving_them(api, server):
    res = api.post(
        "/api/source-settings/test",
        headers=auth_headers(api),
        json={"base_url": "https://10.20.30.40/views", "username": TEST_USERNAME},  # password: keep current
    )

    body = res.json()
    assert body["ok"] is True and body["login_method"] == "basic"
    assert "10.20.30.40" in body["message"]
    served = server.alarm_requests[-1]
    assert served.url.host == "10.20.30.40" and served.url.params["limite"] == "1"
    assert not _store().path.exists()


def test_a_rejected_login_is_reported_without_echoing_the_password(api, server):
    res = api.post(
        "/api/source-settings/test",
        headers=auth_headers(api),
        json={"base_url": ENV_URL, "username": TEST_USERNAME, "password": "clave-equivocada"},
    )

    body = res.json()
    assert body["ok"] is False and "rechazó" in body["message"]
    assert "clave-equivocada" not in res.text


def test_saving_tests_first_and_does_not_store_values_that_do_not_work(api, server):
    res = api.put(
        "/api/source-settings",
        headers=auth_headers(api),
        json={"base_url": ENV_URL, "username": TEST_USERNAME, "password": "clave-equivocada"},
    )

    assert res.json()["saved"] is False and res.json()["test"]["ok"] is False
    assert not _store().path.exists()


def test_saving_can_skip_the_test_when_the_source_is_unreachable(api, server):
    res = api.put(
        "/api/source-settings",
        headers=auth_headers(api),
        json={"base_url": "http://10.2.85.9/ProyectoSOC/views", "username": "nuevo", "password": "otra", "skip_connection_test": True},
    )

    body = res.json()
    assert body["saved"] is True and body["test"] is None
    assert body["settings"]["base_url"] == "http://10.2.85.9/ProyectoSOC/views"
    assert body["settings"]["origin"] == "app" and body["settings"]["updated_by"] == "master"
    assert body["settings"]["uses_https"] is False
    assert server.requests == []  # nothing was sent anywhere
    assert "otra" not in res.text


def test_an_empty_password_keeps_the_current_one(api, server):
    res = api.put(
        "/api/source-settings",
        headers=auth_headers(api),
        json={"base_url": "https://10.20.30.40", "username": TEST_USERNAME, "password": ""},
    )

    assert res.json()["saved"] is True, res.json()
    saved = json.loads(_store().path.read_text(encoding="utf-8"))
    assert saved["password"] == TEST_PASSWORD and saved["base_url"] == "https://10.20.30.40"


def test_invalid_input_is_a_400_with_the_reason(api):
    res = api.put(
        "/api/source-settings", headers=auth_headers(api), json={"base_url": "10.2.85.8", "username": TEST_USERNAME}
    )
    assert res.status_code == 400 and "http://" in res.json()["detail"]


def test_connection_tests_are_rate_limited_to_protect_the_source_account(api):
    headers = auth_headers(api)
    payload = {"base_url": ENV_URL, "username": TEST_USERNAME}
    codes = [api.post("/api/source-settings/test", headers=headers, json=payload).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


async def test_saved_values_reach_the_running_provider_without_a_restart(api, server, fake_supabase, monkeypatch):
    fake_supabase.table("in_companies").insert(
        {"id": "thomas-tgs-tps", "name": "THOMAS TGS TPS", "source_client": "THOMAS TGS-TPS", "is_active": True}
    )
    get_company_registry().invalidate()
    provider = HttpSourceDataProvider(build_acquisition(server, base_url=ENV_URL), get_company_registry())
    monkeypatch.setattr("app.api.source_settings._running_provider", lambda: provider)
    company = await get_company_registry().get(name="THOMAS TGS TPS")
    start, end = datetime(2026, 7, 1), datetime(2026, 7, 31, 23, 59, 59)
    await provider.get_security_alerts(company.id, start, end)  # session + cache on the old address

    res = api.put(
        "/api/source-settings",
        headers=auth_headers(api),
        json={"base_url": "https://10.20.30.40/albatrus", "username": TEST_USERNAME, "skip_connection_test": True},
    )
    assert res.json()["saved"] is True
    server.served.clear()
    await provider.get_security_alerts(company.id, start, end)

    request = server.alarm_requests[0]  # not served from the old cache
    assert request.url.host == "10.20.30.40" and request.url.path == "/albatrus/detallado_alarmas.php"
    assert "cookie" not in request.headers  # the old server's session was dropped
