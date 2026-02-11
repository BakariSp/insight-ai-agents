"""Media generation endpoints — direct image/video generation without LLM loop.

Called by Next.js API routes (e.g. /api/ai/iframe-image) to provide
iframe-embedded interactive HTML with on-demand media generation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    size: str = Field(default="1024x1024")
    seed: int = Field(default=-1)


class ImageGenerateResponse(BaseModel):
    image_url: str
    prompt: str
    size: str


@router.post("/generate-image", response_model=ImageGenerateResponse)
async def generate_image_endpoint(req: ImageGenerateRequest):
    """Generate an image from a text prompt using Seedream (Volcengine).

    Lightweight endpoint for iframe bridge — bypasses the LLM tool loop.
    """
    from tools.volcengine_media import generate_image

    result = await generate_image(
        prompt=req.prompt,
        size=req.size,
        seed=req.seed,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("reason", "Image generation failed"))

    return ImageGenerateResponse(
        image_url=result["image_url"],
        prompt=result["prompt"],
        size=result["size"],
    )
