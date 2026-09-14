"""Shared SSE progress-event vocabulary -- both the conversational flow
(conversation_service.py, driven by LangGraph node names) and the
deterministic flow (pipeline.py, driven by pipeline stage names) emit the
same {"event": "progress", "message": ...} shape so the frontend can reuse
one rendering path (ProgressStatus.tsx) for both modalities."""

STATUS_MESSAGES = {
    "understand_request": "Entendiendo la solicitud...",
    "collect_data": "Consultando alarmas de seguridad...",
    "analyze_data": "Analizando los datos de seguridad...",
    "generate_report_specification": "Construyendo el informe...",
    "validate_report_specification": "Validando la estructura del informe...",
    "generate_document": "Generando el documento...",
    "validate_document": "Validando el documento...",
    "ask_user": "Esperando tu respuesta...",
    "answer_question": "Consultando los datos...",
    "return_result": "Finalizando...",
}
