"""Startup diagnostics for the alarm source configuration (app.main._check_data_source)."""
import logging

from app.config.settings import Settings
from app.main import _check_data_source


def _settings(monkeypatch, **env) -> Settings:
    for key in ("SOURCE_BASE_URL", "SOURCE_USERNAME", "SOURCE_PASSWORD", "SOURCE_VERIFY_TLS", "ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATA_PROVIDER", env.get("DATA_PROVIDER", "http"))
    return Settings(_env_file=None)


def test_missing_bootstrap_values_point_to_fuente_de_datos(monkeypatch, caplog):
    # backend/.env is only a bootstrap now: the source is configured from the app
    with caplog.at_level(logging.INFO):
        _check_data_source(_settings(monkeypatch))
    assert "Fuente de Datos" in caplog.text
    assert "SOURCE_BASE_URL" in caplog.text and "SOURCE_USERNAME" in caplog.text and "SOURCE_PASSWORD" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_configured_source_logs_the_host_but_never_the_credentials(monkeypatch, caplog):
    settings = _settings(
        monkeypatch, SOURCE_BASE_URL="https://192.168.80.50", SOURCE_USERNAME="svc-user", SOURCE_PASSWORD="top-secret-pw"
    )
    with caplog.at_level(logging.INFO):
        _check_data_source(settings)
    assert "192.168.80.50" in caplog.text
    assert "top-secret-pw" not in caplog.text and "svc-user" not in caplog.text


def test_production_warns_about_cleartext_and_unverified_tls(monkeypatch, caplog):
    settings = _settings(
        monkeypatch,
        SOURCE_BASE_URL="http://192.168.80.50",
        SOURCE_USERNAME="u",
        SOURCE_PASSWORD="p",
        SOURCE_VERIFY_TLS="false",
        ENVIRONMENT="production",
    )
    with caplog.at_level(logging.WARNING):
        _check_data_source(settings)
    assert "sin cifrar" in caplog.text and "SOURCE_VERIFY_TLS=false" in caplog.text


def test_other_providers_are_not_checked(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        _check_data_source(_settings(monkeypatch, DATA_PROVIDER="mock"))
    assert caplog.text == ""
