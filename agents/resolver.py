"""Path reference resolver for Blueprint execution.

Resolves ``$context.``, ``$input.``, ``$data.``, and ``$compute.`` references
used in Blueprint DataBinding param_mapping and ComputeNode tool_args.

Examples::

    resolve_ref("$context.teacherId", contexts)  # → "t-001"
    resolve_ref("$data.submissions.scores", contexts)  # → [58, 85, 72, ...]
    resolve_refs({"data": "$data.submissions.scores"}, contexts)  # → {"data": [...]}
"""

from __future__ import annotations

from typing import Any


# Recognized reference prefixes and their context keys.
_PREFIX_MAP: dict[str, str] = {
    "$context.": "context",
    "$input.": "input",
    "$data.": "data",
    "$compute.": "compute",
}


def resolve_ref(ref_string: str, contexts: dict[str, Any]) -> Any:
    """Resolve a single ``$prefix.path.to.value`` reference.

    Args:
        ref_string: A reference string like ``"$data.submissions.scores"``.
        contexts: A dict with keys ``"context"``, ``"input"``, ``"data"``,
                  ``"compute"`` mapping to their respective data dicts.

    Returns:
        The resolved value, or ``None`` if the path does not exist.
    """
    if not isinstance(ref_string, str) or not ref_string.startswith("$"):
        return ref_string

    for prefix, ctx_key in _PREFIX_MAP.items():
        if ref_string.startswith(prefix):
            path = ref_string[len(prefix):]
            root = contexts.get(ctx_key)
            return _walk_path(root, path)

    # Unknown prefix — return as-is
    return ref_string


def resolve_refs(
    args_dict: dict[str, Any],
    *context_dicts: dict[str, Any],
) -> dict[str, Any]:
    """Recursively resolve all ``$`` references in a dict.

    Accepts either a single merged contexts dict or multiple positional
    context dicts that will be merged (later dicts override earlier ones).

    Args:
        args_dict: The dict whose values may contain ``$`` references.
        *context_dicts: One or more context dicts to merge. Typical usage::

            resolve_refs(tool_args, context, input_ctx, data_ctx, compute_ctx)

    Returns:
        A new dict with all references resolved.
    """
    merged: dict[str, Any] = {}
    for ctx in context_dicts:
        merged.update(ctx)
    return _resolve_value(args_dict, merged)


def _walk_path(obj: Any, path: str) -> Any:
    """Walk a dot-separated path into a nested dict/object.

    Returns ``None`` if any segment along the path is missing.
    """
    if obj is None:
        return None

    segments = path.split(".")
    current = obj
    for seg in segments:
        if isinstance(current, dict):
            current = current.get(seg)
        elif hasattr(current, seg):
            current = getattr(current, seg)
        else:
            return None
        if current is None:
            return None
    return current


def _resolve_value(value: Any, contexts: dict[str, Any]) -> Any:
    """Recursively resolve references in any value type."""
    if isinstance(value, str) and value.startswith("$"):
        return resolve_ref(value, contexts)
    if isinstance(value, dict):
        return {k: _resolve_value(v, contexts) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, contexts) for item in value]
    return value
