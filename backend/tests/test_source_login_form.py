"""Login by web form + PHP session (the source's logout/account pages suggest it):
the client discovers the form, posts the configured credentials once, keeps the
session cookie, renews it when it expires, and never loops or leaks."""
from datetime import datetime

import pytest

from app.ingestion.errors import SourceAuthenticationError
from app.ingestion.login_form import find_login_form
from app.ingestion.requests import build_alarms_request
from tests.source_fakes import (
    TEST_PASSWORD,
    TEST_USERNAME,
    FakeSourceServer,
    build_client,
)

START, END = datetime(2026, 7, 1), datetime(2026, 7, 31, 23, 59)


@pytest.fixture
def server():
    server = FakeSourceServer(b"id,cliente,timestamp,created_at\n1,THOMAS TGS-TPS,2026-07-02 10:00:00,2026-07-02 10:05:00\n")
    server.form_login = True
    return server


def _alarms(client):
    return build_alarms_request(client.config, "THOMAS TGS-TPS", START, END)


async def test_redirect_to_login_is_answered_with_one_form_login_and_the_request_is_retried(server):
    client = build_client(server)

    response = await client.fetch(_alarms(client))

    assert response.status_code == 200 and b"THOMAS TGS-TPS" in response.content
    assert client.last_login_method == "form"
    assert len(server.login_posts) == 1
    posted = server.login_posts[0]
    # credentials go in the POST body together with the form's own hidden/CSRF and submit fields
    assert posted == {
        "csrf_token": "csrf-synthetic-token",
        "usuario": TEST_USERNAME,
        "clave": TEST_PASSWORD,
        "ingresar": "1",
    }
    assert all(TEST_PASSWORD not in str(r.url) for r in server.requests)


async def test_the_session_cookie_is_reused_without_logging_in_again(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    await client.fetch(_alarms(client))
    await client.fetch(_alarms(client))
    assert len(server.login_posts) == 1


async def test_an_expired_session_triggers_exactly_one_new_login(server):
    client = build_client(server)
    await client.fetch(_alarms(client))
    server.expire_sessions()

    response = await client.fetch(_alarms(client))

    assert response.status_code == 200
    assert len(server.login_posts) == 2


async def test_login_page_served_with_http_200_is_also_recognized(server):
    server.login_page_with_200 = True
    client = build_client(server)
    response = await client.fetch(_alarms(client))
    assert response.status_code == 200 and len(server.login_posts) == 1


async def test_rejected_form_login_fails_once_without_looping(server):
    client = build_client(server, password="wrong-password")

    with pytest.raises(SourceAuthenticationError) as excinfo:
        await client.fetch(_alarms(client))

    assert len(server.login_posts) == 1  # one attempt only: never lock the service account
    assert "SOURCE_PASSWORD" in str(excinfo.value) and "wrong-password" not in str(excinfo.value)


async def test_credentials_are_never_posted_to_another_host(server):
    server.login_form_action = "https://phishing.example/steal.php"
    client = build_client(server)

    with pytest.raises(SourceAuthenticationError) as excinfo:
        await client.fetch(_alarms(client))

    assert "otro host" in str(excinfo.value)
    assert server.login_posts == []
    assert all(r.url.host == "source.test" for r in server.requests)


async def test_a_redirect_to_another_host_is_not_followed(server):
    import httpx

    def handler(request):
        return httpx.Response(302, headers={"Location": "https://elsewhere.example/login.php"})

    client = build_client(server)
    client._transport = httpx.MockTransport(handler)
    with pytest.raises(SourceAuthenticationError):  # reported as a login redirect, never followed
        await client.fetch(_alarms(client))


# ---- the form reader on its own ---------------------------------------------------


def test_form_reader_takes_action_hidden_fields_and_the_right_inputs():
    page = """<form action="/app/login.php" method="post">
        <input type="hidden" name="token" value="abc">
        <input type="email" name="correo"><input type="text" name="telefono">
        <input type="password" name="pwd"><input type="submit" name="entrar" value="Entrar">
        <input type="checkbox" name="recordar"></form>"""
    form = find_login_form(page, "http://10.2.85.8/ProyectoSOC/public/index.php")

    assert form.action == "http://10.2.85.8/app/login.php"
    assert (form.username_field, form.password_field) == ("correo", "pwd")
    assert form.payload("u", "p") == {"token": "abc", "telefono": "", "entrar": "Entrar", "correo": "u", "pwd": "p"}


def test_pages_without_a_password_field_are_not_login_forms():
    assert find_login_form("<form><input name='q'></form>", "http://x/") is None
    assert find_login_form("<html><body>password reset info</body></html>", "http://x/") is None
