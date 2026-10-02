"""HTTP client for the alarm data source: authentication, a reusable session
and renewal when the session expires.

Authentication
--------------
Every request carries HTTP Basic Auth. If the server instead (or additionally)
uses a login *form* with a PHP session -- it answers with a redirect to a login
page, or with a login page itself -- the client reads that form, submits the
configured credentials, keeps the session cookie and retries the request. The
form is only ever submitted to the same host that served it.

Session model
-------------
One httpx.AsyncClient is kept for the life of the process, so connections and
the session cookie (e.g. PHPSESSID) are reused across requests. If a request
that used to work starts answering 401 the session is considered expired: the
client is discarded (dropping its cookies), a fresh one is built and the request
is retried exactly once; a login page showing up again is answered with one new
form login. A rejection on the very first attempt, or on the retry, raises
SourceAuthenticationError -- a wrong password can never turn into a login loop.

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
from app.ingestion.csv_decoder import looks_like_html
from app.ingestion.encoding import decode_source_text
from app.ingestion.errors import (
    SourceAuthenticationError,
    SourceError,
    SourceFormatError,
    SourceUnavailableError,
)
from app.ingestion.login_form import find_login_form
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
        self.last_login_method: str | None = None  # "basic" | "form" -- diagnostics only

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
        host = self._config.host
        renewed_session = False
        logged_in_with_form = False

        for _ in range(4):  # hard bound: initial try + one renewal + one form login + its retry
            client = await self._get_client()
            response, elapsed = await self._send(client, request.url, request.params)

            if response.status_code == 401:
                if self._authenticated and not renewed_session:
                    logger.info("Fuente %s: sesión expirada (HTTP 401); reautenticando", host)
                    async with self._lock:
                        await self._discard_client()
                    renewed_session = True
                    continue
                if renewed_session:
                    raise SourceAuthenticationError(
                        f"La sesión con {host} expiró y la reautenticación fue rechazada (HTTP 401). "
                        "Verifica SOURCE_USERNAME / SOURCE_PASSWORD."
                    )
                raise SourceAuthenticationError(
                    f"{host} rechazó las credenciales (HTTP 401). "
                    "Verifica SOURCE_USERNAME / SOURCE_PASSWORD en backend/.env."
                )

            login_page = await self._login_page_behind(client, response)
            if login_page is not None:
                if logged_in_with_form:
                    raise SourceAuthenticationError(
                        f"{host} rechazó el inicio de sesión (sigue mostrando el formulario de login). "
                        "Verifica SOURCE_USERNAME / SOURCE_PASSWORD."
                    )
                if self._authenticated:
                    logger.info("Fuente %s: sesión expirada (página de login); iniciando sesión de nuevo", host)
                await self._login_with_form(client, *login_page)
                logged_in_with_form = True
                continue
            break
        else:  # pragma: no cover - the attempt accounting above always returns or raises first
            raise SourceAuthenticationError(f"No se pudo establecer una sesión con {host}.")

        self._raise_for_status(response)
        self._authenticated = True
        self.last_login_method = "form" if logged_in_with_form else (self.last_login_method or "basic")
        logger.info(
            "Fuente %s: %s HTTP %s en %.2fs (%d bytes)",
            host,
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

    async def _login_page_behind(self, client: httpx.AsyncClient, response: httpx.Response) -> tuple[str, str] | None:
        """(page_url, html) when `response` is, or redirects (same host) to, a login form."""
        page = response
        for _ in range(2):
            if not page.is_redirect:
                break
            location = page.headers.get("location")
            if not location:
                return None
            target = page.url.join(location)
            if target.host != response.url.host:
                return None  # never follow an auth redirect to another host
            page, _ = await self._send(client, str(target))
        if page.is_redirect or page.status_code != 200:
            return None
        if "html" not in page.headers.get("content-type", "").lower() and not looks_like_html(page.content):
            return None
        text = decode_source_text(page.content)
        if find_login_form(text, str(page.url)) is None:
            return None
        return str(page.url), text

    async def _login_with_form(self, client: httpx.AsyncClient, page_url: str, page_html: str) -> None:
        host = self._config.host
        form = find_login_form(page_html, page_url)
        if form is None:  # pragma: no cover - _login_page_behind only returns pages with a form
            raise SourceAuthenticationError(f"{host} pidió iniciar sesión pero el formulario no es reconocible.")
        if httpx.URL(form.action).host != httpx.URL(page_url).host:
            raise SourceAuthenticationError(
                f"El formulario de login de {host} envía las credenciales a otro host "
                f"({httpx.URL(form.action).host}); no se enviaron."
            )
        try:
            response = await client.post(form.action, data=form.payload(self._config.username, self._config.password))
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"No se pudo completar el inicio de sesión en {host} ({type(exc).__name__}).") from exc
        if response.status_code in (401, 403):
            raise SourceAuthenticationError(
                f"{host} rechazó el inicio de sesión (HTTP {response.status_code}). Verifica SOURCE_USERNAME / SOURCE_PASSWORD."
            )
        logger.info("Fuente %s: sesión iniciada por formulario", host)

    async def _send(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str] | None = None
    ) -> tuple[httpx.Response, float]:
        host = self._config.host
        started = time.monotonic()
        try:
            response = await client.get(url, params=params)
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
                    f"{host} redirigió al inicio de sesión '{target}' (HTTP {code}) y no se encontró un "
                    "formulario de login reconocible para iniciar sesión automáticamente."
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
