"""TTS generation tools — synthesize audio via Java backend (DashScope CosyVoice).

The Java backend handles: DashScope API call → file storage → database record.
AI Agent passes raw CosyVoice voice IDs — no mapping needed.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_client():
    from services.java_client import get_java_client
    return get_java_client()


async def synthesize_speech(
    *,
    text: str,
    voice: str = "longxiaochun",
    language: str = "zh-CN",
    speed: float = 1.0,
    title: str = "",
) -> dict[str, Any]:
    """Call Java backend TTS endpoint to synthesize audio.

    Returns:
        {"status": "ok", "task_id": str, "audio_url": str, "duration": int, ...}
        or {"status": "error", "reason": str}
    """
    if not text or not text.strip():
        return {"status": "error", "reason": "text is required"}
    if len(text) > 3000:
        return {"status": "error", "reason": "text exceeds 3000 characters"}

    try:
        client = _get_client()
        response = await client.post("/text-to-speech", json_body={
            "text": text.strip(),
            "voiceType": voice,
            "language": language,
            "voiceSpeed": speed,
            "title": title or text[:50],
        })

        data = response.get("data", {}) if isinstance(response, dict) else {}
        task_id = data.get("taskId", "")

        return {
            "status": "ok",
            "task_id": task_id,
            "audio_url": data.get("audioUrl", ""),
            "duration": data.get("duration", 0),
            "voice_type": data.get("voiceType", voice),
            "language": data.get("language", language),
            "title": data.get("title", title),
            "message": f"Audio generated successfully (taskId={task_id})",
        }

    except Exception as exc:
        logger.exception("TTS synthesis failed: %s", exc)
        return {"status": "error", "reason": str(exc)}
