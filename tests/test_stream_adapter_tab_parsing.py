"""Tests for stream adapter tab parsing functionality."""

import pytest

from services.stream_adapter import (
    _parse_tabs_from_markdown,
    _parse_blocks_from_content,
    _try_parse_block,
)


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


# ======== Structured Block Parsing Tests ========


class TestBlockFenceParsing:
    """Tests for ```block:type fence parsing within tabs."""

    def test_kpi_grid_block(self):
        """Test parsing a kpi_grid block fence."""
        markdown = """
## [TAB:overview] 整体概览

```block:kpi_grid
{
  "data": [
    {"label": "平均分", "value": 48, "status": "down", "subtext": "低于及格线"},
    {"label": "及格率", "value": "0%", "status": "down"}
  ]
}
```

本次作业整体表现堪忧。
"""

        result = _parse_tabs_from_markdown(markdown)
        assert result is not None
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 2
        # First block: kpi_grid
        assert blocks[0]["type"] == "kpi_grid"
        assert len(blocks[0]["data"]) == 2
        assert blocks[0]["data"][0]["label"] == "平均分"
        assert blocks[0]["data"][0]["value"] == 48
        assert blocks[0]["data"][0]["status"] == "down"
        # Second block: markdown text
        assert blocks[1]["type"] == "markdown"
        assert "整体表现堪忧" in blocks[1]["content"]

    def test_chart_block(self):
        """Test parsing a chart block fence."""
        markdown = """
## [TAB:dist] 成绩分布

```block:chart
{
  "variant": "bar",
  "title": "分数段分布",
  "xAxis": ["0-60", "60-70", "70-80", "80-90", "90-100"],
  "series": [{"name": "人数", "data": [4, 0, 0, 0, 0]}]
}
```

所有学生成绩集中在低分段。
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 2
        assert blocks[0]["type"] == "chart"
        assert blocks[0]["variant"] == "bar"
        assert blocks[0]["title"] == "分数段分布"
        assert blocks[0]["xAxis"] == ["0-60", "60-70", "70-80", "80-90", "90-100"]
        assert blocks[0]["series"][0]["data"] == [4, 0, 0, 0, 0]

    def test_table_block(self):
        """Test parsing a table block fence."""
        markdown = """
## [TAB:students] 学生明细

```block:table
{
  "title": "成绩明细",
  "headers": ["姓名", "分数", "评价"],
  "rows": [
    {"cells": ["张三", 95, "优秀"], "status": "success"},
    {"cells": ["李四", 45, "不及格"], "status": "warning"}
  ]
}
```
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 1
        assert blocks[0]["type"] == "table"
        assert blocks[0]["headers"] == ["姓名", "分数", "评价"]
        assert len(blocks[0]["rows"]) == 2
        assert blocks[0]["rows"][0]["status"] == "success"

    def test_suggestion_list_block(self):
        """Test parsing a suggestion_list block fence."""
        markdown = """
## [TAB:suggestions] 教学建议

```block:suggestion_list
{
  "title": "改进建议",
  "items": [
    {"title": "加强基础", "description": "增加练习量", "priority": "high", "category": "教学"},
    {"title": "关注差生", "description": "个别辅导", "priority": "medium", "category": "关注"}
  ]
}
```
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 1
        assert blocks[0]["type"] == "suggestion_list"
        assert blocks[0]["title"] == "改进建议"
        assert len(blocks[0]["items"]) == 2
        assert blocks[0]["items"][0]["priority"] == "high"

    def test_mixed_blocks_and_markdown(self):
        """Test a tab with multiple block types interleaved with markdown."""
        markdown = """
## [TAB:overview] 整体概览

```block:kpi_grid
{"data": [{"label": "平均分", "value": 72, "status": "up"}]}
```

从整体来看，本次作业表现有所提升。

```block:chart
{"variant": "bar", "title": "分布", "xAxis": ["A", "B"], "series": [{"name": "人数", "data": [10, 20]}]}
```

以上是分数段分布情况。
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 4
        assert blocks[0]["type"] == "kpi_grid"
        assert blocks[1]["type"] == "markdown"
        assert "表现有所提升" in blocks[1]["content"]
        assert blocks[2]["type"] == "chart"
        assert blocks[2]["variant"] == "bar"
        assert blocks[3]["type"] == "markdown"
        assert "分数段分布" in blocks[3]["content"]

    def test_multiple_tabs_with_blocks(self):
        """Test multiple tabs each with structured blocks."""
        markdown = """
## [TAB:overview] 概览

```block:kpi_grid
{"data": [{"label": "均分", "value": 80, "status": "up"}]}
```

## [TAB:suggestions] 建议

```block:suggestion_list
{"items": [{"title": "多练习", "priority": "high"}]}
```
"""

        result = _parse_tabs_from_markdown(markdown)
        assert len(result["tabs"]) == 2
        assert result["tabs"][0]["blocks"][0]["type"] == "kpi_grid"
        assert result["tabs"][1]["blocks"][0]["type"] == "suggestion_list"

    def test_invalid_json_degrades_to_markdown(self):
        """Test that invalid JSON inside a block fence degrades gracefully."""
        markdown = """
## [TAB:test] Test

```block:kpi_grid
{invalid json here}
```

Normal text after.
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        # Invalid JSON → becomes markdown block (not crash)
        assert len(blocks) == 2
        assert blocks[0]["type"] == "markdown"
        assert "invalid json" in blocks[0]["content"]
        assert blocks[1]["type"] == "markdown"
        assert "Normal text" in blocks[1]["content"]

    def test_unknown_block_type_degrades_to_markdown(self):
        """Test that unknown block types degrade to markdown."""
        markdown = """
## [TAB:test] Test

```block:unknown_widget
{"foo": "bar"}
```
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"

    def test_markdown_variant_block(self):
        """Test parsing a markdown block with variant."""
        markdown = """
## [TAB:test] Test

```block:markdown
{"content": "重要警告信息", "variant": "warning"}
```
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"
        assert blocks[0]["content"] == "重要警告信息"
        assert blocks[0]["variant"] == "warning"

    def test_plain_text_only_still_works(self):
        """Test backward compatibility — plain markdown without fences still works."""
        markdown = """
## [TAB:overview] 概览

这是一段纯文本内容，没有任何 block fence。

- 列表项 1
- 列表项 2
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"
        assert "纯文本内容" in blocks[0]["content"]

    def test_regular_code_fence_not_confused(self):
        """Test that regular code fences (```python etc) are NOT parsed as blocks."""
        markdown = """
## [TAB:code] 代码

```python
print("hello")
```

这是普通代码块。
"""

        result = _parse_tabs_from_markdown(markdown)
        blocks = result["tabs"][0]["blocks"]

        # Should be treated as one markdown block (no block:xxx pattern)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"
        assert "```python" in blocks[0]["content"]


class TestTryParseBlock:
    """Unit tests for _try_parse_block."""

    def test_valid_kpi_grid(self):
        block = _try_parse_block("kpi_grid", '{"data": [{"label": "x", "value": 1, "status": "up"}]}')
        assert block["type"] == "kpi_grid"
        assert len(block["data"]) == 1

    def test_valid_chart(self):
        block = _try_parse_block("chart", '{"variant": "bar", "title": "t", "xAxis": [], "series": []}')
        assert block["type"] == "chart"
        assert block["variant"] == "bar"

    def test_invalid_json(self):
        block = _try_parse_block("kpi_grid", "{not valid}")
        assert block["type"] == "markdown"

    def test_json_array_not_object(self):
        block = _try_parse_block("kpi_grid", '[1, 2, 3]')
        assert block["type"] == "markdown"

    def test_unknown_type(self):
        block = _try_parse_block("nonexistent", '{"foo": "bar"}')
        assert block["type"] == "markdown"


class TestParseBlocksFromContent:
    """Unit tests for _parse_blocks_from_content."""

    def test_empty_content(self):
        blocks = _parse_blocks_from_content("")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"

    def test_only_text(self):
        blocks = _parse_blocks_from_content("Hello world\n\nSome text")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "markdown"
        assert "Hello world" in blocks[0]["content"]

    def test_only_block(self):
        content = '```block:kpi_grid\n{"data": []}\n```'
        blocks = _parse_blocks_from_content(content)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "kpi_grid"

    def test_text_block_text(self):
        content = 'Before\n\n```block:chart\n{"variant":"pie","title":"t","xAxis":[],"series":[]}\n```\n\nAfter'
        blocks = _parse_blocks_from_content(content)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "markdown"
        assert blocks[1]["type"] == "chart"
        assert blocks[2]["type"] == "markdown"
