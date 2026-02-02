"""Tests for clarify builder — option generation from route hints."""

import pytest

from models.conversation import ClarifyOptions
from services.clarify_builder import build_clarify_options


@pytest.mark.asyncio
async def test_build_class_choices():
    """needClassId → fetches teacher classes and builds choices."""
    opts = await build_clarify_options("needClassId", teacher_id="t-001")
    assert isinstance(opts, ClarifyOptions)
    assert opts.type == "single_select"
    assert len(opts.choices) == 2  # Form 1A, Form 1B from mock data
    assert opts.choices[0].value == "class-hk-f1a"
    assert opts.choices[1].value == "class-hk-f1b"
    assert opts.allow_custom_input is True


@pytest.mark.asyncio
async def test_build_class_choices_unknown_teacher():
    """needClassId with unknown teacher → empty choices."""
    opts = await build_clarify_options("needClassId", teacher_id="unknown")
    assert isinstance(opts, ClarifyOptions)
    assert len(opts.choices) == 0
    assert opts.allow_custom_input is True


@pytest.mark.asyncio
async def test_build_time_range_choices():
    """needTimeRange → preset time range options."""
    opts = await build_clarify_options("needTimeRange")
    assert isinstance(opts, ClarifyOptions)
    assert len(opts.choices) == 3
    values = [c.value for c in opts.choices]
    assert "this_week" in values
    assert "this_month" in values
    assert "this_semester" in values


@pytest.mark.asyncio
async def test_build_assignment_choices():
    """needAssignment → empty choices (no class_id available)."""
    opts = await build_clarify_options("needAssignment", teacher_id="t-001")
    assert isinstance(opts, ClarifyOptions)
    assert opts.allow_custom_input is True


@pytest.mark.asyncio
async def test_build_subject_choices():
    """needSubject → preset subject options."""
    opts = await build_clarify_options("needSubject")
    assert isinstance(opts, ClarifyOptions)
    assert len(opts.choices) == 4
    values = [c.value for c in opts.choices]
    assert "english" in values
    assert "math" in values


@pytest.mark.asyncio
async def test_unknown_route_hint():
    """Unknown route_hint → empty options with custom input."""
    opts = await build_clarify_options("unknownHint")
    assert isinstance(opts, ClarifyOptions)
    assert len(opts.choices) == 0
    assert opts.allow_custom_input is True


@pytest.mark.asyncio
async def test_none_route_hint():
    """None route_hint → empty options with custom input."""
    opts = await build_clarify_options(None)
    assert isinstance(opts, ClarifyOptions)
    assert len(opts.choices) == 0
    assert opts.allow_custom_input is True


@pytest.mark.asyncio
async def test_clarify_options_camel_case_output():
    """Verify ClarifyOptions serializes to camelCase."""
    opts = await build_clarify_options("needClassId", teacher_id="t-001")
    data = opts.model_dump(by_alias=True)
    assert "allowCustomInput" in data
    assert data["type"] == "single_select"
    if opts.choices:
        assert "label" in data["choices"][0]
        assert "value" in data["choices"][0]
