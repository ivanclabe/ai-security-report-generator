from pydantic import BaseModel


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


class SendMessageRequest(BaseModel):
    content: str


class UpdateConversationRequest(BaseModel):
    title: str


class PinConversationRequest(BaseModel):
    is_pinned: bool


class CompanyOut(BaseModel):
    id: str
    name: str


class ReportTemplateOut(BaseModel):
    key: str
    name: str
    description: str | None = None
