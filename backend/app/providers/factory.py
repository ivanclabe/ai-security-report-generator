from functools import lru_cache

from app.config.settings import get_settings
from app.ingestion.client import SourceClient
from app.ingestion.normalizer import load_mitre_catalog
from app.ingestion.service import AlarmAcquisitionService
from app.ingestion.source_settings_store import effective_source_config
from app.providers.base import DataProvider
from app.providers.http_source import HttpSourceDataProvider
from app.providers.mock import MockDataProvider
from app.services.company_registry import get_company_registry
from app.services.ingestion_service import record_import

_REMOVED_PROVIDERS = {
    "excel": "el proveedor Excel fue reemplazado por la fuente HTTP",
    "api": "el placeholder 'api' fue reemplazado por la fuente HTTP",
}


@lru_cache
def get_data_provider() -> DataProvider:
    settings = get_settings()
    kind = settings.data_provider
    if kind == "mock":
        return MockDataProvider(settings.mock_data_path)
    if kind == "http":
        client = SourceClient(effective_source_config(settings))
        acquisition = AlarmAcquisitionService(
            client, load_mitre_catalog(settings.mitre_tactics_path), on_fetch=record_import
        )
        return HttpSourceDataProvider(acquisition, get_company_registry())
    if kind in _REMOVED_PROVIDERS:
        raise ValueError(f"DATA_PROVIDER={kind!r} ya no existe: {_REMOVED_PROVIDERS[kind]}. Usa DATA_PROVIDER=http.")
    raise ValueError(f"Unknown data provider: {kind!r} (valid: 'http', 'mock')")
