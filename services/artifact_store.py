"""In-memory artifact store for native artifact tools."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from models.tool_contracts import Artifact, ContentFormat


@dataclass
class ArtifactVersion:
    artifact: Artifact


class InMemoryArtifactStore:
    """In-memory artifact store with capacity limits.

    ``MAX_ARTIFACTS`` caps the total number of artifact versions stored.
    When the cap is reached, the oldest entry (by insertion order) is evicted.
    ``MAX_CONVERSATIONS`` caps the conversation→latest-artifact mapping.
    """

    MAX_ARTIFACTS = 2000
    MAX_CONVERSATIONS = 1000

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, ArtifactVersion] = {}
        self._latest_by_conversation: dict[str, str] = {}

    def save_artifact(
        self,
        *,
        conversation_id: str,
        artifact_type: str,
        content_format: str,
        content: Any,
        artifact_id: str | None = None,
    ) -> Artifact:
        with self._lock:
            if artifact_id and artifact_id in self._by_id:
                prev = self._by_id[artifact_id].artifact
                version = prev.version + 1
                aid = artifact_id
            else:
                version = 1
                aid = artifact_id or f"art-{uuid.uuid4().hex[:10]}"

            artifact = Artifact(
                artifact_id=aid,
                artifact_type=artifact_type,
                content_format=ContentFormat(content_format),
                content=content,
                version=version,
            )
            self._by_id[aid] = ArtifactVersion(artifact=artifact)
            if conversation_id:
                self._latest_by_conversation[conversation_id] = aid

            # Evict oldest entries when capacity is exceeded.
            if len(self._by_id) > self.MAX_ARTIFACTS:
                oldest_key = next(iter(self._by_id))
                del self._by_id[oldest_key]
            if len(self._latest_by_conversation) > self.MAX_CONVERSATIONS:
                oldest_conv = next(iter(self._latest_by_conversation))
                del self._latest_by_conversation[oldest_conv]

            return artifact

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._lock:
            item = self._by_id.get(artifact_id)
            return item.artifact if item else None

    def get_latest_for_conversation(self, conversation_id: str) -> Artifact | None:
        with self._lock:
            aid = self._latest_by_conversation.get(conversation_id, "")
            if not aid:
                return None
            item = self._by_id.get(aid)
            return item.artifact if item else None


_artifact_store = InMemoryArtifactStore()


def get_artifact_store() -> InMemoryArtifactStore:
    return _artifact_store

