"""Volcengine media generation — Seedream (image) + Seedance (video).

Uses ``volcenginesdkarkruntime.AsyncArk`` with ARK_API_KEY authentication.
Base URL: https://ark.cn-beijing.volces.com/api/v3

Image generation (Seedream):
  ``client.images.generate(model, prompt, size, seed)`` → immediate result.

Video generation (Seedance):
  ``client.content_generation.tasks.create(model, content, duration, ratio)``
  → async task → poll ``tasks.get(task_id)`` until succeeded/failed.

Response type reference (from SDK):
  ContentGenerationTask.content.video_url  — generated video URL
  ContentGenerationTask.error.message      — error description
  ContentGenerationTask.status             — "succeeded" | "failed" | "running" | ...
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


# ── Singleton AsyncArk client ─────────────────────────────


@lru_cache
def _get_ark_client():
    """Lazy-init singleton AsyncArk client.  Raises RuntimeError if ARK_API_KEY unset."""
    from volcenginesdkarkruntime import AsyncArk
    from config.settings import get_settings

    s = get_settings()
    if not s.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured — set it in .env")
    return AsyncArk(base_url=s.ark_base_url, api_key=s.ark_api_key)


# ── Image generation (Seedream) ───────────────────────────


async def generate_image(
    *,
    prompt: str,
    size: str = "1024x1024",
    model: str = "",
    seed: int = -1,
) -> dict[str, Any]:
    """Generate an image from a text prompt using Seedream.

    Returns:
        {"status": "ok", "image_url": str, "model": str, "prompt": str, "size": str}
        or {"status": "error", "reason": str}
    """
    if not prompt or not prompt.strip():
        return {"status": "error", "reason": "prompt is required"}

    from config.settings import get_settings
    settings = get_settings()
    model = model or settings.ark_image_model

    try:
        client = _get_ark_client()

        # AsyncArk.images.generate is awaitable
        kwargs: dict[str, Any] = {
            "model": model,
            "prompt": prompt.strip(),
        }
        if size:
            kwargs["size"] = size
        if seed and seed >= 0:
            kwargs["seed"] = seed

        response = await client.images.generate(**kwargs)
        image_url = response.data[0].url

        return {
            "status": "ok",
            "image_url": image_url,
            "model": model,
            "prompt": prompt.strip(),
            "size": size,
        }
    except RuntimeError as exc:
        # ARK_API_KEY not configured
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        logger.exception("Seedream image generation failed: %s", exc)
        return {"status": "error", "reason": f"Image generation failed: {exc}"}


# ── Video generation (Seedance) ───────────────────────────


def _build_video_content(
    prompt: str,
    image_url: str = "",
) -> list[dict[str, Any]]:
    """Build the ``content`` array for Seedance task creation.

    Duration and ratio are now first-class SDK parameters (not in-prompt).
    """
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt.strip()},
    ]

    # Image-to-video: add reference image
    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })

    return content


async def generate_video(
    *,
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "16:9",
    model: str = "",
    image_url: str = "",
) -> dict[str, Any]:
    """Generate a video from text (+ optional image) using Seedance.

    This is an async task:
      1. Create task via ``content_generation.tasks.create()``
      2. Poll ``content_generation.tasks.get(task_id)`` until done

    Returns:
        {"status": "ok", "video_url": str, "task_id": str, ...}
        or {"status": "error", "reason": str, ...}
    """
    if not prompt or not prompt.strip():
        return {"status": "error", "reason": "prompt is required"}

    from config.settings import get_settings
    settings = get_settings()
    model = model or settings.ark_video_model

    try:
        client = _get_ark_client()
        content = _build_video_content(prompt=prompt, image_url=image_url)

        # Step 1: Create the video generation task
        # SDK supports duration, ratio as first-class params
        create_result = await client.content_generation.tasks.create(
            model=model,
            content=content,
            duration=duration,
            ratio=aspect_ratio,
        )
        task_id = create_result.id
        logger.info("Video generation task created: %s (model=%s)", task_id, model)

        # Step 2: Poll for completion
        elapsed = 0
        poll_interval = settings.ark_video_poll_interval
        max_wait = settings.ark_video_max_wait

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            result = await client.content_generation.tasks.get(task_id=task_id)
            status = result.status

            if status == "succeeded":
                video_url = ""
                if result.content:
                    video_url = result.content.video_url or ""
                logger.info("Video generation succeeded: %s → %s", task_id, video_url)
                return {
                    "status": "ok",
                    "video_url": video_url,
                    "task_id": task_id,
                    "model": model,
                    "prompt": prompt.strip(),
                    "duration": duration,
                    "aspect_ratio": aspect_ratio,
                }

            if status == "failed":
                error_msg = "unknown error"
                if result.error:
                    error_msg = result.error.message or result.error.code or error_msg
                logger.error("Video generation failed: %s — %s", task_id, error_msg)
                return {
                    "status": "error",
                    "reason": f"Video generation failed: {error_msg}",
                    "task_id": task_id,
                }

            # Still running — continue polling
            logger.debug("Video task %s status: %s (%ds elapsed)", task_id, status, elapsed)

        # Timed out
        return {
            "status": "error",
            "reason": f"Video generation timed out after {max_wait}s",
            "task_id": task_id,
        }

    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        logger.exception("Seedance video generation failed: %s", exc)
        return {"status": "error", "reason": f"Video generation failed: {exc}"}
