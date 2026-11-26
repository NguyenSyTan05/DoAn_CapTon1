"""
schema.py (modules/summary)
=============================
Hợp đồng dữ liệu Pydantic v2 cho tính năng Tóm tắt bài giảng & Comprehension Heatmap,
tương thích trực tiếp với cấu trúc bảng `lesson_summaries`, `domain_keywords`,
`student_notes` và `confusion_metrics` trong `db.sql`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LectureSection(BaseModel):
    section_index: int = Field(ge=1)
    title: str
    time_range: str = ""
    summary_vi: str
    summary_en: str = ""
    segment_count: int = Field(default=0, ge=0)


class KeyConceptItem(BaseModel):
    concept: str
    explanation_vi: str
    explanation_en: str = ""


class VocabularyItem(BaseModel):
    term_en: str
    term_vi: str
    definition_en: str = ""
    explanation_vi: str = ""
    example_text: str = ""


class ExampleItem(BaseModel):
    timestamp: str = ""
    text_vi: str = ""
    text_en: str = ""


class ClarificationItem(BaseModel):
    topic: str
    question_count: int = Field(default=1, ge=1)
    status: Literal["answered", "pending"] = "pending"
    answer_text: str = ""
    recommendation: str = ""


class HeatmapSlideItem(BaseModel):
    slide_number: int = Field(ge=1)
    question_count: int = Field(default=0, ge=0)
    heat_level: Literal["low", "medium", "high", "critical"] = "low"
    intensity_pct: int = Field(default=0, ge=0, le=100)


class LessonSummaryRecord(BaseModel):
    session_id: str
    lesson_title: str
    detected_subject: str
    overview: str
    overview_en: str = ""
    lecture_structure: list[LectureSection] = Field(default_factory=list)
    key_concepts: list[KeyConceptItem] = Field(default_factory=list)
    vocabulary: list[VocabularyItem] = Field(default_factory=list)
    examples: list[ExampleItem] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list)
    further_clarification: list[ClarificationItem] = Field(default_factory=list)
    heatmap: list[HeatmapSlideItem] = Field(default_factory=list)
    transcript_count: int = Field(default=0, ge=0)
    question_count: int = Field(default=0, ge=0)
    version_number: int = Field(default=1, ge=1)
    model_name: str = "hybrid-minilm-nllb-v1"
    generation_status: Literal["EMPTY", "COMPLETED"] = "COMPLETED"
    updated_at: str


class SummaryGenerateRequest(BaseModel):
    lesson_title: str | None = Field(default=None, max_length=255)
    lecturer_notes: str | None = Field(default=None, max_length=4000)


class SummaryUpdateRequest(BaseModel):
    lesson_title: str | None = Field(default=None, max_length=255)
    detected_subject: str | None = Field(default=None, max_length=200)
    overview: str | None = Field(default=None, max_length=8000)
    overview_en: str | None = Field(default=None, max_length=8000)
    key_takeaways: list[str] | None = None
    vocabulary: list[VocabularyItem] | None = None


class StudentNoteOutput(BaseModel):
    note_id: str
    owner: str
    session_id: str
    title: str
    content: str
    source_type: Literal["PERSONAL", "AI_COPY", "LECTURER"] = "PERSONAL"
    is_pinned: bool = False
    updated_at: str


class StudentNoteRequest(BaseModel):
    note_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=20000)
    source_type: Literal["PERSONAL", "AI_COPY", "LECTURER"] = "PERSONAL"
    is_pinned: bool = False


class StudentNoteListResponse(BaseModel):
    notes: list[StudentNoteOutput]
