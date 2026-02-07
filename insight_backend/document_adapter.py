"""Java file API adapter — get download URLs, update parse status.

Reuses the existing JavaClient singleton for all requests to the Java backend.
Only handles resource library files (purpose="rag_material").

API paths follow the studio convention:
  GET  /studio/teacher/me/files/{fileId}/download
  PUT  /studio/teacher/me/files/{fileId}/parse-status
"""

from __future__ import annotations

import logging
from typing import Any

from services.java_client import get_java_client, JavaClientError
from insight_backend.models import ParseStatus

logger = logging.getLogger(__name__)


async def get_file_download_url(file_id: str) -> str | None:
    """Get the OSS download URL for a file from Java backend.

    Args:
        file_id: The file ID in Java's database.

    Returns:
        The download URL string, or None if not found.
    """
    client = get_java_client()
    try:
        resp = await client.get(f"/studio/teacher/me/files/{file_id}/download")
        data = resp.get("data") or {}
        return data.get("url") or data.get("downloadUrl")
    except Exception as exc:
        logger.error("Failed to get download URL for file %s: %s", file_id, exc)
        return None


async def update_parse_status(
    file_id: str,
    status: ParseStatus,
    chunk_count: int = 0,
    error_message: str = "",
) -> bool:
    """Notify Java backend of document parse status.

    Calls: PUT /api/studio/teacher/me/files/{fileId}/parse-status

    Args:
        file_id: The file ID.
        status: New parse status.
        chunk_count: Number of chunks extracted (on success).
        error_message: Error details (on failure).

    Returns:
        True if update was successful.
    """
    client = get_java_client()
    body: dict[str, Any] = {
        "parseStatus": status.value,
        "chunkCount": chunk_count,
    }
    if error_message:
        body["errorMessage"] = error_message

    try:
        await client.post(f"/studio/teacher/me/files/{file_id}/parse-status", json_body=body)
        logger.info(
            "Updated parse status for file %s → %s (chunks=%d)",
            file_id, status.value, chunk_count,
        )
        return True
    except JavaClientError as exc:
        logger.error("Failed to update parse status for file %s: %s", file_id, exc)
        return False
