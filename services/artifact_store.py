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

