"""Data models for the Teacher Knowledge Base (RAG) pipeline.

Only files with purpose="rag_material" are processed by this pipeline.
"""

from __future__ import annotations

from enum import Enum

from models.base import CamelModel


class ParseStatus(str, Enum):
    """Document parse status — synced with Java ai_files.parse_status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ParseOptions(CamelModel):
    """Optional parsing configuration sent by Java."""

    parse_method: str = "auto"  # auto / mineru / docling
    process_images: bool = True
    process_tables: bool = True
    process_equations: bool = True


class ParseRequest(CamelModel):
    """Request from Java backend to parse a resource library document.

    Java sends this ONLY for files with purpose="rag_material".
    Studio files (analysis, lesson_material, general) never reach this endpoint.
    """

    file_id: str
    teacher_id: str
    oss_url: str
    file_name: str = ""
    purpose: str = "rag_material"
    parse_options: ParseOptions | None = None


class ParseResult(CamelModel):
    """Result of document parsing, sent back to Java via callback."""

    file_id: str
    parse_status: ParseStatus
    chunk_count: int = 0
    entity_count: int = 0
    error_message: str | None = None


class DocumentChunk(CamelModel):
    """A retrieved document chunk from RAG search."""

    content: str
    source: str = ""  # e.g. "teacher-123/教案.pdf" or "public/dse-math"
    score: float = 0.0
    metadata: dict = {}
