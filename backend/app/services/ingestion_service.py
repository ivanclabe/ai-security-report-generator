"""Records import metadata (which file, when, how many rows, which warnings)
into Supabase (in_companies / in_data_sources / in_data_imports) as a
side-channel to the in-memory ExcelDataProvider -- see INGESTION_ARCHITECTURE.md.

Deliberately NOT on the request path: ExcelDataProvider is built once per
process (cached in providers/factory.py) synchronously; this module is called
once from the FastAPI lifespan after the provider is already built. A
Supabase outage here must not block the backend from serving requests --
callers should catch and log, not propagate.
"""
import hashlib
import logging
import re
from pathlib import Path

from app.providers.excel import ExcelDataProvider
from app.services import supabase_rest as db
from app.services.db import new_id, now_iso

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "client"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _ensure_company(company_id: str, name: str) -> None:
    existing = await db.select("in_companies", filters={"id": company_id})
    if existing:
        return
    await db.insert(
        "in_companies",
        {"id": company_id, "name": name, "industry": None, "country": None, "created_at": now_iso()},
    )


async def _ensure_data_source(company_id: str, source_type: str, name: str) -> str:
    existing = await db.select(
        "in_data_sources", filters={"company_id": company_id, "source_type": source_type}
    )
    if existing:
        return existing[0]["id"]
    row = await db.insert(
        "in_data_sources",
        {
            "id": new_id("source"),
            "company_id": company_id,
            "source_type": source_type,
            "name": name,
            "config": {},
            "is_active": True,
            "created_at": now_iso(),
        },
    )
    return row["id"]


async def record_excel_import(provider: ExcelDataProvider, excel_path: Path) -> list[dict]:
    """Upserts a company + data source per distinct client found in the sheet,
    then records one in_data_imports row per company -- skipping companies that
    already have an import with the same file_hash (avoids duplicate audit rows
    when the backend restarts without the source file changing)."""
    file_hash = _file_hash(excel_path)
    warnings = provider.ingestion_warnings
    alerts = provider.alerts
    status = "failed" if not alerts and warnings else ("partial" if warnings else "success")

    alerts_by_client: dict[str, int] = {}
    for alert in alerts:
        alerts_by_client[alert.client] = alerts_by_client.get(alert.client, 0) + 1

    created: list[dict] = []
    for client_name, row_count in alerts_by_client.items():
        company_id = _slugify(client_name)
        await _ensure_company(company_id, client_name)
        data_source_id = await _ensure_data_source(company_id, "excel", f"Excel — {client_name}")

        existing_import = await db.select(
            "in_data_imports", filters={"data_source_id": data_source_id, "file_hash": file_hash}
        )
        if existing_import:
            logger.info(
                "Import already recorded for %s (hash=%s, import_id=%s) -- skipping duplicate",
                client_name,
                file_hash[:12],
                existing_import[0]["id"],
            )
            created.append(existing_import[0])
            continue

        timestamp = now_iso()
        import_row = await db.insert(
            "in_data_imports",
            {
                "id": new_id("import"),
                "data_source_id": data_source_id,
                "company_id": company_id,
                "source_file_ref": excel_path.name,
                "file_hash": file_hash,
                "status": status,
                "row_count": row_count,
                "warning_count": len(warnings),
                "warnings": warnings,
                "imported_by": None,
                "started_at": timestamp,
                "completed_at": timestamp,
                "created_at": timestamp,
            },
        )
        created.append(import_row)

    return created
