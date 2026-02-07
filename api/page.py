"""Page API — Blueprint execution and SSE streaming endpoint."""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from agents.executor import ExecutorAgent
from models.request import PageGenerateRequest, PagePatchRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/page", tags=["page"])

# Module-level executor instance — reused across requests.
_executor = ExecutorAgent()


def _normalize_teacher_id(raw: str | None) -> str:
    """Normalize teacher_id from request/context to avoid null-like values."""
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return ""
    if value.lower() in {"none", "null", "undefined"}:
        return ""
    return value


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
    req.teacher_id = _normalize_teacher_id(req.teacher_id)
    context_teacher_id = _normalize_teacher_id(context.get("teacherId"))
    teacher_id = req.teacher_id or context_teacher_id
    if teacher_id:
        context["teacherId"] = teacher_id

    logger.info(
        "Generating page for blueprint: %s (id=%s)",
        req.blueprint.name,
        req.blueprint.id,
    )

    return EventSourceResponse(
        _event_generator(req.blueprint, context),
        media_type="text/event-stream",
    )


async def _patch_event_generator(
    blueprint,
    page: dict,
    patch_plan,
    context: dict,
    data_context: dict | None,
    compute_results: dict | None,
) -> AsyncGenerator[str, None]:
    """Wrap ExecutorAgent patch stream into SSE-formatted JSON strings."""
    async for event in _executor.execute_patch(
        page, blueprint, patch_plan, data_context, compute_results
    ):
        yield json.dumps(event, ensure_ascii=False, default=str)


@router.post("/patch")
async def page_patch(req: PagePatchRequest):
    """Execute a PatchPlan to incrementally modify a page via SSE.

    Receives a PatchPlan (from PatchAgent) and applies it to the existing page.
    For PATCH_COMPOSE, regenerates AI content for affected blocks.
    For PATCH_LAYOUT, applies property changes directly.
    """
    context = req.context or {}
    req.teacher_id = _normalize_teacher_id(req.teacher_id)
    context_teacher_id = _normalize_teacher_id(context.get("teacherId"))
    teacher_id = req.teacher_id or context_teacher_id
    if teacher_id:
        context["teacherId"] = teacher_id

    logger.info(
        "Patching page for blueprint: %s (scope=%s)",
        req.blueprint.name,
        req.patch_plan.scope,
    )

    return EventSourceResponse(
        _patch_event_generator(
            req.blueprint,
            req.page,
            req.patch_plan,
            context,
            req.data_context,
            req.compute_results,
        ),
        media_type="text/event-stream",
    )
