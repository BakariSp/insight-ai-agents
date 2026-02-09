"""Structured error codes — FP-4 freeze protocol.

Defines the canonical error codes shared across the three-party integration
(Frontend ↔ AI Agent ↔ Java Backend).

SSE stream errors follow the frozen format::

    {ERROR_CODE}: {tool_name} — {human_readable_detail}

See: docs/plans/2026-02-09-three-party-freeze-protocol.md § 5.3
"""

from __future__ import annotations

import re
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


# ── Tool name extraction pattern ────────────────────────────────────
# Matches known tool-function prefixes found in the tools/ registry.
_TOOL_NAME_RE = re.compile(
    r"\b("
    r"get_\w+"
    r"|generate_\w+"
    r"|calculate_\w+"
    r"|save_as_\w+"
    r"|create_share_\w+"
    r"|search_teacher_\w+"
    r"|resolve_entity"
    r"|patch_artifact"
    r"|propose_pptx_outline"
    r"|render_pdf"
    r"|request_interactive_content"
    r"|build_report_page"
    r"|ask_clarification"
    r"|compare_performance"
    r"|analyze_student_weakness"
    r"|get_student_error_patterns"
    r"|calculate_class_mastery"
    r")\b"
)

# Broad patterns that indicate a tool-related failure even when the
# exact tool name cannot be extracted from the error message.
_TOOL_HINT_RE = re.compile(
    r"\btool\b|java api",
    re.IGNORECASE,
)

# LLM-provider patterns (timeout, connection, context-length, token limits,
# content-safety filters).
_LLM_PROVIDER_RE = re.compile(
    r"timeout|connection|context length|token|content filter|safety",
    re.IGNORECASE,
)


def classify_stream_error(error_text: str) -> str:
    """Classify a raw exception string into a frozen SSE ``errorText``.

    Classification order (first match wins):
        1. Tool execution failure — matched by known tool-name prefix or
           generic tool-hint keywords.
        2. LLM provider error — timeout / connection / context-length / token /
           content-filter / safety.
        3. Fallback — ``INTERNAL_ERROR``.

    Returns:
        A formatted string conforming to FP-4 § 5.3.2.
    """
    # 1. Tool execution failure
    tool_match = _TOOL_NAME_RE.search(error_text)
    if tool_match:
        return format_tool_error(tool_match.group(1), error_text)
    if _TOOL_HINT_RE.search(error_text):
        return format_tool_error("unknown_tool", error_text)

    # 2. LLM provider error (sub-classify for richer detail)
    err_lower = error_text.lower()
    if "content filter" in err_lower or "safety" in err_lower:
        return format_llm_error("Content filtered by safety policy")
    if "context length" in err_lower or "token" in err_lower:
        return format_llm_error(f"Context length exceeded — {error_text}")
    if "timeout" in err_lower or "connection" in err_lower:
        return format_llm_error(error_text)

    # 3. Fallback
    return f"{ErrorCode.INTERNAL_ERROR}: {error_text}"
