"""JWT verification: forward to Java backend + cache verified teacher_id.

User requests to AI carry the user's JWT. We verify it by calling
Java's /api/auth/me endpoint and cache the result for 5 minutes.
"""

from __future__ import annotations

import hashlib
import logging
import time

import httpx
from fastapi import HTTPException, Request

from config.settings import get_settings

logger = logging.getLogger(__name__)

# In-memory cache: sha256(token)[:16] → (teacher_id, expire_at)
_verified_cache: dict[str, tuple[str, float]] = {}

# Cache TTL in seconds
_CACHE_TTL = 300  # 5 minutes


async def get_verified_teacher_id(request: Request) -> str:
    """Extract and verify teacher_id from the user's JWT via Java backend.

    1. Read Authorization header
    2. Check local cache (5-min TTL keyed by token hash)
    3. On cache miss → call Java GET /api/auth/me
    4. Return the verified teacher_id (never trust request body)
    """
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Cache lookup
    cache_key = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = _verified_cache.get(cache_key)
    if cached is not None:
        tid, expire_at = cached
        if time.time() < expire_at:
            return tid
        # Expired — remove stale entry
        _verified_cache.pop(cache_key, None)

    # Cache miss → verify with Java
    settings = get_settings()
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(
                f"{settings.spring_boot_base_url}{settings.spring_boot_api_prefix}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.TransportError as exc:
        logger.error("Failed to verify JWT with Java backend: %s", exc)
        raise HTTPException(status_code=502, detail="Auth service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired JWT")

    # Java returns {code, data: {id, ...}, message}
    data = resp.json().get("data", {})
    teacher_id = str(data.get("id", ""))
    if not teacher_id:
        raise HTTPException(status_code=401, detail="Could not extract teacher ID from JWT")

    # Write cache
    _verified_cache[cache_key] = (teacher_id, time.time() + _CACHE_TTL)
    logger.info("Verified teacher_id=%s via Java /auth/me", teacher_id)
    return teacher_id


def verify_internal_secret(request: Request) -> None:
    """Verify X-Internal-Secret header for internal (Java → AI) calls."""
    settings = get_settings()
    if not settings.internal_api_secret:
        logger.warning("INTERNAL_API_SECRET not configured — internal endpoints unprotected")
        return

    provided = request.headers.get("X-Internal-Secret", "")
    if provided != settings.internal_api_secret:
        raise HTTPException(status_code=403, detail="Invalid internal secret")
