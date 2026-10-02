"""Records import metadata (which request, when, how many rows, which warnings)
into Supabase (in_data_sources / in_data_imports) every time the acquisition
layer fetches fresh data from the source -- see INGESTION_ARCHITECTURE.md.

Deliberately a side-channel hooked in as AlarmAcquisitionService's `on_fetch`
listener, not part of the request path: a Supabase outage here must not fail a
report (the listener swallows and logs). Companies themselves are not created
here -- the company registry (in_companies) is the authority on which companies
exist; an import is only ever recorded against a registered company.
"""
import logging

from app.ingestion.service import AlarmBatch
from app.services import supabase_rest as db
from app.services.db import new_id, now_iso

logger = logging.getLogger(__name__)

SOURCE_TYPE = "api"


async def _ensure_data_source(company_id: str, name: str) -> str:
    existing = await db.select("in_data_sources", filters={"company_id": company_id, "source_type": SOURCE_TYPE})
    if existing:
        return existing[0]["id"]
    row = await db.insert(
        "in_data_sources",
        {
            "id": new_id("source"),
            "company_id": company_id,
            "source_type": SOURCE_TYPE,
            "name": name,
            "config": {},  # address/credentials live in backend/.env, never in the database
            "is_active": True,
            "created_at": now_iso(),
        },
    )
    return row["id"]


async def record_import(batch: AlarmBatch) -> dict:
    """One in_data_imports row per distinct payload (content hash) -- re-fetching
    unchanged data does not add audit rows."""
    company = batch.company
    data_source_id = await _ensure_data_source(company.id, f"Albatroz — {company.name}")

    existing = await db.select(
        "in_data_imports", filters={"data_source_id": data_source_id, "file_hash": batch.content_hash}
    )
    if existing:
        logger.info("Import ya registrado para %s (hash=%s) -- sin duplicar", company.name, batch.content_hash[:12])
        return existing[0]

    status = "failed" if not batch.alerts and batch.warnings else ("partial" if batch.warnings else "success")
    timestamp = now_iso()
    return await db.insert(
        "in_data_imports",
        {
            "id": new_id("import"),
            "data_source_id": data_source_id,
            "company_id": company.id,
            "source_file_ref": batch.request_url,
            "file_hash": batch.content_hash,
            "status": status,
            "row_count": len(batch.alerts),
            "warning_count": len(batch.warnings),
            "warnings": batch.warnings,
            "imported_by": None,
            "started_at": timestamp,
            "completed_at": timestamp,
            "created_at": timestamp,
        },
    )
