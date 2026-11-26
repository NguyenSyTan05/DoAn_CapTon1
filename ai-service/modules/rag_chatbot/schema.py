from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CitationItem(BaseModel):
    label: str
    source_type: Literal["SLIDE", "TRANSCRIPT"]
    slide_number: int | None = None
    timestamp: str = ""
    excerpt: str = ""
    score: float = 0.0


class ChatbotAskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=600)


class ChatbotAskResponse(BaseModel):
    message_id: str
    question: str
    answer: str
    status: Literal["ANSWERED", "NO_SOURCE_FOUND"]
    confidence: float
    citations: list[CitationItem] = Field(default_factory=list)
    can_escalate: bool = False


class ChatbotEscalateRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=600)
    reason: str = Field(default="NO_SOURCE_FOUND", max_length=200)


class ChatbotEscalateResponse(BaseModel):
    escalation_id: str
    forwarded_question_id: str
    message: str


class ChatbotHistoryItem(BaseModel):
    message_id: str
    question: str
    answer: str
    status: Literal["ANSWERED", "NO_SOURCE_FOUND"]
    citations: list[CitationItem] = Field(default_factory=list)
    created_at: str


class ChatbotHistoryResponse(BaseModel):
    items: list[ChatbotHistoryItem] = Field(default_factory=list)
