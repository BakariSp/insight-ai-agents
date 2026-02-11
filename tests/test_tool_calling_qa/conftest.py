"""Shared fixtures for Tool Calling QA suite.

Provides:
- Model list (filtered by available API keys)
- Mock registry swap (Phase 1 instant-return)
- Agent factory
- Result collector for cross-dimension report
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pytest

# Populate the tool registry before anything else
import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps, NativeAgent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from tools.registry import get_tool_names, _registry as _tool_registry

logger = logging.getLogger(__name__)

# ── Settings & API key detection ──────────────────────────────

_settings = None
try:
    from config.settings import get_settings
    _settings = get_settings()
except Exception:
    pass

_has_api_key = bool(
    _settings
    and (
        _settings.dashscope_api_key
        or _settings.openai_api_key
        or _settings.anthropic_api_key
        or _settings.zai_api_key
        or _settings.zai_intl_api_key
        or _settings.gemini_api_key
    )
)

pytestmark = pytest.mark.skipif(
    not _has_api_key,
    reason="No LLM API key — skipping tool calling QA tests",
)


# ── Model candidates ─────────────────────────────────────────

_CANDIDATE_MODELS: list[dict[str, str]] = [
    # ── DashScope 百炼统一平台 (all use dashscope_api_key) ──
    # GLM
    {"id": "dashscope/glm-4.7",            "label": "glm-4.7",       "key_attr": "dashscope_api_key"},
    # Qwen
    {"id": "dashscope/qwen3-max",           "label": "qwen3-max",     "key_attr": "dashscope_api_key"},
    {"id": "dashscope/qwen3-coder-plus",    "label": "qwen3-coder",   "key_attr": "dashscope_api_key"},
    # DeepSeek
    {"id": "dashscope/deepseek-v3.2",       "label": "deepseek-v3.2", "key_attr": "dashscope_api_key"},
    # Kimi
    {"id": "dashscope/kimi-k2.5",           "label": "kimi-k2.5",     "key_attr": "dashscope_api_key"},
    # ── OpenAI GPT-5 family ──
    {"id": "openai/gpt-5.2",               "label": "gpt-5.2",       "key_attr": "openai_api_key"},
    {"id": "openai/gpt-5-mini",            "label": "gpt-5-mini",    "key_attr": "openai_api_key"},
    # ── Google Gemini 3 ──
    {"id": "gemini/gemini-3-pro-preview",   "label": "gemini-3-pro",  "key_attr": "gemini_api_key"},
    {"id": "gemini/gemini-3-flash-preview", "label": "gemini-3-flash","key_attr": "gemini_api_key"},
]


def get_available_models() -> list[dict[str, str]]:
    """Filter to only models with configured API keys."""
    if not _settings:
        return []
    available = []
    for m in _CANDIDATE_MODELS:
        if getattr(_settings, m["key_attr"], ""):
            available.append(m)
    # Fallback: at least test default model
    if not available and _has_api_key:
        available = [{"id": _settings.default_model, "label": "default", "key_attr": ""}]
    return available


MODELS_TO_TEST = get_available_models()
DEFAULT_MODEL = MODELS_TO_TEST[0]["id"] if MODELS_TO_TEST else "dashscope/qwen3-max"


# ── Mock returns (instant, no actual content generation) ──────

MOCK_RETURNS: dict[str, dict] = {
    "get_teacher_classes": {"status": "ok", "classes": [
        {"classId": "c-001", "name": "三年一班", "grade": "三年级",
         "subject": "数学", "studentCount": 30, "assignmentCount": 5},
        {"classId": "c-002", "name": "三年二班", "grade": "三年级",
         "subject": "英语", "studentCount": 28, "assignmentCount": 4},
    ]},
    "get_class_detail": {"status": "ok", "classId": "c-001", "name": "三年一班",
                         "students": [{"studentId": "s-001", "name": "张三"},
                                      {"studentId": "s-002", "name": "李明"}],
                         "assignments": [{"assignmentId": "a-001", "title": "期中考试"}]},
    "get_assignment_submissions": {"status": "ok", "submissions": [], "scores": [85, 90, 78, 92, 66]},
    "get_student_grades": {"status": "ok", "grades": [
        {"assignmentId": "a-001", "score": 85, "total": 100}
    ]},
    "resolve_entity": {"status": "ok", "classId": "c-001", "studentId": ""},
    "calculate_stats": {"status": "ok", "mean": 84.3, "median": 85, "max": 100, "min": 60, "count": 30},
    "compare_performance": {"status": "ok", "diff": 5.0},
    "analyze_student_weakness": {"status": "ok", "weaknesses": ["二次函数图像变换", "三角恒等式"]},
    "get_student_error_patterns": {"status": "ok", "patterns": []},
    "calculate_class_mastery": {"status": "ok", "mastery": {}},
    "generate_quiz_questions": {"status": "ok", "questions": [
        {"text": "1+1=?", "options": ["1", "2", "3", "4"], "answer": "2"}
    ], "artifact_id": "art-mock", "artifact_type": "quiz", "content_format": "json", "version": 1},
    "propose_pptx_outline": {"status": "ok", "outline": [{"slide": 1, "title": "Introduction"}],
                             "artifact_id": "art-mock", "artifact_type": "pptx",
                             "content_format": "json", "version": 1},
    "generate_pptx": {"status": "ok", "artifact_id": "art-mock"},
    "generate_docx": {"status": "ok", "artifact_id": "art-mock"},
    "render_pdf": {"status": "ok", "artifact_id": "art-mock"},
    "generate_interactive_html": {"status": "ok", "html": "<h1>Mock</h1>",
                                  "artifact_id": "art-mock", "artifact_type": "interactive",
                                  "content_format": "html", "version": 1},
    "get_artifact": {"status": "ok", "artifact_id": "art-mock", "content": {"slides": []}},
    "patch_artifact": {"status": "ok", "artifact_id": "art-mock"},
    "regenerate_from_previous": {"status": "ok"},
    "search_teacher_documents": {"status": "ok", "results": [
        {"title": "期末复习大纲", "content": "二次函数复习要点：顶点式、一般式、交点式...", "score": 0.9}
    ]},
    "ask_clarification": {"status": "ok", "action": "clarify",
                          "clarify": {"question": "请问您想要什么科目的题目？",
                                      "options": ["数学-二次函数", "英语-语法", "物理-力学"]}},
    "build_report_page": {"status": "ok", "page": {}},
    "save_assignment": {"status": "ok", "assignmentId": "a-new-001"},
    "share_link": {"status": "ok", "url": "https://example.com/share/abc"},
}


def _mock_tool_func(tool_name: str, mock_return: dict):
    """Create a mock async function that returns instantly."""
    async def _mock(ctx, **kwargs):
        return mock_return
    _mock.__name__ = tool_name
    _mock.__qualname__ = tool_name
    return _mock


@pytest.fixture
def mock_tools():
    """Swap all registry tools with instant-return mocks. Restores after test."""
    originals: dict[str, Any] = {}
    for name, rt in _tool_registry.items():
        originals[name] = rt.func
        mock_return = MOCK_RETURNS.get(name, {"status": "ok"})
        rt.func = _mock_tool_func(name, mock_return)
    yield
    for name, original_func in originals.items():
        if name in _tool_registry:
            _tool_registry[name].func = original_func


# ── Agent runner (Phase 1 mock) ──────────────────────────────


async def run_agent_phase1(
    message: str,
    model_id: str,
    deps: AgentDeps | None = None,
    message_history: list[ModelMessage] | None = None,
    user_prompt: str | None = None,
) -> "QAResult":
    """Run NativeAgent with mocked tools — only tests LLM tool-call decisions."""
    import time

    if deps is None:
        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-test",
            language="zh-CN",
        )

    result_obj = QAResult(model_id=model_id, message=message)
    start = time.monotonic()

    try:
        agent = NativeAgent(model_name=model_id)
        result = await agent.run(
            message,
            deps=deps,
            message_history=message_history,
            user_prompt=user_prompt,
        )
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.output_text = _extract_output_text(result)
        result_obj.tool_calls_made = _extract_tool_calls(_extract_messages(result))

    except Exception as e:
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.error = f"{type(e).__name__}: {e}"

    return result_obj


# ── Result data class ─────────────────────────────────────────


@dataclass
class QAResult:
    model_id: str = ""
    message: str = ""
    output_text: str = ""
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""

    @property
    def tool_names(self) -> set[str]:
        return {tc["tool_name"] for tc in self.tool_calls_made}

    @property
    def tool_names_list(self) -> list[str]:
        return [tc["tool_name"] for tc in self.tool_calls_made]

    @property
    def called_any_tool(self) -> bool:
        return len(self.tool_calls_made) > 0

    def get_tool_args(self, tool_name: str) -> dict[str, Any] | None:
        """Get args of the first call to a specific tool."""
        for tc in self.tool_calls_made:
            if tc["tool_name"] == tool_name:
                return tc["args"]
        return None


# ── Extraction helpers ────────────────────────────────────────


def _extract_tool_calls(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    calls = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    args = part.args
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {"_raw": args}
                    calls.append({
                        "tool_name": part.tool_name,
                        "args": args if isinstance(args, dict) else {},
                        "tool_call_id": part.tool_call_id,
                    })
    return calls


def _extract_output_text(result) -> str:
    if hasattr(result, "output"):
        return result.output or ""
    if hasattr(result, "data"):
        return str(result.data)
    return ""


def _extract_messages(result) -> list[ModelMessage]:
    if hasattr(result, "all_messages"):
        return list(result.all_messages())
    if hasattr(result, "new_messages"):
        return list(result.new_messages())
    return []


# ── History builders ──────────────────────────────────────────


def build_chat_history(turns: int) -> list[ModelMessage]:
    """Build a simple chat history with N turns of small talk."""
    chat_pairs = [
        ("你好", "你好！有什么可以帮您的？"),
        ("今天天气不错", "是的，希望您教学愉快！"),
        ("谢谢", "不客气，随时为您服务。"),
        ("学校最近在搞活动", "听起来很有趣！需要我帮您准备什么教学材料吗？"),
        ("没事随便聊聊", "好的，随时可以找我帮忙。"),
    ]
    history: list[ModelMessage] = []
    for i in range(turns):
        user_msg, assistant_msg = chat_pairs[i % len(chat_pairs)]
        history.append(ModelRequest(parts=[UserPromptPart(content=user_msg)]))
        history.append(ModelResponse(parts=[TextPart(content=assistant_msg)]))
    return history


def build_tool_history(turns: int) -> list[ModelMessage]:
    """Build history with tool calls + large returns (simulates real usage)."""
    history: list[ModelMessage] = []
    mock_data = json.dumps({
        "status": "ok", "classes": [
            {"classId": f"c-{i:03d}", "name": f"班级{i}", "studentCount": 30}
            for i in range(10)
        ],
        "stats": {"mean": 84.3, "median": 85, "max": 100, "min": 60},
    }, ensure_ascii=False)

    for i in range(turns):
        history.append(ModelRequest(parts=[UserPromptPart(content=f"查询第{i+1}次操作")]))
        history.append(ModelResponse(parts=[
            ToolCallPart(tool_name="get_teacher_classes", args={}, tool_call_id=f"tc-{i}"),
        ]))
        history.append(ModelRequest(parts=[
            ToolReturnPart(tool_name="get_teacher_classes", content=mock_data, tool_call_id=f"tc-{i}"),
        ]))
        history.append(ModelResponse(parts=[TextPart(content=f"已为您查询完成第{i+1}次数据。")]))

    return history


def build_injected_prompt(doc_chars: int, user_instruction: str) -> str:
    """Simulate multimodal.py doc_context + text_prompt concatenation."""
    # Use realistic education content as filler
    sample = (
        "第一章 二次函数基础\n"
        "1.1 二次函数的定义与图像\n"
        "二次函数是形如 y = ax² + bx + c（a≠0）的函数。其图像为抛物线。\n"
        "当 a > 0 时开口向上，当 a < 0 时开口向下。\n"
        "顶点坐标为 (-b/2a, (4ac-b²)/4a)。\n"
        "对称轴为 x = -b/2a。\n\n"
        "1.2 二次函数的三种表示形式\n"
        "一般式: y = ax² + bx + c\n"
        "顶点式: y = a(x-h)² + k\n"
        "交点式: y = a(x-x₁)(x-x₂)\n\n"
        "1.3 二次函数与一元二次方程\n"
        "二次函数 y = ax² + bx + c 的图像与 x 轴的交点，\n"
        "就是一元二次方程 ax² + bx + c = 0 的实数根。\n"
        "判别式 Δ = b² - 4ac 决定了交点的个数。\n\n"
        "第二章 三角函数\n"
        "2.1 三角函数的定义\n"
        "在直角三角形中，sinθ = 对边/斜边，cosθ = 邻边/斜边，tanθ = 对边/邻边。\n"
        "在单位圆中，设角θ的终边与单位圆交于点P(x,y)，则 sinθ = y, cosθ = x。\n\n"
        "2.2 三角函数的图像与性质\n"
        "正弦函数 y = sinx 的周期为 2π，值域为 [-1, 1]。\n"
        "余弦函数 y = cosx 的周期为 2π，值域为 [-1, 1]。\n"
        "正切函数 y = tanx 的周期为 π，值域为 (-∞, +∞)。\n\n"
        "2.3 三角恒等变换\n"
        "和差化积公式：sin(α±β) = sinαcosβ ± cosαsinβ\n"
        "二倍角公式：sin2α = 2sinαcosα, cos2α = cos²α - sin²α\n"
        "辅助角公式：asinx + bcosx = √(a²+b²)sin(x+φ)\n\n"
        "第三章 导数与微积分初步\n"
        "3.1 导数的概念\n"
        "函数在某点的导数定义为 f'(x₀) = lim(Δx→0) [f(x₀+Δx)-f(x₀)]/Δx。\n"
        "导数的几何意义是曲线在该点切线的斜率。\n\n"
        "3.2 常见函数的导数\n"
        "幂函数：(xⁿ)' = nxⁿ⁻¹\n"
        "指数函数：(eˣ)' = eˣ, (aˣ)' = aˣlna\n"
        "对数函数：(lnx)' = 1/x\n"
        "三角函数：(sinx)' = cosx, (cosx)' = -sinx\n\n"
        "3.3 导数的应用\n"
        "利用导数可以判断函数的单调性、求极值和最值。\n"
        "f'(x) > 0 时函数单调递增，f'(x) < 0 时函数单调递减。\n"
        "极值点处 f'(x₀) = 0 且 f''(x₀) ≠ 0。\n\n"
    )

    if doc_chars <= 0:
        return user_instruction

    # Repeat sample to fill desired length
    doc_content = ""
    while len(doc_content) < doc_chars:
        doc_content += sample
    doc_content = doc_content[:doc_chars]

    return f"[Attached file: 教学大纲.pdf]\n{doc_content}\n\n{user_instruction}"


# ── Report helpers ────────────────────────────────────────────


# ── Live monitor hooks ────────────────────────────────────────


def pytest_runtest_setup(item):
    """Auto-mark D9 test case as 'running' in live monitor."""
    import re
    m = re.match(r"test_([a-z]+)(\d+)_", item.name)
    if m:
        case_id = f"{m.group(1)}-{m.group(2)}"
        try:
            from tests.test_tool_calling_qa.live_monitor import LiveMonitor
            LiveMonitor.get().mark_running(case_id)
        except Exception:
            pass


def pytest_unconfigure(config):
    """Stop the live monitor HTTP server at session end."""
    try:
        from tests.test_tool_calling_qa.live_monitor import LiveMonitor
        m = LiveMonitor.get()
        m.end_session()
        m.stop_server()
    except Exception:
        pass


# ── Report helpers ────────────────────────────────────────────


def print_dimension_report(
    dimension: str,
    results: dict[str, list[tuple[str, bool, str, float]]],
):
    """Print a dimension report: model → [(case_id, passed, detail, latency_ms)]."""
    model_labels = list(results.keys())

    print(f"\n{'='*70}")
    print(f"  {dimension}")
    print(f"{'='*70}")

    header = f"  {'Case':<16}"
    for label in model_labels:
        header += f" {label:>16}"
    print(header)
    print("  " + "-" * (16 + 17 * len(model_labels)))

    # Collect all case IDs
    all_cases = []
    for items in results.values():
        for case_id, *_ in items:
            if case_id not in all_cases:
                all_cases.append(case_id)

    for case_id in all_cases:
        row = f"  {case_id:<16}"
        for label in model_labels:
            items = results[label]
            match = [x for x in items if x[0] == case_id]
            if match:
                _, passed, detail, latency = match[0]
                status = "PASS" if passed else "FAIL"
                row += f" {status:>4} {latency:>7.0f}ms  "
            else:
                row += f" {'SKIP':>4}         "
        print(row)

    # Summary
    print()
    for label in model_labels:
        items = results[label]
        passed = sum(1 for _, p, *_ in items if p)
        total = len(items)
        pct = passed / total * 100 if total else 0
        print(f"  {label}: {passed}/{total} ({pct:.0f}%)")

    print(f"{'='*70}\n")
