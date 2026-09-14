"""Small read-only endpoints backing the deterministic-flow form's selectors
(empresa, tipo de informe) -- see DETERMINISTIC_FLOW.md. Bundled together
rather than one router file each since both are simple reference-data lookups
with no write operations."""
from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.schemas.api import CompanyOut, ReportTemplateOut
from app.services.repositories import CompanyRepository, ReportTemplateRepository

router = APIRouter(prefix="/api", tags=["reference-data"], dependencies=[Depends(require_auth)])

_companies = CompanyRepository()
_templates = ReportTemplateRepository()


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies():
    return await _companies.list_all()


@router.get("/report-templates", response_model=list[ReportTemplateOut])
async def list_report_templates():
    rows = await _templates.list_active()
    return [{"key": r["key"], "name": r["name"], "description": r.get("description")} for r in rows]
