"""Skill configuration models — per-request skill toggles.

Carried on each conversation request to control which skills are enabled.
Knowledge/RAG skills are off by default; file context auto-enables when
the teacher uploads a document.
"""

from __future__ import annotations

from models.base import CamelModel


class SkillConfig(CamelModel):
    """Per-request skill configuration sent from the frontend."""

    enable_rag_search: bool = False
    enable_file_context: bool = False
    uploaded_file_content: str | None = None
