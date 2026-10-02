from functools import lru_cache

from app.config.settings import get_settings
from app.ingestion.client import SourceClient
from app.ingestion.normalizer import load_mitre_catalog
from app.ingestion.service import AlarmAcquisitionService, SourceEvent
from app.providers.base import DataProvider
from app.providers.http_source import HttpSourceDataProvider
from app.providers.mock import MockDataProvider
from app.services import source_settings_service
from app.services.company_registry import get_company_registry
from app.services.ingestion_service import record_import
from app.services.observability import get_observability

_REMOVED_PROVIDERS = {
    "excel": "el proveedor Excel fue reemplazado por la fuente HTTP",
    "api": "el placeholder 'api' fue reemplazado por la fuente HTTP",
}


_SOURCE_EVENT_MESSAGES = {
    "alarms_fetched": "Alertas descargadas de {company}: {rows} filas",
    "alarms_failed": "Fallo al descargar alertas de {company}: {detail}",
    "indicators_fetched": "Notificaciones/indicadores de {company}: {rows} alarmas en el panel",
    "indicators_failed": "Fallo al leer notificaciones/indicadores de {company}: {detail}",
}


async def _observe_source(event: SourceEvent) -> None:
    level = "INFO" if event.ok else "ERROR"
    if event.ok and event.warnings:
        level = "WARNING"
    message = _SOURCE_EVENT_MESSAGES[event.name].format(
        company=event.company, rows=event.rows, detail=event.detail
    )
    if event.ok and event.warnings:
        message += f" ({event.warnings} advertencias)"
    await get_observability().emit(
        level,
        "source",
        f"source.{event.name}",
        message,
        status="ok" if event.ok else "error",
        duration_ms=event.duration_ms,
        context={"host": event.host, "company": event.company, "rows": event.rows, "warnings": event.warnings},
    )


@lru_cache
def get_data_provider() -> DataProvider:
    settings = get_settings()
    kind = settings.data_provider
    if kind == "mock":
        return MockDataProvider(settings.mock_data_path)
    if kind == "http":
        # Address/credentials come from Fuente de Datos (Supabase) and are re-read before every
        # acquisition; the environment values only seed the client until then.
        client = SourceClient(source_settings_service.to_source_config(source_settings_service.settings_from_env()))
        acquisition = AlarmAcquisitionService(
            client,
            load_mitre_catalog(settings.mitre_tactics_path),
            on_fetch=record_import,
            config_provider=source_settings_service.effective_config,
            on_event=_observe_source,
        )
        return HttpSourceDataProvider(acquisition, get_company_registry())
    if kind in _REMOVED_PROVIDERS:
        raise ValueError(f"DATA_PROVIDER={kind!r} ya no existe: {_REMOVED_PROVIDERS[kind]}. Usa DATA_PROVIDER=http.")
    raise ValueError(f"Unknown data provider: {kind!r} (valid: 'http', 'mock')")
