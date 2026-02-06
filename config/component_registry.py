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
        "description": "AI 题目生成器（V1）。输出 QuizOutputV1 格式，含 questions + quizMeta。"
        " ai_content_slot 必须为 true。",
        "data_shape": {
            "questions": [
                {
                    "questionType": "SINGLE_CHOICE | MULTIPLE_CHOICE | TRUE_FALSE | "
                    "FILL_IN_BLANK | SHORT_ANSWER | ORDERING | COMPOSITE",
                    "stem": "str",
                    "options": ["str (choice types only)"],
                    "correctAnswer": "str",
                    "explanation": "str",
                    "difficulty": "EASY | MEDIUM | HARD",
                    "points": "int (default 1)",
                    "knowledgePointIds": ["str"],
                    "subQuestions": ["QuizQuestionV1 (COMPOSITE only)"],
                }
            ],
            "quizMeta": {
                "totalCount": "int",
                "passedCount": "int",
                "avgQuality": "float",
                "generatedAt": "ISO datetime str",
            },
        },
        "props": {
            "title": "str",
            "count": "int (1-50)",
            "types": "list[str]",
            "difficulty": "easy | medium | hard",
            "subject": "str",
            "topic": "str",
            "knowledgePoint": "str",
        },
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
