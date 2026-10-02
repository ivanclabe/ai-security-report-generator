"""HTTP client for the alarm data source: Basic Auth, a reusable session and
renewal when the session expires.

Session model
-------------
One httpx.AsyncClient is kept for the life of the process, so connections and
any cookie the server sets (e.g. PHPSESSID) are reused across requests. If a
request that used to work starts answering 401 the session is considered
expired: the client is discarded (dropping its cookies), a fresh one is built
and the request is retried exactly once. A 401 on the very first request, or
on the retry, is not retried -- it raises SourceAuthenticationError, so a wrong
password can never turn into a login loop.

Nothing here logs or raises with credentials: only the host, the endpoint
label, the status code and timings.
"""
import asyncio
import logging
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.ingestion.config import SourceConfig
from app.ingestion.errors import (
    SourceAuthenticationError,
    SourceError,
    SourceFormatError,
    SourceUnavailableError,
)
from app.ingestion.requests import SourceRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceResponse:
    content: bytes
    content_type: str
    status_code: int
    elapsed_seconds: float


class SourceClient:
    def __init__(self, config: SourceConfig, transport: httpx.AsyncBaseTransport | None = None):
        self._config = config
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()

    @property
    def config(self) -> SourceConfig:
        return self._config

    async def aclose(self) -> None:
        async with self._lock:
            await self._discard_client()

    async def _discard_client(self) -> None:
        client, self._client = self._client, None
        self._authenticated = False
        if client is not None:
            await client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    auth=httpx.BasicAuth(self._config.username, self._config.password),
                    verify=self._config.tls_verify,
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                    follow_redirects=False,
                    headers={
                        "Accept": "text/csv, application/json;q=0.9, */*;q=0.5",
                        "User-Agent": "ai-security-report-generator",
                    },
                    transport=self._transport,
                )
            return self._client

    async def fetch(self, request: SourceRequest) -> SourceResponse:
        self._config.validate()

        for attempt in (1, 2):
            client = await self._get_client()
            response, elapsed = await self._send(client, request)

            if response.status_code == 401:
                if attempt == 1 and self._authenticated:
                    logger.info("Fuente %s: sesión expirada (HTTP 401); reautenticando", self._config.host)
                    async with self._lock:
                        await self._discard_client()
                    continue
                if attempt == 2:
                    raise SourceAuthenticationError(
                        f"La sesión con {self._config.host} expiró y la reautenticación fue rechazada (HTTP 401). "
                        "Verifica SOURCE_USERNAME / SOURCE_PASSWORD."
                    )
                raise SourceAuthenticationError(
                    f"{self._config.host} rechazó las credenciales (HTTP 401). "
                    "Verifica SOURCE_USERNAME / SOURCE_PASSWORD en backend/.env."
                )
            break

        self._raise_for_status(response)
        self._authenticated = True
        logger.info(
            "Fuente %s: %s HTTP %s en %.2fs (%d bytes)",
            self._config.host,
            request.label,
            response.status_code,
            elapsed,
            len(response.content),
        )
        return SourceResponse(
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            status_code=response.status_code,
            elapsed_seconds=elapsed,
        )

    async def _send(self, client: httpx.AsyncClient, request: SourceRequest) -> tuple[httpx.Response, float]:
        host = self._config.host
        started = time.monotonic()
        try:
            response = await client.get(request.url, params=request.params)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError(
                f"Tiempo de espera agotado ({self._config.timeout_seconds:g}s) consultando {host}."
            ) from exc
        except httpx.ConnectError as exc:
            if self._is_certificate_error(exc):
                raise SourceUnavailableError(
                    f"No se pudo verificar el certificado TLS de {host}. Si es un servidor interno con CA propia, "
                    "apunta SOURCE_CA_BUNDLE a esa CA (o, solo en redes de confianza, SOURCE_VERIFY_TLS=false)."
                ) from exc
            raise SourceUnavailableError(
                f"No se pudo conectar a {host}. Verifica la red/VPN y que SOURCE_BASE_URL sea la dirección correcta."
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"Error de red consultando {host} ({type(exc).__name__}).") from exc
        return response, time.monotonic() - started

    @staticmethod
    def _is_certificate_error(exc: BaseException) -> bool:
        cause = exc.__cause__ or exc.__context__
        return isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)

    def _raise_for_status(self, response: httpx.Response) -> None:
        host, code = self._config.host, response.status_code
        if response.is_redirect:
            target = urlsplit(response.headers.get("location", "")).path or "(desconocido)"
            if "login" in target.lower():
                raise SourceAuthenticationError(
                    f"{host} redirigió a '{target}' (HTTP {code}): exige iniciar sesión por formulario, "
                    "no solo Basic Auth."
                )
            raise SourceFormatError(f"{host} redirigió a '{target}' (HTTP {code}); se esperaba la respuesta directa.")
        if code == 403:
            raise SourceAuthenticationError(f"{host} denegó el acceso (HTTP 403) al usuario configurado.")
        if code == 404:
            raise SourceError(
                f"{host} respondió HTTP 404: revisa SOURCE_ALARMS_PATH / SOURCE_INDICATORS_PATH y SOURCE_BASE_URL."
            )
        if code >= 500:
            raise SourceUnavailableError(f"{host} respondió con un error del servidor (HTTP {code}).")
        if code >= 400:
            raise SourceError(f"{host} respondió HTTP {code}.")
