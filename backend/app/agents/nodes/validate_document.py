from pathlib import Path

from app.agents.state import ReportState


async def validate_document(state: ReportState) -> dict:
    if state.get("status") == "error":
        # generate_document already recorded a specific error (e.g. PDF conversion
        # failed) -- don't overwrite it with the generic message below.
        return {}
    file_path = state.get("report_file_path")
    if not file_path or not Path(file_path).exists() or Path(file_path).stat().st_size == 0:
        return {"status": "error", "errors": ["El documento no se generó correctamente."]}
    return {"status": "ready", "errors": []}
