"""
translate_schema.py
=====================

Pydantic request/response models for on-demand text translation.
[EXISTING LIBRARY: Pydantic] — same shape/type-only validation convention
as the other schema files.
"""

from __future__ import annotations

from pydantic import BaseModel


class TranslateRequest(BaseModel):
    text: str


class TranslateResponse(BaseModel):
    translated_text: str
    source_lang: str
    target_lang: str
