from typing import Literal

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    title: str | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    is_pinned: bool = False
    created_at: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class ReportOut(BaseModel):
    report_id: str
    version: int
    title: str | None
    section_count: int
    objective: str | None = None
    format: str = "docx"


class ConversationDetail(BaseModel):
    id: str
    title: str | None
    is_pinned: bool = False
    created_at: str
    messages: list[MessageOut]
    report: ReportOut | None = None


class LLMSelectionIn(BaseModel):
    """Provider/model for one execution (Cloud, Local, vLLM or Auto). Omitted = the user's default."""

    provider: Literal["auto", "cloud", "local", "vllm"]
    model: str | None = Field(default=None, max_length=200)


class SendMessageRequest(BaseModel):
    content: str
    llm: LLMSelectionIn | None = None


class UpdateConversationRequest(BaseModel):
    title: str


class PinConversationRequest(BaseModel):
    is_pinned: bool


class CompanyOut(BaseModel):
    id: str
    name: str
    logo_key: str | None = None
    consecutivo: str | None = None


class ReportTemplateOut(BaseModel):
    key: str
    name: str
    description: str | None = None
