import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_conversation_service
from app.auth import require_auth
from app.services.conversation_service import ConversationService
from app.services.report.request import ReportRequest

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(require_auth)])


@router.post("/generate")
async def generate_report(
    body: ReportRequest,
    service: ConversationService = Depends(get_conversation_service),
    username: str = Depends(require_auth),
):
    """Modalidad 1 (formulario/determinístico) -- see DETERMINISTIC_FLOW.md.
    Registered before /{report_id} so the literal path "generate" isn't
    swallowed by that dynamic route."""

    async def event_generator():
        async for event in service.generate_report_deterministic(body, username=username):
            yield {"event": event["event"], "data": json.dumps(event, default=str)}

    return EventSourceResponse(event_generator())


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
    return FileResponse(path=file_path, media_type=media_type, filename=filename)
