"""Teacher Knowledge Base — RAG document storage & retrieval.

This module handles ONLY resource library files (purpose="rag_material").
Studio files (analysis, lesson_material, general) are NOT RAG-indexed.

Provides:
- JWT verification via Java backend (auth.py)
- RAG engine with per-teacher workspace isolation (rag_engine.py)
- Java file API adapter for download URLs & parse status (document_adapter.py)
- Pydantic models for parse requests/results (models.py)

Data separation:
- Resource Library → RAG-indexed (PostgreSQL + pgvector, managed by LightRAG)
- Studio Files → NOT RAG-indexed (OSS only, one-time analysis or direct display)
"""
