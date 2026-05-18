from __future__ import annotations
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Language = Literal["en"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    language: Optional[Language] = None
    session_id: Optional[str] = None
    channel: Literal["web"] = "web"


class ChatResponse(BaseModel):
    answer: str
    language: Language = "en"
    confidence: float
    needs_human: bool = False
    ui_action: Optional[str] = None


class SessionResetRequest(BaseModel):
    session_id: str


class SessionHistoryItem(BaseModel):
    session_id: str
    channel: Literal["web"] = "web"
    started_at: str
    last_activity_at: str
    message_count: int
    last_role: str
    preview: str
    latest_satisfaction: Optional[Literal["yes", "no"]] = None
    latest_satisfaction_at: Optional[str] = None


class FAQItem(BaseModel):
    id: str
    question: str = Field(min_length=2, max_length=400)
    answer: str = Field(min_length=2, max_length=4000)
    tags: List[str] = Field(default_factory=list)


class FAQUpsertRequest(BaseModel):
    question: str
    answer: str
    tags: List[str] = Field(default_factory=list)


class ReindexRequest(BaseModel):
    full_crawl: bool = True


class ReindexResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int


class HandoffResolveRequest(BaseModel):
    note: str = ""


class HandoffReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    operator_name: str = "Operator"


class HandoffAiModeRequest(BaseModel):
    ai_enabled: bool = True


class SupportContactRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    question: str = Field(min_length=2, max_length=4000)
    session_id: Optional[str] = None


class SupportContactResponse(BaseModel):
    ok: bool = True
    handoff_id: str
    message: str


class SatisfactionFeedbackRequest(BaseModel):
    response: Literal["yes", "no"]
    session_id: Optional[str] = None


class QuickActionItem(BaseModel):
    id: str
    question: str = Field(default="", max_length=200)
    answer: str = Field(default="", max_length=4000)
    enabled: bool = True
    sort_order: int = 0


class QuickActionsUpdateRequest(BaseModel):
    items: list[QuickActionItem] = Field(default_factory=list)


class PublicQuickActionItem(BaseModel):
    id: str
    question: str
    action: Literal["message"] = "message"


class LinkRuleItem(BaseModel):
    id: str
    question_pattern: str
    mode: Literal["manual", "disable"] = "manual"
    url: str = ""
    note: str = ""
    enabled: bool = True
    created_at: str
    updated_at: str


class LinkRuleUpsertRequest(BaseModel):
    question_pattern: str = Field(min_length=2, max_length=200)
    mode: Literal["manual", "disable"] = "manual"
    url: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=400)
    enabled: bool = True
