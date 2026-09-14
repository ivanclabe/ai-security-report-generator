from fastapi import Request

from app.services.conversation_service import ConversationService


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service
