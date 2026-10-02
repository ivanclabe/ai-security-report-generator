"""Provider selection and wiring from environment variables."""
import pytest

from app.config.settings import get_settings
from app.providers.factory import get_data_provider
from app.providers.http_source import HttpSourceDataProvider
from app.providers.mock import MockDataProvider


@pytest.fixture(autouse=True)
def fresh_provider():
    get_data_provider.cache_clear()
    yield
    get_data_provider.cache_clear()


def _select(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_data_provider()


def test_http_provider_is_built_from_the_environment(monkeypatch):
    provider = _select(
        monkeypatch,
        DATA_PROVIDER="http",
        SOURCE_BASE_URL="https://192.168.80.50",
        SOURCE_USERNAME="svc-reportes",
        SOURCE_PASSWORD="from-the-environment",
        SOURCE_ALARMS_LIMIT="2500",
        SOURCE_CACHE_TTL_SECONDS="120",
    )

    assert isinstance(provider, HttpSourceDataProvider)
    config = provider._acquisition._client.config
    assert (config.base_url, config.username, config.alarms_limit, config.cache_ttl_seconds) == (
        "https://192.168.80.50",
        "svc-reportes",
        2500,
        120,
    )
    assert config.password == "from-the-environment" and config.tls_verify is True


def test_moving_the_server_only_needs_a_new_base_url(monkeypatch):
    first = _select(
        monkeypatch, DATA_PROVIDER="http", SOURCE_BASE_URL="https://192.168.80.50", SOURCE_USERNAME="u", SOURCE_PASSWORD="p"
    )
    get_data_provider.cache_clear()
    second = _select(monkeypatch, SOURCE_BASE_URL="https://10.1.2.3:8443")

    assert first._acquisition._client.config.host == "192.168.80.50"
    assert second._acquisition._client.config.host == "10.1.2.3:8443"


def test_mock_provider_is_still_available_for_demos_and_tests(monkeypatch):
    assert isinstance(_select(monkeypatch, DATA_PROVIDER="mock"), MockDataProvider)


@pytest.mark.parametrize("removed", ["excel", "api"])
def test_removed_providers_fail_with_an_explicit_message(monkeypatch, removed):
    with pytest.raises(ValueError) as excinfo:
        _select(monkeypatch, DATA_PROVIDER=removed)
    assert "DATA_PROVIDER=http" in str(excinfo.value)


def test_unknown_provider_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        _select(monkeypatch, DATA_PROVIDER="ftp")


def test_http_is_the_default_provider(monkeypatch):
    from app.config.settings import Settings

    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    assert Settings(_env_file=None).data_provider == "http"
