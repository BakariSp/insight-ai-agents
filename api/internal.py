"""Internal API endpoints — called by Java backend (not by end users).

All endpoints require X-Internal-Secret header for authentication.

Only resource library files (purpose="rag_material") should be sent here.
Java is responsible for filtering: only call /documents/parse when
the uploaded file has purpose="rag_material". Studio files (analysis,
lesson_material, general) are NOT RAG-indexed.
"""

from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from insight_backend.auth import verify_internal_secret
from pydantic import BaseModel

from insight_backend.models import ParseRequest, ParseResult, ParseStatus
from insight_backend.rag_engine import download_file, get_rag_engine
from insight_backend.document_adapter import get_file_download_url, update_parse_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.post("/documents/parse")
async def parse_document(
    req: ParseRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Accept a document parse request from Java backend.

    Java calls this ONLY for resource library files (purpose="rag_material").
    Parsing runs asynchronously in the background.
    """
    verify_internal_secret(request)

    # Defensive check: only process rag_material files
    if req.purpose != "rag_material":
        raise HTTPException(
            status_code=400,
            detail=f"Only purpose='rag_material' files should be sent for RAG parsing, "
                   f"got purpose='{req.purpose}'",
        )

    logger.info(
        "Received parse request: file_id=%s, teacher_id=%s, file_name=%s, purpose=%s",
        req.file_id, req.teacher_id, req.file_name, req.purpose,
    )

    # Schedule async background parsing
    background_tasks.add_task(
        _do_parse,
        file_id=req.file_id,
        teacher_id=req.teacher_id,
        oss_url=req.oss_url,
        file_name=req.file_name,
    )

    return {"status": "accepted", "fileId": req.file_id}


class SearchRequest(BaseModel):
    teacher_id: str
    query: str
    mode: str = "hybrid"
    include_public: bool = True
    top_k: int = 5


@router.post("/documents/search")
async def search_documents(req: SearchRequest, request: Request):
    """Search the teacher's RAG knowledge base."""
    verify_internal_secret(request)

    engine = get_rag_engine()
    results = await engine.search(
        teacher_id=req.teacher_id,
        query=req.query,
        mode=req.mode,
        include_public=req.include_public,
        top_k=req.top_k,
    )
    return {"results": results}


async def _do_parse(
    file_id: str,
    teacher_id: str,
    oss_url: str,
    file_name: str,
) -> None:
    """Background task: download file → RAG ingest → notify Java."""
    # 1. Notify Java: processing started
    await update_parse_status(file_id, ParseStatus.PROCESSING)

    tmp_dir = tempfile.mkdtemp(prefix="rag_parse_")
    try:
        # 2. Download file from OSS (get fresh URL in case the original expired)
        logger.info("Downloading file %s from OSS...", file_id)
        fresh_url = await get_file_download_url(file_id)
        download_url = fresh_url or oss_url
        file_path = await download_file(download_url, dest_dir=tmp_dir)

        # 3. Ingest into RAG engine
        engine = get_rag_engine()
        result = await engine.ingest_document(
            teacher_id=teacher_id,
            file_path=file_path,
            file_name=file_name,
        )

        chunk_count = result.get("chunk_count", 0)

        # 4. Notify Java: completed
        await update_parse_status(file_id, ParseStatus.COMPLETED, chunk_count=chunk_count)
        logger.info(
            "Parse completed: file_id=%s, teacher_id=%s, chunks=%d",
            file_id, teacher_id, chunk_count,
        )

    except Exception as exc:
        logger.error("Parse failed for file_id=%s: %s", file_id, exc, exc_info=True)
        await update_parse_status(
            file_id,
            ParseStatus.FAILED,
            error_message=str(exc)[:500],
        )

    finally:
        # Cleanup temp files
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
