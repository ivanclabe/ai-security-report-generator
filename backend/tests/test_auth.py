"""Supabase Auth: token verification, app membership, roles, session events
and authentication-failure auditing."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import AuthError, SupabaseTokenVerifier
from tests.conftest import ADMIN_AUTH_ID, auth_headers

ISSUER_URL = "https://proj.supabase.test"


class _StaticJwks:
    def __init__(self, public_key):
        self._key = jwt.PyJWK.from_dict(
            {**jwt.algorithms.ECAlgorithm.to_jwk(public_key, as_dict=True), "alg": "ES256", "kid": "k1"}
        )

    def get_signing_key_from_jwt(self, token):
        return self._key


@pytest.fixture
def signer():
    private_key = ec.generate_private_key(ec.SECP256R1())
    verifier = SupabaseTokenVerifier(ISSUER_URL, jwks_client=_StaticJwks(private_key.public_key()))

    def sign(**overrides):
        now = int(time.time())
        claims = {
            "sub": ADMIN_AUTH_ID,
            "email": "admin@soc.test",
            "aud": "authenticated",
            "iss": f"{ISSUER_URL}/auth/v1",
            "iat": now,
            "exp": now + 3600,
            "role": "authenticated",
            **overrides,
        }
        return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "k1"})

    return verifier, sign


# ---- token verification (real ES256 signatures) --------------------------------------


def test_a_valid_supabase_token_is_accepted(signer):
    verifier, sign = signer
    assert verifier.verify(sign())["sub"] == ADMIN_AUTH_ID


def test_an_expired_token_is_a_session_expired_error(signer):
    verifier, sign = signer
    with pytest.raises(AuthError) as excinfo:
        verifier.verify(sign(exp=int(time.time()) - 120))
    assert excinfo.value.code == "session_expired"


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "anon"}, {"iss": "https://other-project.supabase.test/auth/v1"}],
    ids=["wrong-audience", "token-of-another-project"],
)
def test_tokens_for_another_audience_or_project_are_rejected(signer, overrides):
    verifier, sign = signer
    with pytest.raises(AuthError) as excinfo:
        verifier.verify(sign(**overrides))
    assert excinfo.value.code == "invalid_token"


def test_a_token_signed_with_another_key_is_rejected(signer):
    verifier, _ = signer
    forged = jwt.encode(
        {"sub": ADMIN_AUTH_ID, "aud": "authenticated", "iss": f"{ISSUER_URL}/auth/v1", "exp": int(time.time()) + 60},
        ec.generate_private_key(ec.SECP256R1()),
        algorithm="ES256",
    )
    with pytest.raises(AuthError):
        verifier.verify(forged)


def test_a_symmetric_token_cannot_downgrade_the_algorithm(signer):
    verifier, _ = signer
    hs = jwt.encode({"sub": ADMIN_AUTH_ID, "aud": "authenticated", "exp": int(time.time()) + 60}, "x" * 32, "HS256")
    with pytest.raises(AuthError):
        verifier.verify(hs)


# ---- protected routes ----------------------------------------------------------------


def test_protected_routes_require_a_session(api_client):
    res = api_client.get("/api/companies")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "not_authenticated"


def test_garbage_and_expired_tokens_are_401_with_a_reason(api_client):
    assert api_client.get("/api/me", headers={"Authorization": "Bearer garbage"}).json()["detail"]["code"] == "invalid_token"
    res = api_client.get("/api/me", headers={"Authorization": "Bearer token-expired"})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "session_expired"


def test_a_supabase_user_of_another_app_is_denied_and_audited(api_client, fake_supabase):
    res = api_client.get("/api/companies", headers=auth_headers(role="outsider"))

    assert res.status_code == 403 and res.json()["detail"]["code"] == "not_member"
    denied = fake_supabase.audit("auth.access_denied")
    assert denied and denied[0]["actor_email"] == "otra-app@example.test"


def test_a_deactivated_member_loses_access(api_client, fake_supabase):
    fake_supabase.table("in_users").update({"id": "user-operator"}, {"is_active": False})
    assert api_client.get("/api/me", headers=auth_headers(role="operator")).status_code == 403


def test_me_returns_the_member_profile(api_client):
    body = api_client.get("/api/me", headers=auth_headers()).json()
    assert body == {"email": "admin@soc.test", "display_name": "Admin SOC", "role": "admin", "is_admin": True}


def test_admin_areas_reject_operators(api_client, fake_supabase):
    headers = auth_headers(role="operator")
    for path in ("/api/audit", "/api/observability/summary", "/api/source-settings"):
        res = api_client.get(path, headers=headers)
        assert res.status_code == 403, path
        assert res.json()["detail"]["code"] == "admin_required"
    assert fake_supabase.audit("auth.admin_required")
    # ...but operators still see whether the source is ready
    assert api_client.get("/api/source-settings/status", headers=headers).status_code == 200


# ---- session events -----------------------------------------------------------------


def test_login_and_logout_are_audited_under_the_user(api_client, fake_supabase):
    for event in ("login", "logout"):
        assert api_client.post("/api/me/session-events", headers=auth_headers(), json={"event": event}).status_code == 204
    actions = [r["action"] for r in fake_supabase.audit()]
    assert actions == ["auth.login", "auth.logout"]
    assert all(r["actor_auth_id"] == ADMIN_AUTH_ID for r in fake_supabase.audit())


def test_failed_sign_in_is_audited_without_a_session_and_rate_limited(api_client, fake_supabase):
    payload = {"action": "login_failed", "email": "alguien@soc.test", "reason": "Invalid login credentials"}
    codes = [api_client.post("/api/auth/events", json=payload).status_code for _ in range(21)]

    assert codes[:20] == [204] * 20 and codes[20] == 429
    row = fake_supabase.audit("auth.login_failed")[0]
    assert row["actor_email"] == "alguien@soc.test" and row["actor_auth_id"] is None


def test_auth_events_accept_only_known_actions(api_client):
    assert api_client.post("/api/auth/events", json={"action": "settings_updated"}).status_code == 422
