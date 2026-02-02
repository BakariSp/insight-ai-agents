"""API request / response models."""

from __future__ import annotations

from models.base import CamelModel
from models.blueprint import Blueprint


class WorkflowGenerateRequest(CamelModel):
    """POST /api/workflow/generate — request body."""

    user_prompt: str
    language: str = "en"
    teacher_id: str = ""
    context: dict | None = None


class WorkflowGenerateResponse(CamelModel):
    """POST /api/workflow/generate — response body."""

    blueprint: Blueprint
    model: str = ""


class PageGenerateRequest(CamelModel):
    """POST /api/page/generate — request body."""

    blueprint: Blueprint
    context: dict | None = None
    teacher_id: str = ""


class PageChatRequest(CamelModel):
    """POST /api/page/chat — request body."""

    message: str
    page_context: dict | None = None
    conversation_id: str | None = None


class PageChatResponse(CamelModel):
    """POST /api/page/chat — response body."""

    response: str
    conversation_id: str
