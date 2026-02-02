"""Tests for path reference resolver."""

import pytest

from agents.resolver import resolve_ref, resolve_refs


# ── Sample contexts ──────────────────────────────────────────

CONTEXTS = {
    "context": {
        "teacherId": "t-001",
        "language": "en",
    },
    "input": {
        "class": "class-hk-f1a",
        "assignment": "a-001",
    },
    "data": {
        "submissions": {
            "assignment_id": "a-001",
            "scores": [58, 85, 72, 91, 65],
            "submissions": [
                {"student_id": "s-001", "score": 58},
                {"student_id": "s-002", "score": 85},
            ],
        },
        "classDetail": {
            "name": "Form 1A",
            "student_count": 5,
        },
    },
    "compute": {
        "scoreStats": {
            "mean": 74.2,
            "median": 72,
            "count": 5,
        },
    },
}


# ── resolve_ref tests ────────────────────────────────────────


def test_resolve_context_ref():
    result = resolve_ref("$context.teacherId", CONTEXTS)
    assert result == "t-001"


def test_resolve_input_ref():
    result = resolve_ref("$input.class", CONTEXTS)
    assert result == "class-hk-f1a"


def test_resolve_data_ref_simple():
    result = resolve_ref("$data.classDetail.name", CONTEXTS)
    assert result == "Form 1A"


def test_resolve_data_ref_nested():
    """Resolve a deeply nested path like $data.submissions.scores."""
    result = resolve_ref("$data.submissions.scores", CONTEXTS)
    assert result == [58, 85, 72, 91, 65]


def test_resolve_compute_ref():
    result = resolve_ref("$compute.scoreStats.mean", CONTEXTS)
    assert result == 74.2


def test_resolve_missing_path_returns_none():
    result = resolve_ref("$data.nonexistent.field", CONTEXTS)
    assert result is None


def test_resolve_missing_context_returns_none():
    result = resolve_ref("$data.submissions.scores", {"context": {}})
    assert result is None


def test_resolve_non_ref_string_passthrough():
    """Non-reference strings are returned as-is."""
    result = resolve_ref("plain text", CONTEXTS)
    assert result == "plain text"


def test_resolve_unknown_prefix_passthrough():
    result = resolve_ref("$unknown.foo", CONTEXTS)
    assert result == "$unknown.foo"


def test_resolve_non_string_passthrough():
    result = resolve_ref(42, CONTEXTS)
    assert result == 42


# ── resolve_refs tests ───────────────────────────────────────


def test_resolve_refs_flat_dict():
    args = {
        "teacher_id": "$context.teacherId",
        "assignment_id": "$input.assignment",
    }
    result = resolve_refs(args, CONTEXTS)
    assert result == {
        "teacher_id": "t-001",
        "assignment_id": "a-001",
    }


def test_resolve_refs_nested_dict():
    args = {
        "data": "$data.submissions.scores",
        "config": {
            "label": "$data.classDetail.name",
            "threshold": 60,
        },
    }
    result = resolve_refs(args, CONTEXTS)
    assert result["data"] == [58, 85, 72, 91, 65]
    assert result["config"]["label"] == "Form 1A"
    assert result["config"]["threshold"] == 60


def test_resolve_refs_list_values():
    args = {
        "items": ["$context.teacherId", "$input.class", "literal"],
    }
    result = resolve_refs(args, CONTEXTS)
    assert result["items"] == ["t-001", "class-hk-f1a", "literal"]


def test_resolve_refs_no_refs():
    """Dict without any $ references is returned unchanged."""
    args = {"key": "value", "count": 5}
    result = resolve_refs(args, CONTEXTS)
    assert result == {"key": "value", "count": 5}


def test_resolve_refs_multiple_context_dicts():
    """Multiple context dicts are merged (later overrides earlier)."""
    ctx_a = {"context": {"teacherId": "t-001"}}
    ctx_b = {"data": {"scores": [1, 2, 3]}}
    args = {
        "teacher": "$context.teacherId",
        "data": "$data.scores",
    }
    result = resolve_refs(args, ctx_a, ctx_b)
    assert result["teacher"] == "t-001"
    assert result["data"] == [1, 2, 3]


def test_resolve_refs_empty_dict():
    result = resolve_refs({}, CONTEXTS)
    assert result == {}
