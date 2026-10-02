"""_check_production_security is a startup-time warning, not an enforcement
gate (SECURITY_REVIEW.md explains why it doesn't refuse to start) -- these
tests just confirm it fires (or doesn't) for the right combinations."""
import logging

from app.config.settings import Settings
from app.main import _check_production_security


def _settings(**overrides) -> Settings:
    defaults = dict(
        environment="production",
        supabase_url="https://proj.supabase.co",
        supabase_anon_key="anon",
        source_secret_key="dGVzdC1rZXktZm9yLXNvdXJjZS1wYXNzd29yZHMtMDE=",
        cors_origins=["http://localhost:5173"],
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_warns_when_supabase_is_not_configured(caplog):
    with caplog.at_level(logging.CRITICAL):
        _check_production_security(_settings(supabase_url="", supabase_anon_key=""))
    assert any("SUPABASE_URL" in r.message for r in caplog.records)


def test_warns_when_the_source_password_cannot_be_encrypted(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings(source_secret_key=""))
    assert any("SOURCE_SECRET_KEY" in r.message for r in caplog.records)


def test_warns_on_localhost_cors_in_production(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings())
    assert any("CORS_ORIGINS" in r.message for r in caplog.records)


def test_silent_when_properly_configured_for_production(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings(cors_origins=["https://reports.example.com"]))
    assert caplog.records == []


def test_cors_is_not_checked_outside_production(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings(environment="development"))
    assert caplog.records == []
