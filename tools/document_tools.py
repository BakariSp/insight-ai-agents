"""Document search tools — search teacher knowledge base via RAG.

Provides a tool for PlannerAgent/ExecutorAgent to search the teacher's
uploaded documents (lesson plans, worksheets, etc.) via LightRAG.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def search_teacher_documents(
    teacher_id: str,
    query: str,
    n_results: int = 5,
    include_public: bool = False,
) -> dict[str, Any]:
    """Search the teacher's knowledge base for relevant document chunks.

    Uses LightRAG hybrid search (vector similarity + knowledge graph traversal)
    to find document fragments relevant to the query. Searches both the teacher's
    private workspace and the public knowledge base.

    Args:
        teacher_id: The teacher whose documents to search.
        query: Natural-language search query (e.g. "教案出题", "期末复习").
        n_results: Maximum number of results to return.
        include_public: Also search the public (system) knowledge base.

    Returns:
        {"status": "ok"|"no_result"|"error"|"degraded", "query": str, "results": list[dict], "total": int}
        Each result has: content, source, score.
    """
    from insight_backend.rag_engine import get_rag_engine

    try:
        engine = get_rag_engine()
    except RuntimeError:
        logger.warning("RAG engine not initialized")
        return {
            "status": "error",
            "reason": "RAG engine not initialized",
            "query": query,
            "results": [],
            "total": 0,
        }

    try:
        results = await engine.search(
            teacher_id=teacher_id,
            query=query,
            mode="hybrid",
            include_public=include_public,
            top_k=n_results,
        )
        normalized_results = []
        for item in results:
            if not isinstance(item, dict):
                normalized_results.append(item)
                continue
            normalized_results.append({
                **item,
                "source": item.get("source", "public" if include_public else "private"),
            })

        # Attach source file list for citation transparency
        sources = [
            {"fileId": f["file_id"], "fileName": f["file_name"]}
            for f in engine.get_workspace_files(teacher_id)
        ]

        if not normalized_results:
            return {
                "status": "no_result",
                "query": query,
                "results": [],
                "total": 0,
                "sources": sources,
            }

        return {
            "status": "ok",
            "query": query,
            "results": normalized_results,
            "total": len(normalized_results),
            "sources": sources,
        }
    except Exception as exc:
        logger.error("Document search failed for teacher %s: %s", teacher_id, exc)
        return {
            "status": "error",
            "reason": str(exc),
            "query": query,
            "results": [],
            "total": 0,
        }
