"""
schema.py (modules/question_clustering)
=========================================

Pydantic request/response models cho API gom cụm câu hỏi ngữ nghĩa.
[EXISTING LIBRARY: Pydantic]

Design note: các model này chỉ validate *hình dạng và kiểu*. Luật nghiệp
vụ sâu (text không rỗng, timestamp ISO-8601 hợp lệ, từ chối id trùng) nằm ở
`CustomSemanticQuestionAggregator.parse_and_validate`
(semantic_question_aggregator.py) — service là nguồn sự thật duy nhất và
vẫn test được mà không cần FastAPI.

QuestionInput là thực thể "câu hỏi" dùng chung với cụm Q&A nên được import
từ modules.qa.schema thay vì định nghĩa lặp lại.
"""

from __future__ import annotations

from pydantic import BaseModel

from modules.qa.schema import QuestionInput


class AggregateRequest(BaseModel):
    questions: list[QuestionInput]


class QuestionEcho(BaseModel):
    id: str
    text: str


class ClusterOutput(BaseModel):
    cluster_id: int
    representative_id: str
    representative_text: str
    total_count: int
    mean_similarity: float
    questions: list[QuestionEcho]


class MetricsOutput(BaseModel):
    total_questions: int
    total_clusters: int
    average_cluster_size: float
    largest_cluster_size: int
    singleton_clusters: int
    mean_intra_cluster_similarity: float


class TimingBreakdownOutput(BaseModel):
    translation_time_ms: float
    embedding_time_ms: float
    similarity_time_ms: float
    clustering_time_ms: float
    representative_time_ms: float
    serialization_time_ms: float
    total_processing_time_ms: float


class AggregateResponse(BaseModel):
    clusters: list[ClusterOutput]
    compression_ratio: float
    execution_time_ms: float
    timing_breakdown_ms: TimingBreakdownOutput
    clustering_strategy: str
    metrics: MetricsOutput


class ErrorResponse(BaseModel):
    detail: str
