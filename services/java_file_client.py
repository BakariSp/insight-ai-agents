"""Java file API client — get signed URLs for uploaded files.

Uses the general-purpose ``GET /files/{fileId}/url`` endpoint (not the
Studio-specific path) so it works for any upload purpose including
CONVERSATION_ATTACHMENT.
"""

from __future__ import annotations

import logging

from services.java_client import get_java_client

logger = logging.getLogger(__name__)


async def get_file_url(file_id: str) -> str | None:
    """Get a fresh signed OSS URL for any uploaded file.

    Args:
        file_id: The file UUID from Java's ``file_uploads`` table.

    Returns:
        A signed URL string (valid ~1 hour), or ``None`` on failure.
    """
    client = get_java_client()
    try:
        resp = await client.get(f"/files/{file_id}/url")
        data = resp.get("data") or {}
        # The endpoint returns either { url } or { downloadUrl }
        return data.get("url") or data.get("downloadUrl")
    except Exception as exc:
        logger.error("Failed to get URL for file %s: %s", file_id, exc)
        return None
