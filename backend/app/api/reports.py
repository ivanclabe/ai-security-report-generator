import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_conversation_service
from app.auth import require_user
from app.security.context import CurrentUser
from app.services import audit
from app.services.conversation_service import ConversationService
from app.services.report.request import ReportRequest

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(require_user)])


@router.post("/generate")
async def generate_report(
    body: ReportRequest,
    service: ConversationService = Depends(get_conversation_service),
    user: CurrentUser = Depends(require_user),
):
    """Modalidad 1 (formulario/determinístico) -- see DETERMINISTIC_FLOW.md.
    Registered before /{report_id} so the literal path "generate" isn't
    swallowed by that dynamic route."""

    await audit.record(
        "report.generation_requested",
        module="informes",
        context={"company": body.company or body.company_id, "period": f"{body.start_date} a {body.end_date}",
                 "report_type": body.report_type, "format": body.format},
    )

    async def event_generator():
        async for event in service.generate_report_deterministic(body, user=user):
            yield {"event": event["event"], "data": json.dumps(event, default=str)}

    return EventSourceResponse(event_generator())


@router.get("")
async def list_reports(limit: int = 20, service: ConversationService = Depends(get_conversation_service)):
    """Recent reports (latest version of each) -- Inicio and "¿dónde están mis informes?"."""
    return await service.list_recent_reports(max(1, min(limit, 50)))


@router.get("/{report_id}")
async def get_report(report_id: str, service: ConversationService = Depends(get_conversation_service)):
    report = await service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    latest = await service.get_latest_version(report_id)
    return {**report, "latest_version": latest}


@router.get("/{report_id}/download")
async def download_report(report_id: str, service: ConversationService = Depends(get_conversation_service)):
    report = await service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    latest = await service.get_latest_version(report_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No document has been generated yet")

    file_path = Path(latest["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Document file is missing on disk")

    # Determined from the actual file on disk, not a hardcoded assumption -- format
    # is per-version (a report can have a .docx v1 and a .pdf v2), see DocumentService.
    extension = file_path.suffix.lstrip(".") or "docx"
    media_type = (
        "application/pdf"
        if extension == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    filename = f"{report.get('company') or 'security-report'}-v{latest['version']}.{extension}".replace(" ", "-")
    await audit.record(
        "report.downloaded",
        module="informes",
        resource_type="report",
        resource_id=report_id,
        context={"version": latest["version"], "format": extension, "company": report.get("company")},
    )
    return FileResponse(path=file_path, media_type=media_type, filename=filename)
