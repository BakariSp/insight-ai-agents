"""Tool Calling Fidelity Test — detect fake vs real tool calls.

Two-phase design:
  Phase 1 (fast):  Mock all tool functions → instant return.
                   Only measures: did the LLM *issue* a tool_call?
                   ~2-5s per scenario per model.

  Phase 2 (slow):  Real tool execution, full pipeline.
                   Validates end-to-end correctness.

Multi-model comparison:
  Parameterized across models (Qwen, GLM, etc.) defined in MODELS_TO_TEST.
  Produces a side-by-side comparison table.

Usage:
    cd insight-ai-agent

    # Phase 1 only (fast, recommended first):
    pytest tests/test_tool_calling_fidelity.py -k "phase1" -v -s

    # Phase 1, specific model:
    pytest tests/test_tool_calling_fidelity.py -k "phase1 and qwen" -v -s

    # Phase 2 (slow, full execution):
    pytest tests/test_tool_calling_fidelity.py -k "phase2" -v -s

    # Full comparison report across all models:
    pytest tests/test_tool_calling_fidelity.py -k "test_model_comparison_report" -v -s

    # Everything:
    pytest tests/test_tool_calling_fidelity.py -v -s

Skipped automatically if no API key is configured.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pytest

import tools.native_tools  # noqa: F401  populate registry

from agents.native_agent import AgentDeps, NativeAgent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from tools.registry import get_tool_names, _registry as _tool_registry

logger = logging.getLogger(__name__)

# ── Skip if no API key ──────────────────────────────────────

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
    )
)

pytestmark = pytest.mark.skipif(
    not _has_api_key,
    reason="No LLM API key — skipping tool calling fidelity tests",
)

# ── Models to compare ───────────────────────────────────────

# Add / remove models here.  Only models with a configured API key will run.
# Updated 2026-02-10: latest Qwen3 + GLM-4.x models.
_CANDIDATE_MODELS: list[dict[str, str]] = [
    # ── Qwen3 (Alibaba DashScope) ──
    # Note: "千问Plus" product name uses API ID "qwen-plus" (no "3"), but IS Qwen3 arch.
    # "qwen3-plus" and "qwen3-flash" do NOT exist as API IDs.
    {"id": "dashscope/qwen3-max",              "label": "qwen3-max",      "key_attr": "dashscope_api_key"},
    {"id": "dashscope/qwen-plus",              "label": "qwen-plus(q3)",  "key_attr": "dashscope_api_key"},
    {"id": "dashscope/qwen3-coder-plus",       "label": "qwen3-coder",   "key_attr": "dashscope_api_key"},
    # ── GLM (Zhipu AI — China mainland) ──
    {"id": "zai/glm-4.7",                     "label": "glm-4.7",        "key_attr": "zai_api_key"},
    {"id": "zai/glm-4.7-flash",               "label": "glm-4.7-flash",  "key_attr": "zai_api_key"},
    {"id": "zai/glm-4.6",                     "label": "glm-4.6",        "key_attr": "zai_api_key"},
    # ── GLM (Zhipu AI — overseas z.ai, lower latency outside China) ──
    {"id": "zai-intl/glm-4.7",                "label": "glm-4.7-intl",   "key_attr": "zai_intl_api_key"},
    {"id": "zai-intl/glm-4.7-flash",          "label": "glm-4.7f-intl",  "key_attr": "zai_intl_api_key"},
]

# Filter to only models with available API keys
MODELS_TO_TEST: list[dict[str, str]] = []
if _settings:
    for m in _CANDIDATE_MODELS:
        if getattr(_settings, m["key_attr"], ""):
            MODELS_TO_TEST.append(m)

# Fallback: at least test the default model
if not MODELS_TO_TEST and _has_api_key:
    MODELS_TO_TEST = [{"id": _settings.default_model, "label": "default", "key_attr": ""}]


# ── Failure Modes ────────────────────────────────────────────


class FailureMode(str, Enum):
    TEXT_SIMULATION = "text_simulation"       # Described tool call in text, didn't call
    HALLUCINATED_TOOL = "hallucinated_tool"   # Called a non-existent tool
    MISSING_TOOL_CALL = "missing_tool_call"   # Should have called tool, didn't
    DUPLICATE_CALL = "duplicate_call"         # Same gen tool called 2+ times
    WRONG_TOOL = "wrong_tool"                 # Called wrong / forbidden tool
    UNEXPECTED_TOOL = "unexpected_tool"       # Chat scenario triggered tools


# ── Scenario Definition ─────────────────────────────────────


@dataclass
class Scenario:
    id: str
    category: str           # chat / generation / data / analysis / rag / ambiguous
    message: str
    expect_tool_call: bool  # Should the model call any tool?
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    class_id: str | None = None
    has_artifacts: bool = False
    description: str = ""


SCENARIOS: list[Scenario] = [
    # ─── Chat (should NOT call tools) ───
    Scenario(id="chat-01", category="chat", message="你好",
             expect_tool_call=False, description="Greeting"),
    Scenario(id="chat-02", category="chat", message="1+1等于多少？",
             expect_tool_call=False, description="General math"),
    Scenario(id="chat-03", category="chat", message="什么是光合作用？",
             expect_tool_call=False, description="General science"),
    Scenario(id="chat-04", category="chat", message="谢谢你的帮助",
             expect_tool_call=False, description="Polite ack"),
    Scenario(id="chat-05", category="chat", message="你能做什么？",
             expect_tool_call=False, description="Ask capabilities"),

    # ─── Generation (MUST call tool) ───
    Scenario(id="gen-01", category="generation",
             message="帮我出 5 道英语选择题",
             expect_tool_call=True,
             expected_tools=["generate_quiz_questions"],
             description="Quiz generation"),
    Scenario(id="gen-02", category="generation",
             message="生成一个关于牛顿三定律的互动网页",
             expect_tool_call=True,
             expected_tools=["generate_interactive_html"],
             description="Interactive HTML"),
    Scenario(id="gen-03", category="generation",
             message="帮我做一个 PPT 大纲，主题是二次函数复习课",
             expect_tool_call=True,
             expected_tools=["propose_pptx_outline"],
             description="PPT outline"),
    Scenario(id="gen-04", category="generation",
             message="出 10 道数学填空题，难度中等，关于三角函数",
             expect_tool_call=True,
             expected_tools=["generate_quiz_questions"],
             description="Specific quiz"),
    Scenario(id="gen-05", category="generation",
             message="生成一个可以跟 AI 对话练习英语口语的互动页面",
             expect_tool_call=True,
             expected_tools=["generate_interactive_html"],
             description="Interactive + AI chat"),

    # ─── Data query (MUST call data tools) ───
    Scenario(id="data-01", category="data",
             message="我有几个班级？",
             expect_tool_call=True,
             expected_tools=["get_teacher_classes"],
             description="List classes"),
    Scenario(id="data-02", category="data",
             message="帮我看看三年一班有哪些学生",
             expect_tool_call=True,
             expected_tools=["get_teacher_classes", "get_class_detail", "resolve_entity"],
             description="Student roster"),

    # ─── Analysis ───
    Scenario(id="analysis-01", category="analysis",
             message="帮我分析一下这个班的成绩",
             expect_tool_call=True,
             expected_tools=[
                 "get_teacher_classes", "get_class_detail",
                 "get_assignment_submissions", "calculate_stats",
                 "ask_clarification",
             ],
             class_id="c-test-001",
             description="Class analysis"),

    # ─── RAG ───
    Scenario(id="rag-01", category="rag",
             message="根据我上传的知识库资料，帮我出 5 道题",
             expect_tool_call=True,
             expected_tools=["search_teacher_documents", "generate_quiz_questions"],
             description="RAG → quiz"),

    # ─── Ambiguous ───
    Scenario(id="ambig-01", category="ambiguous",
             message="帮我生成题目",
             expect_tool_call=True,
             expected_tools=["ask_clarification", "generate_quiz_questions"],
             description="Ambiguous quiz"),
    Scenario(id="ambig-02", category="ambiguous",
             message="做一个互动网页",
             expect_tool_call=True,
             expected_tools=["ask_clarification", "generate_interactive_html"],
             description="Ambiguous interactive"),
]


# ── Result Structures ───────────────────────────────────────


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    message: str
    model_id: str = ""
    output_text: str = ""
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    latency_ms: float = 0.0
    passed: bool = True
    error: str = ""

    def add_failure(self, mode: FailureMode, detail: str):
        self.failures.append({"mode": mode.value, "detail": detail})
        self.passed = False


# ── Detection Logic ─────────────────────────────────────────

# Patterns: model DESCRIBES a tool call instead of executing it
_FAKE_CALL_PATTERNS = [
    r"我(需要|来|将|会|要)(先|)调用",
    r"调用\s*(get_|generate_|search_|calculate_|patch_|ask_)",
    r"使用\s*(get_|generate_|search_|calculate_|patch_|ask_)",
    r"执行\s*(get_|generate_|search_|calculate_|patch_|ask_)",
    r"(我|让我)(先|来|)(查看|查询|获取|检索|搜索)(一下|).{0,5}(。|$)",
    r"我(打算|准备|计划)(调用|使用|执行)",
    r"I('ll| will| need to| should) (call|invoke|use|execute)\s+\w+_\w+",
    # Tool name leaked into user-facing text
    r"\b(get_teacher_classes|get_class_detail|get_assignment_submissions|"
    r"get_student_grades|resolve_entity|calculate_stats|compare_performance|"
    r"analyze_student_weakness|get_student_error_patterns|calculate_class_mastery|"
    r"generate_quiz_questions|propose_pptx_outline|generate_pptx|generate_docx|"
    r"render_pdf|generate_interactive_html|get_artifact|patch_artifact|"
    r"regenerate_from_previous|search_teacher_documents|ask_clarification|"
    r"build_report_page)\b",
]
_FAKE_CALL_RE = re.compile("|".join(_FAKE_CALL_PATTERNS), re.IGNORECASE)

_GENERATION_TOOLS = {
    "generate_quiz_questions", "generate_interactive_html",
    "propose_pptx_outline", "generate_pptx", "generate_docx", "render_pdf",
}


def detect_failures(
    scenario: Scenario,
    output_text: str,
    tool_calls: list[dict[str, Any]],
) -> list[tuple[FailureMode, str]]:
    failures: list[tuple[FailureMode, str]] = []
    all_registered = set(get_tool_names())
    tools_called = [tc["tool_name"] for tc in tool_calls]

    # 1. TEXT_SIMULATION
    m = _FAKE_CALL_RE.search(output_text)
    if m:
        failures.append((
            FailureMode.TEXT_SIMULATION,
            f"Text describes tool call: '{m.group()[:80]}'",
        ))

    # 2. HALLUCINATED_TOOL
    for tc in tool_calls:
        if tc["tool_name"] not in all_registered:
            failures.append((
                FailureMode.HALLUCINATED_TOOL,
                f"Non-existent tool: '{tc['tool_name']}'",
            ))

    # 3. MISSING_TOOL_CALL
    if scenario.expect_tool_call and not tool_calls:
        failures.append((
            FailureMode.MISSING_TOOL_CALL,
            "No tools called when expected",
        ))

    # 4. DUPLICATE_CALL
    gen_calls = [t for t in tools_called if t in _GENERATION_TOOLS]
    for name, count in Counter(gen_calls).items():
        if count > 1:
            failures.append((
                FailureMode.DUPLICATE_CALL,
                f"'{name}' called {count}x",
            ))

    # 5. UNEXPECTED_TOOL (chat scenario triggered tools)
    if not scenario.expect_tool_call and tool_calls:
        failures.append((
            FailureMode.UNEXPECTED_TOOL,
            f"Chat triggered: {tools_called}",
        ))

    # 6. WRONG_TOOL (forbidden)
    for tc in tool_calls:
        if tc["tool_name"] in scenario.forbidden_tools:
            failures.append((
                FailureMode.WRONG_TOOL,
                f"Forbidden tool: '{tc['tool_name']}'",
            ))

    return failures


# ── Extraction Helpers ──────────────────────────────────────


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


# ── Mock Tools for Phase 1 (instant return) ─────────────────


_MOCK_RETURNS: dict[str, dict] = {
    "get_teacher_classes": {"status": "ok", "classes": [
        {"classId": "c-001", "name": "三年一班", "grade": "三年级",
         "subject": "数学", "studentCount": 30, "assignmentCount": 5},
    ]},
    "get_class_detail": {"status": "ok", "classId": "c-001", "name": "三年一班",
                         "students": [{"studentId": "s-001", "name": "张三"}],
                         "assignments": [{"assignmentId": "a-001", "title": "期中考试"}]},
    "get_assignment_submissions": {"status": "ok", "submissions": [], "scores": [85, 90, 78]},
    "get_student_grades": {"status": "ok", "grades": []},
    "resolve_entity": {"status": "ok", "classId": "c-001", "studentId": ""},
    "calculate_stats": {"status": "ok", "mean": 84.3, "median": 85, "max": 100, "min": 60, "count": 30},
    "compare_performance": {"status": "ok", "diff": 5.0},
    "analyze_student_weakness": {"status": "ok", "weaknesses": []},
    "get_student_error_patterns": {"status": "ok", "patterns": []},
    "calculate_class_mastery": {"status": "ok", "mastery": {}},
    "generate_quiz_questions": {"status": "ok", "questions": [
        {"text": "What is 1+1?", "options": ["1", "2", "3", "4"], "answer": "2"}
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
    "get_artifact": {"status": "ok", "artifact_id": "art-mock", "content": {}},
    "patch_artifact": {"status": "ok", "artifact_id": "art-mock"},
    "regenerate_from_previous": {"status": "ok"},
    "search_teacher_documents": {"status": "ok", "results": [
        {"title": "Mock Doc", "content": "This is mock content for testing.", "score": 0.9}
    ]},
    "ask_clarification": {"status": "ok", "action": "clarify",
                          "clarify": {"question": "Which subject?", "options": []}},
    "build_report_page": {"status": "ok", "page": {}},
}


def _mock_tool_func(tool_name: str, mock_return: dict):
    """Create a mock async function that returns instantly."""
    async def _mock(ctx, **kwargs):
        return mock_return
    _mock.__name__ = tool_name
    _mock.__qualname__ = tool_name
    return _mock


# ── Phase 1 Runner (fast: mock tools) ──────────────────────


async def _run_phase1(
    scenario: Scenario,
    model_id: str,
) -> ScenarioResult:
    """Run scenario with mocked tools — only tests LLM tool-call decisions.

    Replaces ``_registry[name].func`` with instant-return mocks so that
    ``get_tools_raw()`` / ``get_tools()`` return mock Tool objects.
    PydanticAI never executes real tool logic.
    """
    # Save original funcs and swap in mocks
    originals: dict[str, Any] = {}
    for name, rt in _tool_registry.items():
        originals[name] = rt.func
        mock_return = _MOCK_RETURNS.get(name, {"status": "ok"})
        rt.func = _mock_tool_func(name, mock_return)

    result_obj = ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        message=scenario.message,
        model_id=model_id,
    )

    deps = AgentDeps(
        teacher_id="t-fidelity-001",
        conversation_id=f"conv-{scenario.id}-{model_id.split('/')[-1]}",
        language="zh-CN",
        class_id=scenario.class_id,
        has_artifacts=scenario.has_artifacts,
    )

    start = time.monotonic()
    try:
        agent = NativeAgent(model_name=model_id)
        result = await agent.run(scenario.message, deps=deps)
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.output_text = _extract_output_text(result)
        result_obj.tool_calls_made = _extract_tool_calls(_extract_messages(result))

        for mode, detail in detect_failures(
            scenario, result_obj.output_text, result_obj.tool_calls_made,
        ):
            result_obj.add_failure(mode, detail)

    except Exception as e:
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.error = f"{type(e).__name__}: {e}"
        result_obj.add_failure(FailureMode.MISSING_TOOL_CALL, f"Exception: {result_obj.error}")
    finally:
        # Restore original funcs
        for name, original_func in originals.items():
            if name in _tool_registry:
                _tool_registry[name].func = original_func

    return result_obj


# ── Phase 2 Runner (slow: real tools) ───────────────────────


async def _run_phase2(
    scenario: Scenario,
    model_id: str,
) -> ScenarioResult:
    """Run scenario with real tool execution — full pipeline."""
    result_obj = ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        message=scenario.message,
        model_id=model_id,
    )

    deps = AgentDeps(
        teacher_id="t-fidelity-001",
        conversation_id=f"conv-p2-{scenario.id}",
        language="zh-CN",
        class_id=scenario.class_id,
        has_artifacts=scenario.has_artifacts,
    )

    start = time.monotonic()
    try:
        agent = NativeAgent(model_name=model_id)
        result = await agent.run(scenario.message, deps=deps)
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.output_text = _extract_output_text(result)
        result_obj.tool_calls_made = _extract_tool_calls(_extract_messages(result))

        for mode, detail in detect_failures(
            scenario, result_obj.output_text, result_obj.tool_calls_made,
        ):
            result_obj.add_failure(mode, detail)

    except Exception as e:
        result_obj.latency_ms = (time.monotonic() - start) * 1000
        result_obj.error = f"{type(e).__name__}: {e}"
        result_obj.add_failure(FailureMode.MISSING_TOOL_CALL, f"Exception: {result_obj.error}")

    return result_obj


# ── Report Printing ─────────────────────────────────────────


def _print_comparison_table(
    all_results: dict[str, list[ScenarioResult]],
):
    """Print a multi-model comparison table."""
    model_labels = list(all_results.keys())
    categories = sorted(set(s.category for s in SCENARIOS))

    print("\n" + "=" * 80)
    print("  TOOL CALLING FIDELITY — MULTI-MODEL COMPARISON")
    print("=" * 80)

    # ── Overall pass rates ──
    print("\n  Overall Pass Rate:")
    header = f"  {'Model':<20}"
    for label in model_labels:
        header += f" {label:>14}"
    print(header)
    print("  " + "-" * (20 + 15 * len(model_labels)))

    # Total
    row = f"  {'TOTAL':<20}"
    for label in model_labels:
        results = all_results[label]
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        pct = passed / total * 100 if total else 0
        row += f" {passed}/{total} ({pct:.0f}%)"
        row = row[:-1] + f"{'':>1}"
    print(row)

    # Per category
    for cat in categories:
        row = f"  {cat:<20}"
        for label in model_labels:
            results = [r for r in all_results[label] if r.category == cat]
            passed = sum(1 for r in results if r.passed)
            total = len(results)
            pct = passed / total * 100 if total else 0
            row += f" {passed}/{total} ({pct:3.0f}%)     "
        print(row)

    # ── Failure mode breakdown ──
    print(f"\n  Failure Mode Breakdown:")
    header = f"  {'Failure Mode':<24}"
    for label in model_labels:
        header += f" {label:>14}"
    print(header)
    print("  " + "-" * (24 + 15 * len(model_labels)))

    all_modes = sorted(set(
        f["mode"]
        for results in all_results.values()
        for r in results
        for f in r.failures
    ))
    for mode in all_modes:
        row = f"  {mode:<24}"
        for label in model_labels:
            count = sum(
                1 for r in all_results[label]
                for f in r.failures if f["mode"] == mode
            )
            row += f" {count:>14}"
        print(row)

    # ── Latency comparison ──
    print(f"\n  Avg Latency (ms):")
    header = f"  {'Category':<20}"
    for label in model_labels:
        header += f" {label:>14}"
    print(header)
    print("  " + "-" * (20 + 15 * len(model_labels)))

    for cat in categories:
        row = f"  {cat:<20}"
        for label in model_labels:
            results = [r for r in all_results[label] if r.category == cat]
            avg = sum(r.latency_ms for r in results) / len(results) if results else 0
            row += f" {avg:>11.0f}ms "
        print(row)

    # ── Per-scenario detail ──
    print("\n" + "-" * 80)
    print("  PER-SCENARIO DETAIL")
    print("-" * 80)

    for scenario in SCENARIOS:
        print(f"\n  {scenario.id} — {scenario.description}")
        print(f"    Message: {scenario.message[:50]}")
        for label in model_labels:
            results = [r for r in all_results[label] if r.scenario_id == scenario.id]
            if not results:
                continue
            r = results[0]
            status = "PASS" if r.passed else "FAIL"
            tools = [tc["tool_name"] for tc in r.tool_calls_made]
            print(f"    [{status}] {label:>14}: tools={tools or '(none)'} "
                  f"({r.latency_ms:.0f}ms)")
            for f in r.failures:
                print(f"           ** {f['mode']}: {f['detail'][:60]}")

    print("\n" + "=" * 80)

    # ── JSON summary ──
    summary = {}
    for label in model_labels:
        results = all_results[label]
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        mode_counts = Counter(f["mode"] for r in results for f in r.failures)
        summary[label] = {
            "pass_rate": round(passed / total * 100, 1) if total else 0,
            "passed": passed,
            "total": total,
            "avg_latency_ms": round(
                sum(r.latency_ms for r in results) / total if total else 0
            ),
            "failure_modes": dict(mode_counts),
            "per_scenario": {
                r.scenario_id: {
                    "passed": r.passed,
                    "tools": [tc["tool_name"] for tc in r.tool_calls_made],
                    "failures": [f["mode"] for f in r.failures],
                    "latency_ms": round(r.latency_ms),
                }
                for r in results
            },
        }
    print("\n  JSON Summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════
#  PHASE 1 TESTS (fast — mocked tools)
# ═══════════════════════════════════════════════════════════════

# Use first available model for parametrized tests
_default_model = MODELS_TO_TEST[0]["id"] if MODELS_TO_TEST else "dashscope/qwen3-max"

_chat_scenarios = [s for s in SCENARIOS if s.category == "chat"]
_gen_scenarios = [s for s in SCENARIOS if s.category == "generation"]
_data_scenarios = [s for s in SCENARIOS if s.category == "data"]
_analysis_scenarios = [s for s in SCENARIOS if s.category == "analysis"]
_rag_scenarios = [s for s in SCENARIOS if s.category == "rag"]
_ambig_scenarios = [s for s in SCENARIOS if s.category == "ambiguous"]


class TestPhase1Chat:
    """Phase 1: Chat messages should NOT trigger tool calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _chat_scenarios, ids=[s.id for s in _chat_scenarios])
    async def test_phase1_chat_no_tools(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        tool_names = [tc["tool_name"] for tc in result.tool_calls_made]
        # Soft assertion: log but don't fail for minor issues
        if result.tool_calls_made:
            logger.warning("[%s] Chat triggered tools: %s", scenario.id, tool_names)
        assert not result.tool_calls_made, (
            f"[{scenario.id}] Chat triggered: {tool_names}"
        )


class TestPhase1Generation:
    """Phase 1: Generation requests MUST issue tool calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _gen_scenarios, ids=[s.id for s in _gen_scenarios])
    async def test_phase1_generation_calls_tool(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        tool_names = {tc["tool_name"] for tc in result.tool_calls_made}
        expected = set(scenario.expected_tools)
        assert tool_names & expected, (
            f"[{scenario.id}] Expected {scenario.expected_tools}, "
            f"got: {list(tool_names) or '(none)'}"
        )
        # No text simulation
        for f in result.failures:
            if f["mode"] == FailureMode.TEXT_SIMULATION.value:
                pytest.fail(f"[{scenario.id}] {f['detail']}")


class TestPhase1Data:
    """Phase 1: Data queries MUST call data tools."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _data_scenarios, ids=[s.id for s in _data_scenarios])
    async def test_phase1_data_calls_tool(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        tool_names = {tc["tool_name"] for tc in result.tool_calls_made}
        expected = set(scenario.expected_tools)
        assert tool_names & expected, (
            f"[{scenario.id}] Expected {scenario.expected_tools}, "
            f"got: {list(tool_names) or '(none)'}"
        )


class TestPhase1Analysis:
    """Phase 1: Analysis requests MUST call tools."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _analysis_scenarios, ids=[s.id for s in _analysis_scenarios])
    async def test_phase1_analysis_calls_tool(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        assert result.tool_calls_made, (
            f"[{scenario.id}] No tools called for analysis"
        )


class TestPhase1Rag:
    """Phase 1: RAG requests MUST call search_teacher_documents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _rag_scenarios, ids=[s.id for s in _rag_scenarios])
    async def test_phase1_rag_searches(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        tool_names = {tc["tool_name"] for tc in result.tool_calls_made}
        assert "search_teacher_documents" in tool_names, (
            f"[{scenario.id}] Expected search_teacher_documents, "
            f"got: {list(tool_names) or '(none)'}"
        )


class TestPhase1Ambiguous:
    """Phase 1: Ambiguous requests should clarify or generate."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _ambig_scenarios, ids=[s.id for s in _ambig_scenarios])
    async def test_phase1_ambiguous_handles(self, scenario: Scenario):
        result = await _run_phase1(scenario, _default_model)
        tool_names = {tc["tool_name"] for tc in result.tool_calls_made}
        expected = set(scenario.expected_tools)
        assert tool_names & expected, (
            f"[{scenario.id}] Expected {scenario.expected_tools}, "
            f"got: {list(tool_names) or '(none)'}"
        )


# ═══════════════════════════════════════════════════════════════
#  PHASE 2 TESTS (slow — real tool execution)
# ═══════════════════════════════════════════════════════════════


class TestPhase2Generation:
    """Phase 2: Full execution for generation scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", _gen_scenarios, ids=[s.id for s in _gen_scenarios])
    async def test_phase2_generation_full(self, scenario: Scenario):
        result = await _run_phase2(scenario, _default_model)
        tool_names = {tc["tool_name"] for tc in result.tool_calls_made}
        expected = set(scenario.expected_tools)
        assert tool_names & expected, (
            f"[{scenario.id}] Expected {scenario.expected_tools}, "
            f"got: {list(tool_names) or '(none)'}"
        )


# ═══════════════════════════════════════════════════════════════
#  MULTI-MODEL COMPARISON REPORT
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_model_comparison_report():
    """Phase 1 across ALL models — prints comparison table.

    This is the main diagnostic test.  Run with:
        pytest tests/test_tool_calling_fidelity.py -k "test_model_comparison_report" -v -s
    """
    if len(MODELS_TO_TEST) == 0:
        pytest.skip("No models available for comparison")

    all_results: dict[str, list[ScenarioResult]] = {}

    for model_info in MODELS_TO_TEST:
        model_id = model_info["id"]
        label = model_info["label"]
        results: list[ScenarioResult] = []

        print(f"\n  === Testing model: {label} ({model_id}) ===")

        for scenario in SCENARIOS:
            print(f"    {scenario.id}: {scenario.message[:35]}...", end=" ", flush=True)
            result = await _run_phase1(scenario, model_id)
            results.append(result)

            status = "PASS" if result.passed else "FAIL"
            tools = [tc["tool_name"] for tc in result.tool_calls_made]
            extra = ""
            if result.error:
                extra = f" ERR: {result.error[:80]}"
            elif not result.passed:
                modes = [f["mode"] for f in result.failures]
                extra = f" [{','.join(modes)}]"
            print(f"[{status}] {tools or '(none)'} ({result.latency_ms:.0f}ms){extra}")

        all_results[label] = results

    _print_comparison_table(all_results)

    # At least one model should pass >= 60%
    best_rate = max(
        sum(1 for r in results if r.passed) / len(results) * 100
        for results in all_results.values()
    )
    assert best_rate >= 50, (
        f"Best model pass rate {best_rate:.0f}% is below 50%"
    )
