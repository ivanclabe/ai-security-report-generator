from app.services import supabase_rest as db
from app.services.db import new_id, now_iso


class ConversationRepository:
    async def create(self, title: str | None = None) -> dict:
        return await db.insert(
            "in_conversations",
            {"id": new_id("conv"), "title": title, "is_pinned": False, "created_at": now_iso()},
        )

    async def get(self, conversation_id: str) -> dict | None:
        rows = await db.select("in_conversations", filters={"id": conversation_id})
        return rows[0] if rows else None

    async def add_message(self, conversation_id: str, role: str, content: str) -> dict:
        return await db.insert(
            "in_messages",
            {
                "id": new_id("msg"),
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": now_iso(),
            },
        )

    async def list_messages(self, conversation_id: str) -> list[dict]:
        return await db.select(
            "in_messages", filters={"conversation_id": conversation_id}, order="created_at.asc"
        )

    async def list_all(self) -> list[dict]:
        return await db.select("in_conversations", order="is_pinned.desc,created_at.desc")

    async def rename(self, conversation_id: str, title: str) -> dict | None:
        return await db.update("in_conversations", {"id": conversation_id}, {"title": title})

    async def set_pinned(self, conversation_id: str, is_pinned: bool) -> dict | None:
        return await db.update("in_conversations", {"id": conversation_id}, {"is_pinned": is_pinned})

    async def delete(self, conversation_id: str) -> None:
        # ON DELETE CASCADE on in_messages/in_reports/in_report_versions handles the rest.
        await db.delete("in_conversations", {"id": conversation_id})


class ReportRepository:
    async def get_or_create_for_conversation(
        self, conversation_id: str, company: str | None, company_id: str | None = None
    ) -> dict:
        rows = await db.select("in_reports", filters={"conversation_id": conversation_id})
        if rows:
            return rows[0]
        return await db.insert(
            "in_reports",
            {
                "id": new_id("report"),
                "conversation_id": conversation_id,
                "company": company,
                "company_id": company_id,
                "created_at": now_iso(),
            },
        )

    async def add_version(
        self,
        report_id: str,
        file_path: str,
        specification: dict,
        change_summary: str | None,
        template_id: str | None = None,
        format: str = "docx",
    ) -> dict:
        existing = await db.select(
            "in_report_versions", filters={"report_id": report_id}, order="version.desc", limit=1
        )
        next_version = (existing[0]["version"] if existing else 0) + 1

        row = await db.insert(
            "in_report_versions",
            {
                "id": new_id("ver"),
                "report_id": report_id,
                "version": next_version,
                "file_path": file_path,
                "specification_json": specification,
                "change_summary": change_summary,
                "template_id": template_id,
                "format": format,
                "created_at": now_iso(),
            },
        )
        row["specification"] = row.pop("specification_json")
        return row

    async def get_report(self, report_id: str) -> dict | None:
        rows = await db.select("in_reports", filters={"id": report_id})
        return rows[0] if rows else None

    async def get_for_conversation(self, conversation_id: str) -> dict | None:
        """Read-only lookup (unlike get_or_create_for_conversation) -- for
        reconstructing a conversation's report card on history load without
        accidentally creating an empty in_reports row for a conversation that
        never generated one."""
        rows = await db.select("in_reports", filters={"conversation_id": conversation_id})
        return rows[0] if rows else None

    async def get_latest_version(self, report_id: str) -> dict | None:
        rows = await db.select(
            "in_report_versions", filters={"report_id": report_id}, order="version.desc", limit=1
        )
        if not rows:
            return None
        row = rows[0]
        row["specification"] = row.pop("specification_json")
        return row

    async def list_versions(self, report_id: str) -> list[dict]:
        rows = await db.select(
            "in_report_versions", filters={"report_id": report_id}, order="version.asc"
        )
        for row in rows:
            row["specification"] = row.pop("specification_json")
        return rows

    async def delete_for_conversation(self, conversation_id: str) -> None:
        # ON DELETE CASCADE on in_report_versions handles the rest.
        await db.delete("in_reports", {"conversation_id": conversation_id})


class CompanyRepository:
    """Reads in_companies -- populated by ingestion_service.py (Fase 3) as a
    side effect of importing each client's data source. Backs the "Empresa"
    selector in the deterministic-flow form (DETERMINISTIC_FLOW.md)."""

    async def list_all(self) -> list[dict]:
        return await db.select("in_companies", order="name.asc")


class ReportTemplateRepository:
    async def list_active(self) -> list[dict]:
        return await db.select("in_report_templates", filters={"is_active": True}, order="name.asc")


class UserRepository:
    """Reads in_users -- seeded with a single 'master' row today (see
    supabase_schema.sql). Not Supabase Auth: backs QUALITY_OBSERVABILITY.md's
    "¿qué usuario lo generó?" audit question, attributing executions to the
    authenticated username without assuming multi-user auth exists yet."""

    async def get_by_username(self, username: str) -> dict | None:
        rows = await db.select("in_users", filters={"username": username})
        return rows[0] if rows else None
