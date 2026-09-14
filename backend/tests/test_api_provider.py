"""ApiDataProvider is a deliberate placeholder (see INGESTION_ARCHITECTURE.md §6) --
these tests only confirm the extension point is wired and fails loudly/clearly
rather than silently, not that it does anything useful yet."""
import pytest

from app.providers.api import ApiDataProvider
from app.providers.factory import get_data_provider


async def test_every_contract_method_raises_not_implemented_with_a_clear_message():
    provider = ApiDataProvider()
    with pytest.raises(NotImplementedError, match="future client API"):
        await provider.get_company(company_id="acme")
    with pytest.raises(NotImplementedError):
        await provider.search_companies("acme")
    with pytest.raises(NotImplementedError):
        await provider.get_notifications([])


def test_factory_recognizes_api_as_a_valid_provider_choice(monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.setenv("DATA_PROVIDER", "api")
    get_settings.cache_clear()
    get_data_provider.cache_clear()
    try:
        provider = get_data_provider()
        assert isinstance(provider, ApiDataProvider)
    finally:
        get_settings.cache_clear()
        get_data_provider.cache_clear()
