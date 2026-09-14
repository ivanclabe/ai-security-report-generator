"""No dedicated auth test file existed before Fase 9 (SECURITY_REVIEW.md) --
login itself was only ever exercised incidentally via the auth_headers() test
helper other suites use to get a token."""
from app.auth import _LOGIN_ATTEMPT_LIMIT


def test_login_succeeds_with_correct_credentials(api_client):
    res = api_client.post("/api/auth/login", json={"username": "master", "password": "123456"})
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "master"
    assert body["access_token"]


def test_login_rejects_wrong_password(api_client):
    res = api_client.post("/api/auth/login", json={"username": "master", "password": "wrong"})
    assert res.status_code == 401


def test_login_rejects_wrong_username(api_client):
    res = api_client.post("/api/auth/login", json={"username": "nobody", "password": "123456"})
    assert res.status_code == 401


def test_protected_route_rejects_missing_token(api_client):
    res = api_client.get("/api/companies")
    assert res.status_code == 401


def test_protected_route_rejects_garbage_token(api_client):
    res = api_client.get("/api/companies", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


def test_login_is_rate_limited_after_repeated_attempts(api_client):
    for _ in range(_LOGIN_ATTEMPT_LIMIT):
        res = api_client.post("/api/auth/login", json={"username": "master", "password": "wrong"})
        assert res.status_code == 401

    # One more (whether the credentials are right or wrong doesn't matter --
    # the limiter counts attempts, not failures) must now be rate limited.
    res = api_client.post("/api/auth/login", json={"username": "master", "password": "123456"})
    assert res.status_code == 429
