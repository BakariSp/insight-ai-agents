"""Workflow API — Blueprint generation endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from agents.planner import generate_blueprint
from models.request import WorkflowGenerateRequest, WorkflowGenerateResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


@router.post("/generate", response_model=WorkflowGenerateResponse)
async def workflow_generate(req: WorkflowGenerateRequest):
    """Generate a Blueprint from a natural-language prompt.

    Calls the PlannerAgent to convert the user's request into a structured
    Blueprint with three layers: DataContract, ComputeGraph, UIComposition.
    """
    try:
        blueprint = await generate_blueprint(
            user_prompt=req.user_prompt,
            language=req.language,
        )
    except Exception as e:
        logger.exception("Blueprint generation failed")
        raise HTTPException(
            status_code=502,
            detail=f"Blueprint generation failed: {e}",
        ) from e

    return WorkflowGenerateResponse(
        blueprint=blueprint,
        model="",
    )
