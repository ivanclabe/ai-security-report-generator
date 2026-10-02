import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_conversation_service
from app.auth import require_user
from app.schemas.api import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    PinConversationRequest,
    SendMessageRequest,
    UpdateConversationRequest,
)
from app.security.context import CurrentUser
from app.services import audit, llm_runtime
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(require_user)])


@router.post("", response_model=ConversationSummary)
async def create_conversation(
    body: CreateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
    user: CurrentUser = Depends(require_user),
):
    return await service.create_conversation(body.title, user=user)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(service: ConversationService = Depends(get_conversation_service)):
    return await service.list_conversations()


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, service: ConversationService = Depends(get_conversation_service)):
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await service.list_messages(conversation_id)
    report = await service.get_report_card_for_conversation(conversation_id)
    return {**conversation, "messages": messages, "report": report}


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    body: UpdateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    return await service.rename_conversation(conversation_id, title)


@router.patch("/{conversation_id}/pin", response_model=ConversationSummary)
async def pin_conversation(
    conversation_id: str,
    body: PinConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await service.set_pinned(conversation_id, body.is_pinned)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, service: ConversationService = Depends(get_conversation_service)
):
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await service.delete_conversation(conversation_id)
    await audit.record(
        "conversation.deleted",
        module="asistente",
        resource_type="conversation",
        resource_id=conversation_id,
        context={"title": conversation.get("title")},
    )
    return Response(status_code=204)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
    user: CurrentUser = Depends(require_user),
):
    conversation = await service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await audit.record(
        "agent.message_sent",
        module="asistente",
        resource_type="conversation",
        resource_id=conversation_id,
        context={"length": len(body.content)},
    )

    async def event_generator():
        selection = await llm_runtime.selection_for(
            body.llm.provider if body.llm else None, body.llm.model if body.llm else None, user
        )
        async for event in service.process_message(conversation_id, body.content, user=user, llm=selection):
            yield {"event": event["event"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())
