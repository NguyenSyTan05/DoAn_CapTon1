"""
slide_schema.py
=================

Pydantic request/response models for the slide-navigation / engagement
diagram feature. [EXISTING LIBRARY: Pydantic]
"""

from __future__ import annotations

from pydantic import BaseModel


class SlideEventRequest(BaseModel):
    slide_number: int


class SlideEventOutput(BaseModel):
    slide_number: int
    started_at: str


class SlideEngagementItem(BaseModel):
    slide_number: int
    question_count: int


class SlideEngagementResponse(BaseModel):
    slides: list[SlideEngagementItem]
