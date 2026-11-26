"""
schema.py (modules/qa)
=======================

Pydantic request/response models cho cụm Q&A: câu hỏi sinh viên gửi lên
(QuestionInput/QuestionListResponse) và câu trả lời của giảng viên
(AnswerRequest/AnswerOutput/AnswerListResponse). [EXISTING LIBRARY: Pydantic]

Chỉ validate hình dạng/kiểu dữ liệu — luật nghiệp vụ (text không rỗng,
timestamp hợp lệ...) nằm ở service, xem
modules/question_clustering/semantic_question_aggregator.py.
"""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Câu hỏi
# ---------------------------------------------------------------------------

class QuestionInput(BaseModel):
    id: str
    text: str
    timestamp: str


class QuestionListResponse(BaseModel):
    questions: list[QuestionInput]


# ---------------------------------------------------------------------------
# Câu trả lời
# ---------------------------------------------------------------------------

class AnswerRequest(BaseModel):
    representative_id: str
    representative_text: str
    total_count: int
    answer_text: str


class AnswerOutput(BaseModel):
    representative_id: str
    representative_text: str
    total_count: int
    answer_text: str
    answered_at: str
    answer_vi: str = ""
    answer_en: str = ""


class AnswerListResponse(BaseModel):
    answers: list[AnswerOutput]
