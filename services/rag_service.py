"""RAG service for curriculum and rubric retrieval.

Phase 7 P1-1: Provides retrieval-augmented generation capabilities for:
- Official curriculum and exam guidelines
- School-specific teaching materials
- Question bank with knowledge point indexing

Note: This is a lightweight implementation. For production, consider using
chromadb or similar vector stores for better retrieval quality.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from functools import lru_cache
from typing import Any
from dataclasses import dataclass, field

from models.base import CamelModel

logger = logging.getLogger(__name__)

# Collection definitions
COLLECTIONS = {
    "official_corpus": "官方课纲、考纲、评分标准",
    "school_assets": "校本教案、题库、老师自建 rubric",
    "question_bank": "题目库（按知识点索引）",
}

DATA_DIR = Path(__file__).parent.parent / "data"


class CorpusVersion(CamelModel):
    """语料版本记录"""
    collection: str
    version: str
    created_at: str
    doc_count: int
    description: str = ""


@dataclass
class Document:
    """A document in the corpus."""
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    collection: str = "official_corpus"
    version: str = "v1"


class SimpleRAGStore:
    """Simple in-memory RAG store for development.

    In production, replace with chromadb or similar vector store.
    """

    def __init__(self):
        self._documents: dict[str, list[Document]] = {
            name: [] for name in COLLECTIONS
        }

    def add_document(
        self,
        collection: str,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        version: str = "v1",
    ) -> None:
        """Add a document to the specified collection."""
        if collection not in self._documents:
            raise ValueError(f"Unknown collection: {collection}")

        doc = Document(
            id=doc_id,
            content=content,
            metadata=metadata or {},
            collection=collection,
            version=version,
        )
        self._documents[collection].append(doc)

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query documents by simple keyword matching.

        Args:
            collection: Collection to search in.
            query_text: Search query.
            n_results: Maximum results to return.
            where: Optional metadata filters.

        Returns:
            List of matching documents with relevance scores.
        """
        if collection not in self._documents:
            raise ValueError(f"Unknown collection: {collection}")

        docs = self._documents[collection]

        # Simple keyword matching (replace with vector similarity in production)
        keywords = query_text.lower().split()
        scored_docs = []

        for doc in docs:
            # Apply metadata filters
            if where:
                skip = False
                for key, value in where.items():
                    if doc.metadata.get(key) != value:
                        skip = True
                        break
                if skip:
                    continue

            # Calculate simple relevance score
            content_lower = doc.content.lower()
            score = sum(1 for kw in keywords if kw in content_lower)

            if score > 0:
                scored_docs.append((doc, score))

        # Sort by score descending
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "id": doc.id,
                "content": doc.content,
                "metadata": doc.metadata,
                "distance": 1.0 / (score + 1),  # Convert to distance-like metric
            }
            for doc, score in scored_docs[:n_results]
        ]

    def get_collection_stats(self, collection: str) -> dict[str, Any]:
        """Get statistics for a collection."""
        if collection not in self._documents:
            raise ValueError(f"Unknown collection: {collection}")

        docs = self._documents[collection]
        return {
            "collection": collection,
            "description": COLLECTIONS[collection],
            "doc_count": len(docs),
        }


class CurriculumRAG:
    """DSE 课纲 RAG 服务

    Provides retrieval of curriculum materials, rubrics, and questions
    to support AI-generated educational content.
    """

    def __init__(self, persist_dir: str | None = None):
        """Initialize RAG service.

        Args:
            persist_dir: Optional directory for persistent storage.
                        If None, uses in-memory storage only.
        """
        self.persist_dir = Path(persist_dir) if persist_dir else None
        self._store = SimpleRAGStore()

        # Load initial data if available
        self._load_initial_data()

    def _load_initial_data(self) -> None:
        """Load initial corpus data from data/ directory."""
        # Load rubrics as official corpus
        rubrics_dir = DATA_DIR / "rubrics"
        if rubrics_dir.exists():
            for file_path in rubrics_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Convert rubric to searchable content
                    content_parts = [
                        f"Rubric: {data.get('name', '')}",
                        f"Subject: {data.get('subject', '')}",
                        f"Task Type: {data.get('taskType', '')}",
                        f"Level: {data.get('level', '')}",
                    ]

                    for criterion in data.get("criteria", []):
                        content_parts.append(f"\n{criterion['dimension'].title()} ({criterion['maxMarks']} marks):")
                        for level in criterion.get("levels", []):
                            content_parts.append(f"  Level {level['level']}: {level['descriptor']}")

                    if data.get("commonErrors"):
                        content_parts.append("\nCommon Errors:")
                        for error in data["commonErrors"]:
                            content_parts.append(f"  - {error}")

                    self._store.add_document(
                        collection="official_corpus",
                        doc_id=data["id"],
                        content="\n".join(content_parts),
                        metadata={
                            "type": "rubric",
                            "subject": data.get("subject", ""),
                            "taskType": data.get("taskType", ""),
                            "level": data.get("level", ""),
                        },
                    )
                    logger.debug("Loaded rubric: %s", data["id"])
                except Exception as e:
                    logger.warning("Failed to load rubric %s: %s", file_path, e)

        # Load knowledge points if available
        kp_dir = DATA_DIR / "knowledge_points"
        if kp_dir.exists():
            for file_path in kp_dir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    for unit in data.get("units", []):
                        for kp in unit.get("knowledgePoints", []):
                            content = f"""
Knowledge Point: {kp['name']}
ID: {kp['id']}
Description: {kp.get('description', '')}
Skills: {', '.join(kp.get('skillTags', []))}
Difficulty: {kp.get('difficulty', 'medium')}
"""
                            self._store.add_document(
                                collection="official_corpus",
                                doc_id=kp["id"],
                                content=content,
                                metadata={
                                    "type": "knowledge_point",
                                    "subject": data.get("subject", ""),
                                    "level": data.get("level", ""),
                                    "unit": unit.get("id", ""),
                                },
                            )
                    logger.debug("Loaded knowledge points from: %s", file_path)
                except Exception as e:
                    logger.warning("Failed to load knowledge points %s: %s", file_path, e)

    def add_document(
        self,
        collection: str,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        version: str = "v1",
    ) -> None:
        """Add a document to the specified collection."""
        self._store.add_document(collection, doc_id, content, metadata, version)

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query documents by relevance."""
        return self._store.query(collection, query_text, n_results, where)

    async def get_rubric_context(self, subject: str, task_type: str) -> str:
        """Get rubric context for question generation.

        Args:
            subject: Subject (e.g., "English").
            task_type: Task type (e.g., "essay").

        Returns:
            Formatted rubric content for LLM context.
        """
        query = f"{subject} {task_type} marking scheme criteria"
        results = self.query("official_corpus", query, n_results=3)

        if not results:
            return ""

        return "\n\n---\n\n".join([r["content"] for r in results])

    async def get_curriculum_context(self, subject: str, unit: str) -> str:
        """Get curriculum context for question generation.

        Args:
            subject: Subject (e.g., "English").
            unit: Unit identifier.

        Returns:
            Formatted curriculum content for LLM context.
        """
        query = f"{subject} {unit} learning objectives key concepts"
        results = self.query(
            "official_corpus",
            query,
            n_results=3,
            where={"type": "knowledge_point"},
        )

        if not results:
            return ""

        return "\n\n---\n\n".join([r["content"] for r in results])

    async def search_similar_questions(
        self,
        knowledge_point_ids: list[str],
        difficulty: str = "",
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for similar questions in the question bank.

        Args:
            knowledge_point_ids: Knowledge points to search for.
            difficulty: Optional difficulty filter.
            n_results: Maximum results.

        Returns:
            List of similar questions.
        """
        query = " ".join(knowledge_point_ids)
        if difficulty:
            query += f" {difficulty}"

        where = {"type": "question"}
        if difficulty:
            where["difficulty"] = difficulty

        return self.query("question_bank", query, n_results, where)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics for all collections."""
        return {
            name: self._store.get_collection_stats(name)
            for name in COLLECTIONS
        }


# Global singleton
_rag_service: CurriculumRAG | None = None


@lru_cache(maxsize=1)
def get_rag_service() -> CurriculumRAG:
    """Get the RAG service singleton."""
    global _rag_service
    if _rag_service is None:
        _rag_service = CurriculumRAG()
    return _rag_service
