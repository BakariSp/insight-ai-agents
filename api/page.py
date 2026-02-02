"""Page API — Blueprint execution and SSE streaming endpoint."""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from agents.executor import ExecutorAgent
from models.request import PageGenerateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/page", tags=["page"])

# Module-level executor instance — reused across requests.
_executor = ExecutorAgent()


async def _event_generator(
    blueprint,
    context: dict,
) -> AsyncGenerator[str, None]:
    """Wrap ExecutorAgent stream into SSE-formatted JSON strings."""
    async for event in _executor.execute_blueprint_stream(blueprint, context):
        yield json.dumps(event, ensure_ascii=False, default=str)


@router.post("/generate")
async def page_generate(req: PageGenerateRequest):
    """Execute a Blueprint and stream the page via SSE.

    Receives a Blueprint (from PlannerAgent) and executes it through three
    phases: Data → Compute → Compose. Events are streamed as SSE to the
    client, ending with a COMPLETE event containing the full page JSON.
    """
    context = req.context or {}
    if req.teacher_id:
        context.setdefault("teacherId", req.teacher_id)

    logger.info(
        "Generating page for blueprint: %s (id=%s)",
        req.blueprint.name,
        req.blueprint.id,
    )

    return EventSourceResponse(
        _event_generator(req.blueprint, context),
        media_type="text/event-stream",
    )
