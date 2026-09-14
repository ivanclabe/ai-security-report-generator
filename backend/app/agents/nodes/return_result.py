from app.agents.state import ReportState


async def return_result(state: ReportState) -> dict:
    if state.get("status") == "error":
        errors = state.get("errors") or ["Ocurrió un error desconocido al generar el informe."]
        message = "Tuve un problema al generar el informe:\n" + "\n".join(f"- {e}" for e in errors)
        return {"assistant_message": message}

    spec = state.get("report_specification") or {}
    section_count = len(spec.get("sections", []))
    message = (
        f"Tu informe de gestión de {state.get('company')} "
        f"({state.get('start_date')} a {state.get('end_date')}) está listo — {section_count} secciones.\n\n"
        f"{spec.get('objective', '')}"
    )
    return {"assistant_message": message, "status": "ready"}
