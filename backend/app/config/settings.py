from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"

    data_provider: str = "excel"
    mock_data_path: Path = PROJECT_ROOT / "data" / "mock_security_data.json"
    excel_data_path: Path = PROJECT_ROOT / "data" / "thomas_tgs_tps_alarmas_julio.xlsx"
    excel_sheet_name: str = "Alarmas"
    mitre_tactics_path: Path = PROJECT_ROOT / "data" / "mitre_tactics.json"

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
