"""Blueprint API endpoints.

Handles blueprint distillation requests with concurrency control.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import Field

from models.base import CamelModel
from models.soft_blueprint import SoftBlueprint
from services.blueprint_distiller import distill_conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blueprint", tags=["Blueprint"])

# Concurrency control — max 1 concurrent distillation per teacher
_distill_semaphores: Dict[str, asyncio.Semaphore] = {}


class DistillRequest(CamelModel):
    """Request to distill a conversation into a blueprint."""

    teacher_id: str = Field(..., description="Teacher ID")
    conversation_id: str = Field(..., description="Source conversation ID")
    language: str = Field("zh", description="Language code (zh, en)")


@router.post("/distill", response_model=SoftBlueprint)
async def distill_blueprint(req: DistillRequest) -> SoftBlueprint:
    """
    Distill a conversation into a Soft Blueprint.

    Rate limit: 1 concurrent distillation per teacher.
    """
    teacher_id = req.teacher_id

    # Get or create semaphore for this teacher
    if teacher_id not in _distill_semaphores:
        _distill_semaphores[teacher_id] = asyncio.Semaphore(1)

    sem = _distill_semaphores[teacher_id]

    # Check if already running
    if sem.locked():
        logger.warning("Distillation already in progress for teacher %s", teacher_id)
        raise HTTPException(status_code=429, detail="已有蒸馏任务进行中，请稍后再试")

    async with sem:
        try:
            blueprint = await distill_conversation(
                teacher_id=teacher_id,
                conversation_id=req.conversation_id,
                language=req.language,
            )
            return blueprint
        except ValueError as e:
            logger.warning("Validation error in distillation: %s", str(e))
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            logger.error("Distillation runtime error: %s", str(e))
            raise HTTPException(status_code=500, detail=str(e))
