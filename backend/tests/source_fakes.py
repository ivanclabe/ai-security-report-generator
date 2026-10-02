"""In-memory stand-in for the remote alarm source, used with httpx.MockTransport
so tests exercise the real SourceClient / acquisition service / provider
without any network. It behaves like the real server in the ways that matter:

* HTTP Basic Auth on every endpoint (401 + WWW-Authenticate otherwise);
* a PHP-style session cookie it issues on the first authenticated request;
* the alarms export filters by `cliente=` (comparing like the data does:
  case/hyphen/space-insensitive) and answers a header-only CSV when nothing matches;
* switches to simulate the failure modes: expired session, HTML login page
  delivered with HTTP 200, server errors, timeouts, connection refused.
"""
import base64
import io
from collections import deque

import httpx
import pandas as pd

from app.ingestion.client import SourceClient
from app.ingestion.config import SourceConfig
from app.ingestion.normalizer import load_mitre_catalog
from app.ingestion.service import AlarmAcquisitionService
from app.services.company_registry import normalize_company_key
from tests.conftest import MITRE_CATALOG_PATH

TEST_USERNAME = "reporter-test"
TEST_PASSWORD = "not-a-real-password-123"  # synthetic; the real credentials only ever live in backend/.env


class FakeSourceServer:
    def __init__(self, alarms_csv: bytes, username: str = TEST_USERNAME, password: str = TEST_PASSWORD):
        self.alarms_csv = alarms_csv
        self.username = username
        self.password = password
        self.requests: list[httpx.Request] = []
        # Statuses to answer (once each, in order) before behaving normally -- e.g. [401] with valid
        # credentials is exactly "the session expired".
        self.fail_next: deque[int] = deque()
        self.sessions_issued = 0
        self.html_instead_of_csv = False
        self.raise_next: deque[Exception] = deque()
        self.transport = httpx.MockTransport(self._handle)

    # -- helpers for tests -------------------------------------------------

    @property
    def alarm_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("detallado_alarmas.php")]

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("authorization", "")
        expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return header == f"Basic {expected}"

    # -- the "server" ------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_next:
            raise self.raise_next.popleft()
        if self.fail_next:
            return httpx.Response(self.fail_next.popleft(), text="")
        if not self._authorized(request):
            return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="Albatroz"'}, text="Unauthorized")

        headers = {}
        if "phpsessid" not in request.headers.get("cookie", "").lower():
            self.sessions_issued += 1
            headers["Set-Cookie"] = f"PHPSESSID=session-{self.sessions_issued}; Path=/"

        path = request.url.path
        if path.endswith("/detallado_alarmas.php"):
            if self.html_instead_of_csv:
                return httpx.Response(
                    200, headers={**headers, "Content-Type": "text/html"}, text="<html><body>Iniciar sesión</body></html>"
                )
            return httpx.Response(
                200,
                headers={**headers, "Content-Type": "text/csv; charset=utf-8"},
                content=self._alarms_for(request.url.params.get("cliente", "")),
            )
        if path.endswith("/indicadores.php"):
            return httpx.Response(200, headers={**headers, "Content-Type": "application/json"}, json={"ok": True})
        return httpx.Response(404, text="not found")

    def _alarms_for(self, cliente: str) -> bytes:
        df = pd.read_csv(io.BytesIO(self.alarms_csv), dtype=str, keep_default_na=False)
        wanted = normalize_company_key(cliente)
        df = df[df["cliente"].map(normalize_company_key) == wanted]
        return df.to_csv(index=False).encode("utf-8")


def make_config(**overrides) -> SourceConfig:
    values = dict(
        base_url="https://source.test",
        username=TEST_USERNAME,
        password=TEST_PASSWORD,
        timeout_seconds=5,
        alarms_limit=1000,
        cache_ttl_seconds=300,
    )
    values.update(overrides)
    return SourceConfig(**values)


def build_client(server: FakeSourceServer, **config_overrides) -> SourceClient:
    return SourceClient(make_config(**config_overrides), transport=server.transport)


def build_acquisition(server: FakeSourceServer, *, clock=None, on_fetch=None, **config_overrides):
    kwargs = {"on_fetch": on_fetch}
    if clock is not None:
        kwargs["clock"] = clock
    return AlarmAcquisitionService(
        build_client(server, **config_overrides), load_mitre_catalog(MITRE_CATALOG_PATH), **kwargs
    )
