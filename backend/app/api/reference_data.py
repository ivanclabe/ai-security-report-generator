"""Small read-only endpoints backing the deterministic-flow form's selectors
(empresa, tipo de informe) -- see DETERMINISTIC_FLOW.md. Bundled together
rather than one router file each since both are simple reference-data lookups
with no write operations."""
from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.schemas.api import CompanyOut, ReportTemplateOut
from app.services.company_registry import get_company_registry
from app.services.repositories import ReportTemplateRepository

router = APIRouter(prefix="/api", tags=["reference-data"], dependencies=[Depends(require_auth)])

_templates = ReportTemplateRepository()


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies():
    """The client's official company list (company registry, in_companies)."""
    companies = await get_company_registry().list_active()
    return [
        {"id": c.id, "name": c.name, "logo_key": c.logo_key, "consecutivo": c.consecutivo} for c in companies
    ]


@router.get("/report-templates", response_model=list[ReportTemplateOut])
async def list_report_templates():
    rows = await _templates.list_active()
    return [{"key": r["key"], "name": r["name"], "description": r.get("description")} for r in rows]
