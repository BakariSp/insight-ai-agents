"""Structured error codes — FP-4 freeze protocol.

Defines the canonical error codes shared across the three-party integration
(Frontend ↔ AI Agent ↔ Java Backend).

SSE stream errors follow the frozen format::

    {ERROR_CODE}: {tool_name} — {human_readable_detail}

See: docs/plans/2026-02-09-three-party-freeze-protocol.md § 5.3
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Frozen error codes per FP-4 contract (Section 5.3.1)."""

    INVALID_REQUEST = "INVALID_REQUEST"
    FORBIDDEN = "FORBIDDEN"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    SERVICE_DEGRADED = "SERVICE_DEGRADED"


def format_tool_error(tool_name: str, detail: str) -> str:
    """Format a tool execution error for SSE ``errorText``.

    Returns:
        String matching the frozen format:
        ``TOOL_EXECUTION_FAILED: {tool_name} — {detail}``
    """
    return f"{ErrorCode.TOOL_EXECUTION_FAILED}: {tool_name} \u2014 {detail}"


def format_llm_error(detail: str) -> str:
    """Format an LLM provider error for SSE ``errorText``.

    Returns:
        String matching the frozen format:
        ``LLM_PROVIDER_ERROR: {detail}``
    """
    return f"{ErrorCode.LLM_PROVIDER_ERROR}: {detail}"


def format_error(code: ErrorCode, detail: str) -> str:
    """Format a generic error for SSE ``errorText``.

    Returns:
        ``{ERROR_CODE}: {detail}``
    """
    return f"{code}: {detail}"
