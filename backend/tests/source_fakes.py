"""In-memory stand-in for the remote alarm source, used with httpx.MockTransport
so tests exercise the real SourceClient / acquisition service / provider
without any network. It behaves like the real server in the ways that matter:

* HTTP Basic Auth on every endpoint (401 + WWW-Authenticate otherwise), so a
  client that only sends credentials when challenged sees the same handshake;
* a PHP-style session cookie it issues on the first authenticated request;
* the alarms export filters by `cliente=` (comparing like the data does:
  case/hyphen/space-insensitive) and answers a header-only CSV when nothing matches;
* the indicators page (indicadores.php) rendered as HTML with the same markup
  as the real page, its figures computed from the same CSV rows, so the
  acquisition layer's CSV<->indicators reconciliation sees a consistent source;
* switches to simulate the failure modes: expired session, HTML login page
  delivered with HTTP 200, server errors, timeouts, connection refused, a
  dashboard that disagrees with the export.
"""
import base64
import html
import io
import json
from collections import Counter, deque
from datetime import date
from urllib.parse import parse_qs

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

# The client selector of the live indicators page (company names only, no data):
# exactly the `cliente=` values the source accepts.
SOURCE_CLIENT_OPTIONS = [
    "THOMAS GREG & SONS", "AIRE", "BAC", "PERU-SSS", "THOMAS TGS COL TTI", "THOMAS TGS LIMITED",
    "THOMAS TGS SECURID", "THOMAS TGS-ALTA-GERENCIA", "THOMAS TGS-BRASIL", "THOMAS TGS-COL LOTERIAS",
    "THOMAS TGS-COLOMBIA", "THOMAS TGS-CSC", "THOMAS TGS-EXPRESS", "THOMAS TGS-GREG", "THOMAS TGS-INVOTECSA",
    "THOMAS TGS-MEXICO", "THOMAS TGS-MTI", "THOMAS TGS-PERU", "THOMAS TGS-SIR", "THOMAS TGS-TPS",
    "THOMAS TGS-TURRISYSTEM",
]


def render_indicators_page(cliente: str, start: str, end: str, rows: pd.DataFrame, total: int | None = None) -> str:
    """HTML in the shape of indicadores.php (resumen, top tables, inline DATA/porDiaRaw/
    categoriasData, client selector), its figures computed from `rows`."""
    total = len(rows) if total is None else total
    options = "\n".join(
        f'<option value="{html.escape(c)}"{" selected" if c == cliente else ""}>{html.escape(c)}</option>'
        for c in SOURCE_CLIENT_OPTIONS
    )

    def table(title: str, values) -> str:
        body = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k, v in values)
        return f'<div class="dashboard-card"><h3><i class="fas fa-x"></i> {title}</h3><table class="top-table"><tbody>{body}</tbody></table></div>'

    def top(column: str) -> list[tuple[str, int]]:
        return Counter(v for v in rows[column] if v).most_common(5) if len(rows) else []

    records = [
        {"tipo": r["tipo"], "timestamp": r["timestamp"], "sourceIP": r["sourceIP"], "externalIP": r["externalIP"],
         "hostname": r["hostname"], "description": r["description"], "quien_reporta": r["quien_reporta"],
         "fecha_de_creacion_alarma": r["fecha_de_creacion_alarma"], "severity": r["severity"]}
        for _, r in rows.iterrows()
    ]
    per_day = dict(sorted(Counter(str(t)[:10] for t in rows["timestamp"]).items())) if len(rows) else {}
    categories = dict(Counter(rows["category"]).most_common(10)) if len(rows) else {}
    summary = (
        f'<div class="resumen-ejecutivo"><h2>Resumen Ejecutivo</h2><p>Se identificaron <strong>{total}</strong> '
        f'alarmas entre <strong>{start}</strong> y <strong>{end}</strong>. Principal origen: '
        f'<strong>{(top("sourceIP") or [("N/A", 0)])[0][0]}</strong></p></div>'
        if total else '<div class="no-data">No se encontraron alarmas para el período seleccionado.</div>'
    )
    return (
        "<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"UTF-8\"><title>Indicadores de Seguridad | Albatrus</title></head><body>"
        f'<form method="GET"><select name="cliente" id="cliente"><option value="">-- Selecciona un cliente --</option>{options}</select>'
        f'<input type="date" name="fecha_inicio" value="{start}"><input type="date" name="fecha_fin" value="{end}"></form>'
        f"{summary}<div class=\"dashboard-container\">"
        + table("Tabla de Riesgo por Severidad", [])
        + table("Top 5 IP Origen", top("sourceIP"))
        + table("Top 5 IP Destino", top("externalIP"))
        + table("Top 5 Hostnames", top("hostname"))
        + table("Top 5 Descripciones", top("description"))
        + "</div><script>\n"
        f"const DATA = {json.dumps(records)};\n"
        f"const porDiaRaw = {json.dumps(per_day)};\n"
        f"const categoriasData = {json.dumps(categories)};\n"
        "</script></body></html>"
    )


class FakeSourceServer:
    def __init__(self, alarms_csv: bytes, username: str = TEST_USERNAME, password: str = TEST_PASSWORD):
        self.alarms_csv = alarms_csv
        self.username = username
        self.password = password
        self.requests: list[httpx.Request] = []  # everything received, auth challenges included
        self.served: list[httpx.Request] = []  # requests that got past authentication
        # Statuses to answer (once each, in order) before behaving normally -- e.g. [401] with valid
        # credentials is exactly "the session expired".
        self.fail_next: deque[int] = deque()
        self.sessions_issued = 0
        self.html_instead_of_csv = False
        self.raise_next: deque[Exception] = deque()
        # login-form mode (PHP session): endpoints redirect to the login page until a session exists
        self.form_login = False
        self.login_path = "/ProyectoSOC/public/login.php"
        self.login_page_with_200 = False  # answer endpoints with the login page itself instead of a 302
        self.login_form_action: str | None = None  # override the form's action (e.g. another host)
        self.csrf_token = "csrf-synthetic-token"
        self.valid_sessions: set[str] = set()
        self.login_posts: list[dict] = []
        # indicators-page switches
        self.indicators_total_override: int | None = None
        self.indicators_status: int = 200
        self.indicators_client_override: str | None = None
        self.transport = httpx.MockTransport(self._handle)

    # -- helpers for tests -------------------------------------------------

    @property
    def alarm_requests(self) -> list[httpx.Request]:
        return [r for r in self.served if r.url.path.endswith("detallado_alarmas.php")]

    @property
    def indicator_requests(self) -> list[httpx.Request]:
        return [r for r in self.served if r.url.path.endswith("indicadores.php")]

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("authorization", "")
        expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return header == f"Basic {expected}"

    # -- the "server" ------------------------------------------------------

    def expire_sessions(self) -> None:
        self.valid_sessions.clear()

    def _session_of(self, request: httpx.Request) -> str | None:
        for part in request.headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name.lower() == "phpsessid":
                return value
        return None

    def _login_page(self, error: str = "") -> httpx.Response:
        action = self.login_form_action or self.login_path
        page = (
            "<!DOCTYPE html><html><head><title>Albatrus - Ingreso</title></head><body>"
            f'<p class="error">{error}</p>'
            f'<form method="POST" action="{action}">'
            f'<input type="hidden" name="csrf_token" value="{self.csrf_token}">'
            '<label>Usuario</label><input type="text" name="usuario" id="usuario">'
            '<label>Contraseña</label><input type="password" name="clave" id="clave">'
            '<input type="checkbox" name="recordar" value="1">'
            '<button type="submit" name="ingresar" value="1">Ingresar</button>'
            "</form></body></html>"
        )
        return httpx.Response(200, headers={"Content-Type": "text/html; charset=UTF-8"}, text=page)

    def _handle_form_login(self, request: httpx.Request) -> httpx.Response | None:
        """Login page + PHP session gate. Returns a response to send, or None to proceed."""
        if request.url.path == self.login_path:
            if request.method == "GET":
                return self._login_page()
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.login_posts.append(form)
            if (
                form.get("csrf_token") == self.csrf_token
                and form.get("usuario") == self.username
                and form.get("clave") == self.password
            ):
                self.sessions_issued += 1
                session = f"session-{self.sessions_issued}"
                self.valid_sessions.add(session)
                return httpx.Response(
                    302, headers={"Location": "/ProyectoSOC/views/panel.php", "Set-Cookie": f"PHPSESSID={session}; Path=/"}
                )
            return self._login_page(error="Usuario o clave incorrectos")
        if self._session_of(request) in self.valid_sessions:
            return None
        if self.login_page_with_200:
            return self._login_page()
        return httpx.Response(302, headers={"Location": self.login_path})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_next:
            raise self.raise_next.popleft()
        if self.fail_next:
            return httpx.Response(self.fail_next.popleft(), text="")

        headers = {}
        if self.form_login:
            gate = self._handle_form_login(request)
            if gate is not None:
                return gate
        else:
            if not self._authorized(request):
                return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="Albatroz"'}, text="Unauthorized")
            if "phpsessid" not in request.headers.get("cookie", "").lower():
                self.sessions_issued += 1
                headers["Set-Cookie"] = f"PHPSESSID=session-{self.sessions_issued}; Path=/"

        self.served.append(request)
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
            if self.indicators_status != 200:
                return httpx.Response(self.indicators_status, headers=headers, text="error")
            params = request.url.params
            return httpx.Response(
                200,
                headers={**headers, "Content-Type": "text/html; charset=UTF-8"},
                text=self._indicators_for(params.get("cliente", ""), params.get("fecha_inicio", ""), params.get("fecha_fin", "")),
            )
        return httpx.Response(404, text="not found")

    def _rows(self) -> pd.DataFrame:
        return pd.read_csv(io.BytesIO(self.alarms_csv), dtype=str, keep_default_na=False, encoding="utf-8-sig")

    def _alarms_for(self, cliente: str) -> bytes:
        df = self._rows()
        wanted = normalize_company_key(cliente)
        df = df[df["cliente"].map(normalize_company_key) == wanted]
        return df.to_csv(index=False).encode("utf-8")

    def _indicators_for(self, cliente: str, start: str, end: str) -> str:
        df = self._rows()
        df = df[df["cliente"].map(normalize_company_key) == normalize_company_key(cliente)]
        if start and end and len(df):
            day = df["timestamp"].str[:10]
            # like the live page: fecha_fin is exclusive
            df = df[(day >= date.fromisoformat(start).isoformat()) & (day < date.fromisoformat(end).isoformat())]
        shown_client = self.indicators_client_override or cliente
        return render_indicators_page(shown_client, start, end, df, total=self.indicators_total_override)


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
