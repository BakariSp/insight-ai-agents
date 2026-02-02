"""Component Registry — defines the UI components AI is allowed to use.

PlannerAgent can ONLY select component types from this registry.
Adding a new component requires:
  1. Frontend: implement + register in ReportRenderer
  2. Backend: add entry here
  3. PlannerAgent system prompt picks it up automatically via get_registry_description()
"""

COMPONENT_REGISTRY: dict[str, dict] = {
    "kpi_grid": {
        "description": "KPI 指标卡片网格，显示 label、value、status、subtext",
        "data_shape": {
            "items": [
                {"label": "str", "value": "str", "status": "str", "subtext": "str"}
            ]
        },
        "props": {"max_columns": "int"},
    },
    "chart": {
        "description": "图表组件，支持多种 variant",
        "variants": ["bar", "line", "radar", "pie", "gauge", "distribution"],
        "data_shape": {
            "xAxis": "list[str]",
            "series": [{"name": "str", "data": "list[float]"}],
        },
        "props": {"variant": "str", "title": "str", "color": "str"},
    },
    "table": {
        "description": "数据表格，支持 headers、rows、highlightRules",
        "data_shape": {
            "headers": "list[str]",
            "rows": [{"cells": "list", "status": "str"}],
        },
        "props": {"title": "str", "highlightRules": "list"},
    },
    "markdown": {
        "description": "Markdown 内容块，用于叙事和洞察",
        "variants": ["default", "insight", "warning", "success"],
        "data_shape": {"content": "str"},
        "props": {"variant": "str"},
    },
    "suggestion_list": {
        "description": "可执行建议列表，含优先级和分类",
        "data_shape": {
            "items": [
                {
                    "title": "str",
                    "description": "str",
                    "priority": "str",
                    "category": "str",
                }
            ]
        },
        "props": {"title": "str"},
    },
    "question_generator": {
        "description": "自动生成练习题，基于错误模式",
        "data_shape": {
            "questions": [
                {"id": "str", "type": "str", "question": "str", "answer": "str"}
            ]
        },
        "props": {"knowledgePoint": "str", "difficulty": "str"},
    },
}


def get_registry_description() -> str:
    """Return a formatted description of all registered components.

    Intended for injection into PlannerAgent system prompts.
    """
    lines: list[str] = ["## Available UI Components\n"]
    for name, spec in COMPONENT_REGISTRY.items():
        lines.append(f"### `{name}`")
        lines.append(f"  Description: {spec['description']}")
        if variants := spec.get("variants"):
            lines.append(f"  Variants: {', '.join(variants)}")
        lines.append(f"  Data shape: {spec['data_shape']}")
        lines.append(f"  Props: {spec['props']}")
        lines.append("")
    return "\n".join(lines)
