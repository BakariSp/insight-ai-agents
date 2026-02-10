"""Knowledge graph query API — exposes LightRAG graph data for visualization.

Called by Next.js API Routes (not by end users directly).
Teacher ID is trusted from the upstream proxy layer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from insight_backend.rag_engine import get_rag_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _normalize_teacher_id(raw: str | None) -> str:
    if raw is None:
        return ""
    value = str(raw).strip()
    if value.lower() in ("", "null", "undefined", "none"):
        return ""
    return value


class GraphRequest(BaseModel):
    teacher_id: str
    node_label: str = "*"
    max_depth: int = 2
    max_nodes: int = 200


@router.post("/graph")
async def get_knowledge_graph(req: GraphRequest):
    """Return the knowledge graph (nodes + edges) for a teacher's workspace."""
    teacher_id = _normalize_teacher_id(req.teacher_id)
    if not teacher_id:
        raise HTTPException(status_code=400, detail="teacher_id is required")

    workspace_id = f"teacher-{teacher_id}"
    engine = get_rag_engine()

    try:
        rag = await engine.get_instance(workspace_id)
    except Exception as exc:
        logger.warning("Failed to get RAG instance for %s: %s", workspace_id, exc)
        return {"nodes": [], "edges": [], "is_truncated": False}

    graph_storage = rag.lightrag.chunk_entity_relation_graph

    try:
        kg = await graph_storage.get_knowledge_graph(
            node_label=req.node_label,
            max_depth=req.max_depth,
            max_nodes=req.max_nodes,
        )
    except Exception as exc:
        logger.warning("Knowledge graph query failed for %s: %s", workspace_id, exc)
        return {"nodes": [], "edges": [], "is_truncated": False}

    return {
        "nodes": [n.model_dump() for n in kg.nodes],
        "edges": [e.model_dump() for e in kg.edges],
        "is_truncated": kg.is_truncated,
    }


@router.get("/health")
async def knowledge_health(teacher_id: str = Query(...)):
    """Diagnose RAG workspace health — check KG vs vector store counts.

    Use this to debug why searches return [no-context] when the KG has data.
    """
    tid = _normalize_teacher_id(teacher_id)
    if not tid:
        raise HTTPException(status_code=400, detail="teacher_id is required")

    engine = get_rag_engine()
    return await engine.diagnose_workspace(tid)
