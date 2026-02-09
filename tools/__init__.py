"""Tool registry — re-exports from tools.registry.

Legacy ``TOOL_REGISTRY`` dict and ``get_tool_descriptions`` are preserved
as thin wrappers for backward compatibility.  New code should import
directly from ``tools.registry``.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.registry import get_all_tools, get_tool_descriptions  # noqa: F401

# Backward-compatible TOOL_REGISTRY dict (name → callable).
# Delegates to the native registry so that tools registered via
# @register_tool are automatically visible here.
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    rt.name: rt.fn for rt in get_all_tools()
}
