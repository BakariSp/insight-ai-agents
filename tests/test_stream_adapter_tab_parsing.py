"""Tests for stream adapter tab parsing functionality."""

import pytest

from services.stream_adapter import _parse_tabs_from_markdown


def test_parse_tabs_simple():
    """Test parsing simple tab structure."""
    markdown = """
## [TAB:overview] 整体概览

KPI: 平均分 85

学生总数: 30

## [TAB:details] 详细分析

具体数据...
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert result["layout"] == "tabs"
    assert len(result["tabs"]) == 2

    # Check first tab
    assert result["tabs"][0]["key"] == "overview"
    assert result["tabs"][0]["label"] == "整体概览"
    assert "KPI" in result["tabs"][0]["blocks"][0]["content"]
    assert "平均分 85" in result["tabs"][0]["blocks"][0]["content"]

    # Check second tab
    assert result["tabs"][1]["key"] == "details"
    assert result["tabs"][1]["label"] == "详细分析"
    assert "具体数据" in result["tabs"][1]["blocks"][0]["content"]


def test_parse_tabs_multiple():
    """Test parsing multiple tabs."""
    markdown = """
## [TAB:overview] Overview

Summary content here

## [TAB:analysis] Analysis

Analysis content here

## [TAB:recommendations] Recommendations

Recommendations content here
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert len(result["tabs"]) == 3
    assert result["tabs"][0]["key"] == "overview"
    assert result["tabs"][1]["key"] == "analysis"
    assert result["tabs"][2]["key"] == "recommendations"


def test_parse_no_tabs():
    """Test parsing markdown without tabs."""
    markdown = "Just plain content without tabs"

    result = _parse_tabs_from_markdown(markdown)

    assert result is None  # Should return None for graceful degradation


def test_parse_tabs_with_special_characters():
    """Test parsing tabs with special characters in label."""
    markdown = """
## [TAB:stats] 统计数据 & 分析

Content with special chars: 测试、分析、总结

## [TAB:chart] 图表 (Chart)

Chart content
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert len(result["tabs"]) == 2
    assert result["tabs"][0]["label"] == "统计数据 & 分析"
    assert result["tabs"][1]["label"] == "图表 (Chart)"


def test_parse_tabs_empty_content():
    """Test parsing tabs with minimal content."""
    markdown = """
## [TAB:empty1] Empty Tab 1

## [TAB:empty2] Empty Tab 2

"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert len(result["tabs"]) == 2
    # Content should be empty strings after stripping
    assert result["tabs"][0]["blocks"][0]["content"] == ""
    assert result["tabs"][1]["blocks"][0]["content"] == ""


def test_parse_tabs_single_tab():
    """Test parsing markdown with only one tab."""
    markdown = """
## [TAB:only] Only Tab

This is the only tab content
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert len(result["tabs"]) == 1
    assert result["tabs"][0]["key"] == "only"
    assert "only tab content" in result["tabs"][0]["blocks"][0]["content"]


def test_parse_tabs_with_markdown_content():
    """Test parsing tabs with rich markdown content."""
    markdown = """
## [TAB:intro] Introduction

### Subsection

- Item 1
- Item 2

**Bold text** and *italic text*

## [TAB:data] Data

| Column 1 | Column 2 |
|----------|----------|
| A        | B        |

```python
print("code block")
```
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    assert len(result["tabs"]) == 2

    # First tab should preserve markdown formatting
    intro_content = result["tabs"][0]["blocks"][0]["content"]
    assert "### Subsection" in intro_content
    assert "**Bold text**" in intro_content

    # Second tab should preserve table and code block
    data_content = result["tabs"][1]["blocks"][0]["content"]
    assert "| Column 1 |" in data_content
    assert "```python" in data_content


def test_parse_tabs_mixed_content():
    """Test parsing tabs mixed with non-tab content."""
    markdown = """
Some preamble text before tabs

## [TAB:first] First Tab

First tab content

## [TAB:second] Second Tab

Second tab content
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    # Preamble is ignored, only tabs are extracted
    assert len(result["tabs"]) == 2


def test_parse_tabs_case_sensitivity():
    """Test that tab marker is case-sensitive."""
    markdown = """
## [tab:lowercase] Lowercase

This should NOT be detected

## [TAB:uppercase] Uppercase

This should be detected
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    # Only uppercase TAB should be detected
    assert len(result["tabs"]) == 1
    assert result["tabs"][0]["key"] == "uppercase"


def test_parse_tabs_block_structure():
    """Test that tabs contain blocks with correct structure."""
    markdown = """
## [TAB:test] Test Tab

Test content
"""

    result = _parse_tabs_from_markdown(markdown)

    assert result is not None
    tab = result["tabs"][0]

    # Check block structure
    assert "blocks" in tab
    assert len(tab["blocks"]) == 1
    assert tab["blocks"][0]["type"] == "markdown"
    assert "content" in tab["blocks"][0]
