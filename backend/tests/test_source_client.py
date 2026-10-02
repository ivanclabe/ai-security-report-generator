"""SourceClient: login (Basic Auth when challenged), session reuse, expiration/renewal, address
changes and failure modes -- against the in-memory fake source, no network."""
from datetime import datetime

import httpx
import pytest

from app.ingestion.errors import (
    SourceAuthenticationError,
    SourceConfigError,
    SourceError,
    SourceFormatError,
    SourceUnavailableError,
)
from app.ingestion.requests import build_alarms_request, build_indicators_request
from tests.source_fakes import (
    TEST_PASSWORD,
    TEST_USERNAME,
    FakeSourceServer,
    build_client,
    make_config,
)

START = datetime(2026, 7, 1, 0, 0)
END = datetime(2026, 7, 31, 23, 59)


@pytest.fixture
def server():
    return FakeSourceServer(b"id,cliente\n1,X\n")


def _alarms(client):
    return build_alarms_request(client.config, "THOMAS TGS-TPS", START, END)


# ---- login ----------------------------------------------------------------


async def test_login_sends_basic_auth_and_never_puts_credentials_in_the_url(server):
    client = build_client(server)
    response = await client.fetch(_alarms(client))

    assert response.status_code == 200
    assert response.content_type.startswith("text/csv")
    challenge, sent = server.requests
    assert "authorization" not in challenge.headers  # nothing is sent until the server asks for it
    assert sent.headers["authorization"].startswith("Basic ")
    assert TEST_PASSWORD not in str(sent.url) and TEST_USERNAME not in str(sent.url)
    assert not sent.url.username and not sent.url.password
    assert client.last_login_method == "basic"


async def test_once_basic_auth_was_asked_for_it_is_sent_up_front(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    await client.fetch(_alarms(client))

    assert len(server.requests) == 3  # challenge, ok, ok -- no second handshake
    assert server.requests[2].headers["authorization"].startswith("Basic ")


async def test_basic_auth_is_never_sent_to_a_server_that_does_not_ask_for_it():
    # The real source uses a login form over plain http: a speculative Basic header
    # would put the password on the wire with every request.
    server = FakeSourceServer(b"id,cliente\n1,X\n")
    server.form_login = True
    client = build_client(server)
    await client.fetch(_alarms(client))
    await client.fetch(_alarms(client))

    assert all("authorization" not in r.headers for r in server.requests)
    assert len(server.login_posts) == 1  # the password travelled once, in the login form


async def test_wrong_credentials_raise_a_clear_error_and_are_not_retried(server):
    client = build_client(server, password="wrong-password")

    with pytest.raises(SourceAuthenticationError) as excinfo:
        await client.fetch(_alarms(client))

    assert "SOURCE_PASSWORD" in str(excinfo.value)  # tells the operator what to fix...
    assert "wrong-password" not in str(excinfo.value)  # ...without ever echoing a secret
    # one attempt with credentials (after the server's challenge): a rejected login is not a
    # reason to hammer the server
    assert [("authorization" in r.headers) for r in server.requests] == [False, True]


async def test_missing_configuration_fails_before_any_request(server):
    client = build_client(server, username="", password="")

    with pytest.raises(SourceConfigError) as excinfo:
        await client.fetch(_alarms(client))

    assert "SOURCE_USERNAME" in str(excinfo.value) and "SOURCE_PASSWORD" in str(excinfo.value)
    assert server.requests == []


def test_config_never_exposes_the_password_in_repr():
    config = make_config()
    assert TEST_PASSWORD not in repr(config)
    assert TEST_PASSWORD not in str(config)


def test_password_comes_from_settings_as_a_secret(monkeypatch):
    from app.config.settings import Settings
    from app.ingestion.config import SourceConfig

    monkeypatch.setenv("SOURCE_BASE_URL", "https://10.0.0.5")
    monkeypatch.setenv("SOURCE_USERNAME", "svc")
    monkeypatch.setenv("SOURCE_PASSWORD", "env-secret")
    settings = Settings(_env_file=None)

    assert "env-secret" not in repr(settings)  # SecretStr: safe even if Settings is logged
    config = SourceConfig.from_settings(settings)
    assert (config.base_url, config.username, config.password) == ("https://10.0.0.5", "svc", "env-secret")
    assert config.problems() == []


# ---- session ----------------------------------------------------------------


async def test_session_is_reused_between_requests(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    first_http_client = client._client
    await client.fetch(_alarms(client))

    assert client._client is first_http_client  # same connection pool / cookie jar
    assert server.sessions_issued == 1  # the 2nd request replayed the session cookie
    assert "phpsessid" in server.requests[-1].headers["cookie"].lower()


async def test_expired_session_is_renewed_transparently_once(server):
    client = build_client(server)
    await client.fetch(_alarms(client))  # logged in
    server.fail_next.append(401)  # session expires server-side; credentials are still valid

    response = await client.fetch(_alarms(client))

    assert response.status_code == 200
    assert len(server.requests) == 4  # challenge, ok, 401, retried-ok
    assert server.sessions_issued == 2  # a brand-new session after dropping the stale cookie


async def test_session_that_cannot_be_renewed_fails_instead_of_looping(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    server.password = "rotated-by-the-administrator"  # credentials changed while we were logged in

    with pytest.raises(SourceAuthenticationError) as excinfo:
        await client.fetch(_alarms(client))

    assert "expiró" in str(excinfo.value)
    assert len(server.requests) == 4  # challenge, ok, 401, one retry (401) -- then stop


async def test_client_can_be_closed_and_reopened(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    await client.aclose()
    await client.fetch(_alarms(client))
    assert server.sessions_issued == 2


# ---- changing the server's address -----------------------------------------


async def test_changing_the_ip_in_the_config_redirects_requests_without_code_changes(server):
    old = build_client(server, base_url="https://192.168.80.50")
    new = build_client(server, base_url="https://10.20.30.40:8443/albatroz")

    await old.fetch(_alarms(old))
    await new.fetch(_alarms(new))

    first, second = server.served
    assert first.url.host == "192.168.80.50"
    assert first.url.path == "/detallado_alarmas.php"
    assert second.url.host == "10.20.30.40" and second.url.port == 8443
    assert second.url.path == "/albatroz/detallado_alarmas.php"


async def test_endpoint_paths_are_configurable_too(server):
    client = build_client(server, alarms_path="export/alarmas.php")
    request = build_alarms_request(client.config, "X", START, END)
    assert request.url == "https://source.test/export/alarmas.php"


async def test_an_endpoint_can_live_on_another_host_via_an_absolute_path(server):
    client = build_client(
        server,
        base_url="http://10.2.85.8/ProyectoSOC/views",
        indicators_path="https://indicadores.example/views/indicadores.php",
    )
    assert _alarms(client).url == "http://10.2.85.8/ProyectoSOC/views/detallado_alarmas.php"
    indicators = build_indicators_request(client.config, "X", START.date(), END.date())
    assert indicators.url == "https://indicadores.example/views/indicadores.php"


async def test_trailing_slash_in_base_url_is_harmless(server):
    client = build_client(server, base_url="https://192.168.80.50/")
    assert _alarms(client).url == "https://192.168.80.50/detallado_alarmas.php"


async def test_indicators_endpoint_is_reachable_with_the_same_credentials(server):
    client = build_client(server)
    response = await client.fetch(build_indicators_request(client.config, "THOMAS TGS-TPS", START.date(), END.date()))
    assert response.status_code == 200
    assert server.requests[0].url.params["fecha_inicio"] == "2026-07-01"


# ---- failure modes ----------------------------------------------------------


@pytest.mark.parametrize(
    "status, error, expected_hint",
    [
        (403, SourceAuthenticationError, "403"),
        (404, SourceError, "SOURCE_ALARMS_PATH"),
        (500, SourceUnavailableError, "500"),
        (503, SourceUnavailableError, "503"),
        (400, SourceError, "400"),
    ],
)
async def test_http_errors_are_translated_to_actionable_messages(server, status, error, expected_hint):
    server.fail_next.append(status)
    client = build_client(server)

    with pytest.raises(error) as excinfo:
        await client.fetch(_alarms(client))

    assert expected_hint in str(excinfo.value)
    assert "source.test" in str(excinfo.value)


async def test_redirect_to_a_login_page_is_reported_as_an_authentication_problem():
    def handler(request):
        return httpx.Response(302, headers={"Location": "/login.php?next=/detallado_alarmas.php"})

    client = build_client(FakeSourceServer(b""))
    client._transport = httpx.MockTransport(handler)

    with pytest.raises(SourceAuthenticationError) as excinfo:
        await client.fetch(_alarms(client))
    assert "login" in str(excinfo.value)


async def test_timeout_message_names_the_host_and_the_limit(server):
    server.raise_next.append(httpx.ReadTimeout("boom"))
    client = build_client(server, timeout_seconds=7)

    with pytest.raises(SourceUnavailableError) as excinfo:
        await client.fetch(_alarms(client))
    assert "7s" in str(excinfo.value) and "source.test" in str(excinfo.value)
    assert "rango de fechas" in str(excinfo.value)


async def test_connect_timeout_points_to_the_vpn_not_to_a_slow_query(server):
    server.raise_next.append(httpx.ConnectTimeout("timed out"))
    client = build_client(server, timeout_seconds=7)

    with pytest.raises(SourceUnavailableError) as excinfo:
        await client.fetch(_alarms(client))
    message = str(excinfo.value)
    assert "7s" in message and "conectar" in message and "VPN" in message


async def test_unreachable_host_suggests_checking_vpn_and_the_configured_address(server):
    server.raise_next.append(httpx.ConnectError("connection refused"))
    client = build_client(server)

    with pytest.raises(SourceUnavailableError) as excinfo:
        await client.fetch(_alarms(client))
    assert "VPN" in str(excinfo.value) and "SOURCE_BASE_URL" in str(excinfo.value)


async def test_untrusted_certificate_points_to_the_ca_bundle_setting(server):
    server.raise_next.append(httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    client = build_client(server)

    with pytest.raises(SourceUnavailableError) as excinfo:
        await client.fetch(_alarms(client))
    assert "SOURCE_CA_BUNDLE" in str(excinfo.value)


async def test_a_redirect_that_is_not_a_login_is_a_format_error():
    def handler(request):
        return httpx.Response(301, headers={"Location": "https://elsewhere.example/other"})

    client = build_client(FakeSourceServer(b""))
    client._transport = httpx.MockTransport(handler)
    with pytest.raises(SourceFormatError):
        await client.fetch(_alarms(client))
