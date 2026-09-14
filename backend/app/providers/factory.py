from functools import lru_cache

from app.config.settings import get_settings
from app.providers.api import ApiDataProvider
from app.providers.base import DataProvider
from app.providers.excel import ExcelDataProvider
from app.providers.mock import MockDataProvider


@lru_cache
def get_data_provider() -> DataProvider:
    settings = get_settings()
    if settings.data_provider == "mock":
        return MockDataProvider(settings.mock_data_path)
    if settings.data_provider == "excel":
        return ExcelDataProvider(
            settings.excel_data_path, settings.mitre_tactics_path, settings.excel_sheet_name
        )
    if settings.data_provider == "api":
        # Recognized but not yet functional -- see app/providers/api.py.
        return ApiDataProvider()
    raise ValueError(f"Unknown data provider: {settings.data_provider}")
