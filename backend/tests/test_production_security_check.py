"""_check_production_security is a startup-time warning, not an enforcement
gate (SECURITY_REVIEW.md explains why it doesn't refuse to start) -- these
tests just confirm it fires (or doesn't) for the right combinations."""
import logging

from app.config.settings import Settings
from app.main import _check_production_security


def _settings(**overrides) -> Settings:
    defaults = dict(
        environment="production",
        auth_secret_key="dev-insecure-change-me",
        auth_password="123456",
        cors_origins=["http://localhost:5173"],
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_warns_on_default_secret_key_in_production(caplog):
    with caplog.at_level(logging.CRITICAL):
        _check_production_security(_settings())
    assert any("AUTH_SECRET_KEY" in r.message for r in caplog.records)


def test_warns_on_default_password_in_production(caplog):
    with caplog.at_level(logging.CRITICAL):
        _check_production_security(_settings())
    assert any("AUTH_PASSWORD" in r.message for r in caplog.records)


def test_warns_on_localhost_cors_in_production(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings())
    assert any("CORS_ORIGINS" in r.message for r in caplog.records)


def test_silent_when_properly_configured_for_production(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(
            _settings(
                auth_secret_key="a-real-random-secret",
                auth_password="a-real-password",
                cors_origins=["https://reports.example.com"],
            )
        )
    assert caplog.records == []


def test_silent_in_development_regardless_of_defaults(caplog):
    with caplog.at_level(logging.WARNING):
        _check_production_security(_settings(environment="development"))
    assert caplog.records == []
