"""
router.py (modules/translate)
===============================
ON-DEMAND TEXT TRANSLATION.
[EXISTING LIBRARY: NLLB-200, qua AiService — không phải model mới] Dùng
cho nút "Dịch" cạnh câu hỏi đại diện trên Dashboard Giảng viên (giảng viên
chỉ đọc tiếng Anh, câu hỏi có thể là tiếng Việt). Khác với bước song ngữ
hoá nội bộ trong semantic_question_aggregator.py (dùng để encode cho
clustering, không trả ra ngoài) — endpoint này dịch 1 đoạn text CỤ THỂ theo
yêu cầu, trả thẳng bản dịch để hiển thị.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from core.ai import ai_service
from modules.translate.schema import TranslateRequest, TranslateResponse

router = APIRouter()


@router.post("/api/v1/translate", response_model=TranslateResponse)
async def translate_text(payload: TranslateRequest):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    src_lang = ai_service.detect_language(text)
    tgt_lang = "en" if src_lang == "vi" else "vi"

    try:
        translated = await asyncio.to_thread(
            ai_service.transcript_text, text, src_lang, tgt_lang
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return TranslateResponse(
        translated_text=translated, source_lang=src_lang, target_lang=tgt_lang
    )
