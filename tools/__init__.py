"""Tool registry — re-exports from tools.registry.

Legacy ``TOOL_REGISTRY`` dict and ``get_tool_descriptions`` are preserved
as thin wrappers for backward compatibility.  New code should import
directly from ``tools.registry``.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.registry import (  # noqa: F401
    _registry as _native_registry,
    get_tool_descriptions,
)


class _ToolRegistryProxy(dict):
    """Live-view dict that delegates to the native registry.

    Avoids the stale-snapshot problem: ``tools/__init__.py`` is imported
    before ``tools.native_tools`` registers tools, so an eagerly-built
    dict would always be empty.  This proxy reads the authoritative
    ``_native_registry`` on every access.
    """

    def _snapshot(self) -> dict[str, Callable[..., Any]]:
        return {rt.name: rt.func for rt in _native_registry.values()}

    def __getitem__(self, key: str) -> Callable[..., Any]:
        return self._snapshot()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._snapshot().get(key, default)

    def keys(self):  # type: ignore[override]
        return self._snapshot().keys()

    def values(self):  # type: ignore[override]
        return self._snapshot().values()

    def items(self):  # type: ignore[override]
        return self._snapshot().items()

    def __contains__(self, key: object) -> bool:
        return key in self._snapshot()

    def __len__(self) -> int:
        return len(_native_registry)

    def __iter__(self):
        return iter(self._snapshot())

    def __repr__(self) -> str:
        return f"_ToolRegistryProxy({self._snapshot()!r})"


# Backward-compatible TOOL_REGISTRY — live view into the native registry.
TOOL_REGISTRY: dict[str, Callable[..., Any]] = _ToolRegistryProxy()
