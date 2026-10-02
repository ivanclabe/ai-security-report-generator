from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"

    # "http" = the remote alarm source (SOURCE_* below); "mock" = synthetic demo/test data.
    data_provider: str = "http"
    mock_data_path: Path = PROJECT_ROOT / "data" / "mock_security_data.json"
    mitre_tactics_path: Path = PROJECT_ROOT / "data" / "mitre_tactics.json"

    # --- Alarm data source (HTTP) --------------------------------------------
    # Every address and credential lives here (backend/.env), never in code:
    # moving the source to another IP/host is a one-line change to
    # SOURCE_BASE_URL. Credentials are SecretStr so they never show up in
    # repr()/logs of this object.
    source_base_url: str = ""
    # Relative to SOURCE_BASE_URL, or an absolute http(s) URL if an endpoint lives elsewhere.
    source_alarms_path: str = "/detallado_alarmas.php"
    source_indicators_path: str = "/indicadores.php"
    source_username: str = ""
    source_password: SecretStr = SecretStr("")
    # True = verify the server certificate with the system CAs. For an internal
    # server with its own CA set SOURCE_CA_BUNDLE to that CA file instead of
    # turning verification off.
    source_verify_tls: bool = True
    source_ca_bundle: str = ""
    source_timeout_seconds: float = 30.0
    # Upper bound sent as `limite=`; a response with exactly this many rows is
    # reported as possibly truncated.
    source_alarms_limit: int = 1000
    source_cache_ttl_seconds: int = 300
    # Compare each alarms download with the source's indicators page (see SourceConfig).
    source_reconcile_indicators: bool = True
    # Address/username/password saved from the app (Configuración > Fuente de datos) override
    # the SOURCE_* values above; stored here with 0600 permissions (see source_settings_store.py).
    source_settings_path: Path = BACKEND_DIR / "source_settings.json"

    sqlite_checkpoint_db_path: Path = BACKEND_DIR / "agent_checkpoints.sqlite3"

    reports_dir: Path = BACKEND_DIR / "generated_reports"

    # Binary used to convert the generated .docx to PDF (headless LibreOffice) --
    # see app/services/report/document.py. Override if it's not on PATH under this name.
    soffice_binary: str = "soffice"

    # "development" | "production" -- gates the insecure-defaults startup check in
    # main.py (SECURITY_REVIEW.md). Set SYSTEM_VERSION at container build time
    # (e.g. from `git rev-parse --short HEAD` in CI) for images built without a
    # .git directory -- see app/services/system_version.py.
    environment: str = "development"
    system_version: str = ""

    cors_origins: list[str] = ["http://localhost:5173"]

    # Conversations/messages/reports live in Supabase (tables prefixed "in_"),
    # accessed server-side only via PostgREST + the anon key (never shipped to the
    # frontend) -- RLS on those tables grants that key full access, scoped to just
    # these tables so it can't touch anything else in a shared Supabase project.
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # Single hardcoded operator login (not per-user Supabase Auth -- there's only
    # ever one credential pair here) issuing a signed session JWT.
    auth_username: str = "master"
    auth_password: str = "123456"
    auth_secret_key: str = "dev-insecure-change-me"
    auth_token_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    return settings
