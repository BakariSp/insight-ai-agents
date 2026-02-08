"""Serve locally-generated files (development / fallback).

When the Java backend upload fails, render tools save files to the system
temp directory and return ``/api/files/generated/<filename>``.  This router
serves those temp files so the browser can download them.

In production the primary path uploads to OSS via the Java backend —
this endpoint is only a safety net.
"""

from __future__ import annotations

import logging
import mimetypes
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# Only serve files from the system temp directory (security boundary)
_TEMP_DIR = Path(tempfile.gettempdir())


@router.get("/generated/{filename:path}")
async def serve_generated_file(filename: str):
    """Serve a generated file from the temp directory.

    Security: only files directly inside the system temp dir are served.
    Path traversal (../) is rejected.
    """
    # Reject path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = _TEMP_DIR / filename
    if not filepath.is_file():
        logger.warning("Generated file not found: %s", filepath)
        raise HTTPException(status_code=404, detail="File not found")

    # Verify the resolved path is still inside temp dir
    try:
        filepath.resolve().relative_to(_TEMP_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Determine content type
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        content_type = "application/octet-stream"

    # Extract the user-friendly filename (strip UUID prefix)
    # Files are named: {uuid}_{original_filename}
    parts = filename.split("_", 1)
    display_name = parts[1] if len(parts) > 1 else filename

    return FileResponse(
        path=str(filepath),
        media_type=content_type,
        filename=display_name,
    )
