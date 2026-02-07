"""Multimodal helpers — build PydanticAI-compatible user prompts with images.

Converts ``Attachment`` objects from ``ConversationRequest`` into
``ImageUrl`` content parts that PydanticAI's ``Agent.run()`` understands.

When no image attachments are present, returns a plain ``str`` so the
agent call path is zero-cost compatible with the existing text-only flow.
"""

from __future__ import annotations

import logging
from typing import Sequence

from pydantic_ai.messages import ImageUrl, UserContent

from models.conversation import Attachment

logger = logging.getLogger(__name__)


def has_images(attachments: list[Attachment] | None) -> bool:
    """Check whether any attachment is an image."""
    if not attachments:
        return False
    return any(a.mime_type.startswith("image/") for a in attachments)


async def build_user_content(
    text_prompt: str,
    attachments: list[Attachment],
) -> str | Sequence[UserContent]:
    """Build a PydanticAI-compatible user prompt.

    - No image attachments → returns the original ``str`` (zero overhead).
    - With image attachments → refreshes signed URLs and returns a
      ``list[UserContent]`` containing ``ImageUrl`` + text.

    Args:
        text_prompt: The assembled text prompt (language hint + history + message).
        attachments: Attachments from the conversation request.

    Returns:
        Plain string or a sequence of ``UserContent`` items.
    """
    image_attachments = [a for a in attachments if a.mime_type.startswith("image/")]
    if not image_attachments:
        return text_prompt

    parts: list[UserContent] = []

    for att in image_attachments:
        fresh_url = await _refresh_url(att.file_id, att.url)
        parts.append(ImageUrl(url=fresh_url))
        logger.debug("Multimodal: added image %s (%s)", att.file_id, att.mime_type)

    # Text comes after images (convention for most vision models)
    parts.append(text_prompt)

    logger.info(
        "Built multimodal prompt: %d image(s) + text (%d chars)",
        len(image_attachments),
        len(text_prompt),
    )
    return parts


async def _refresh_url(file_id: str, fallback_url: str) -> str:
    """Get a fresh signed URL from Java backend, falling back to the provided URL."""
    from services.java_file_client import get_file_url

    try:
        url = await get_file_url(file_id)
        if url:
            return url
    except Exception as exc:
        logger.warning("Failed to refresh URL for %s: %s; using fallback", file_id, exc)

    return fallback_url
