"""Connection settings of the alarm data source, built from app Settings.

Centralizes everything that varies between environments -- address, paths,
credentials, TLS policy, limits -- so the rest of the acquisition layer never
reads environment variables or hardcodes a URL. The address and credentials
start from SOURCE_* in backend/.env and can be changed from the app without a
restart (see source_settings_store.py).
"""
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app.ingestion.errors import SourceConfigError


@dataclass(frozen=True)
class SourceConfig:
    base_url: str
    alarms_path: str = "/detallado_alarmas.php"
    indicators_path: str = "/indicadores.php"
    username: str = ""
    password: str = field(default="", repr=False)  # never printed, not even in debug logs
    verify_tls: bool = True
    ca_bundle: str = ""
    timeout_seconds: float = 30.0
    alarms_limit: int = 1000
    cache_ttl_seconds: int = 300
    # Cross-check every alarms download against the source's own indicators page
    # (same company/period): an empty CSV while the dashboard reports alarms fails
    # loudly instead of producing an empty report.
    reconcile_with_indicators: bool = True

    @classmethod
    def from_settings(cls, settings) -> "SourceConfig":
        return cls(
            base_url=settings.source_base_url.strip(),
            alarms_path=settings.source_alarms_path,
            indicators_path=settings.source_indicators_path,
            username=settings.source_username,
            password=settings.source_password.get_secret_value(),
            verify_tls=settings.source_verify_tls,
            ca_bundle=settings.source_ca_bundle.strip(),
            timeout_seconds=settings.source_timeout_seconds,
            alarms_limit=settings.source_alarms_limit,
            cache_ttl_seconds=settings.source_cache_ttl_seconds,
            reconcile_with_indicators=settings.source_reconcile_indicators,
        )

    @property
    def tls_verify(self) -> bool | str:
        """Value for httpx's `verify=`: a CA bundle path, or on/off."""
        return self.ca_bundle or self.verify_tls

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).netloc

    @property
    def uses_https(self) -> bool:
        return urlsplit(self.base_url).scheme == "https"

    def url_for(self, path: str) -> str:
        """Endpoint URL: the path relative to SOURCE_BASE_URL, or the path itself when
        it is already an absolute http(s) URL (an endpoint living on another host)."""
        if urlsplit(path).scheme in ("http", "https"):
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    def problems(self) -> list[str]:
        """Human-readable list of what is missing/invalid, naming the env vars."""
        problems: list[str] = []
        if not self.base_url:
            problems.append("falta SOURCE_BASE_URL (p. ej. https://192.168.80.50)")
        else:
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                problems.append("SOURCE_BASE_URL debe ser una URL http(s) con host, p. ej. https://192.168.80.50")
        if not self.username:
            problems.append("falta SOURCE_USERNAME")
        if not self.password:
            problems.append("falta SOURCE_PASSWORD")
        if self.ca_bundle and not Path(self.ca_bundle).is_file():
            problems.append("SOURCE_CA_BUNDLE no apunta a un archivo existente")
        if self.alarms_limit < 1:
            problems.append("SOURCE_ALARMS_LIMIT debe ser mayor que 0")
        return problems

    def validate(self) -> None:
        problems = self.problems()
        if problems:
            raise SourceConfigError(
                "La fuente de datos no está configurada (Fuente de Datos en la app, o backend/.env): "
                + "; ".join(problems)
                + "."
            )
