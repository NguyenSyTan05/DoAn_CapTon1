"""
router.py (modules/question_clustering)
=========================================
Semantic Question Aggregation (REST): gom cụm câu hỏi song ngữ EN/VI và
chọn câu đại diện — module NCKH của đề tài. Logic thuật toán nằm ở
semantic_question_aggregator.py / clustering_strategies.py; file này chỉ là
lớp HTTP mỏng.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from modules.question_clustering.schema import (
    AggregateRequest,
    AggregateResponse,
    ErrorResponse,
)
from modules.question_clustering.semantic_question_aggregator import (
    CustomSemanticQuestionAggregator,
    InvalidQuestionError,
)

router = APIRouter()


@router.post(
    "/api/v1/questions/aggregate",
    response_model=AggregateResponse,
    responses={422: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def aggregate_questions(payload: AggregateRequest, request: Request):
    """Gom cụm câu hỏi song ngữ EN/VI và chọn câu hỏi đại diện cho Giảng viên."""
    aggregator: CustomSemanticQuestionAggregator = request.app.state.aggregator
    if aggregator is None:
        raise HTTPException(
            status_code=503,
            detail="AI đang khởi động, vui lòng thử lại sau vài giây.",
        )
    raw = [q.model_dump() for q in payload.questions]

    try:
        # Xử lý embedding, cosine similarity, connected components & medoid
        result = await asyncio.to_thread(aggregator.aggregate, raw)
    except InvalidQuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return result
