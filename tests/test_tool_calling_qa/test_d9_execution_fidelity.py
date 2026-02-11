"""D9: Execution Fidelity — reproduce production failures where the AI *says*
it will execute but doesn't actually call any tool, gets stuck in clarification
loops, or loses intent after clarification.

Three sub-patterns:
  D9a  Promise Without Execution — AI replies "让我来生成..." but tool_calls=[]
  D9b  Clarification Loop — user already answered, AI keeps asking
  D9c  Intent Lost After Clarify — AI calls wrong tool after user clarifies

Driven by real production screenshots (2026-02-10).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d9_execution_fidelity.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    MOCK_RETURNS,
    MODELS_TO_TEST,
    QAResult,
    run_agent_phase1,
    print_dimension_report,
    _has_api_key,
)
from tests.test_tool_calling_qa.live_monitor import LiveMonitor

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ── Live monitor auto-start ──────────────────────────────────

# Forward-ref: ALL_D9_CASES is defined below, but we need it here.
# The fixture is evaluated lazily so it's fine.

@pytest.fixture(autouse=True, scope="module")
def _d9_live_monitor():
    """Start live monitor for D9 tests — dashboard at http://localhost:8888."""
    import sys
    # Fix Windows GBK encoding — force UTF-8 for Chinese + Unicode symbols
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    monitor = LiveMonitor.get()
    if not monitor.started:
        monitor.start_session("D9: Execution Fidelity", DEFAULT_MODEL, ALL_D9_CASES)
    yield
    monitor.end_session()


# ── Promise detection patterns ───────────────────────────────

_PROMISE_PATTERNS = [
    r"我(来|需要|将要|会|先)(帮您|帮你|为您|)(查看|查询|获取|搜索|检索|分析|生成|创建|制作|设计|做)",
    r"(让我|待我|请稍等).{0,15}(查看|查询|获取|检索|生成|创建|设计|制作)",
    r"(好的|好|可以|没问题).{0,10}(我来|让我|我将|马上)(帮您|帮你|为您|)(生成|创建|制作|查看|设计|出题|做)",
    r"(首先|第一步).{0,15}(我需要|需要先|要先)(查看|调用|获取|搜索)",
    r"我(正在|开始)(为您|帮您|)(生成|创建|制作|设计|查找|搜索)",
]

_RECLARIFY_PATTERNS = [
    r"(请问|请告诉|能否说明|请具体|请明确).{0,20}(什么|哪|怎么|具体|详细)",
    r"(您希望|您想要|您需要).{0,20}(什么|哪种|怎样的)",
    r"(还需要|需要更多).{0,10}(信息|细节|说明)",
    r"(例如|比如)[：:].{0,50}(？|\?)",
    r"(您可以从以下|请从以下).{0,20}(选择|选项)",
]


def _has_promise(text: str) -> bool:
    return any(re.search(p, text) for p in _PROMISE_PATTERNS)


def _has_reclarify(text: str) -> bool:
    return any(re.search(p, text) for p in _RECLARIFY_PATTERNS)


# ── History builders for clarify→execute scenarios ───────────


def _build_clarify_history(
    user_msg: str,
    clarify_question: str,
    tool_name: str = "ask_clarification",
    options: list[str] | None = None,
) -> list[ModelMessage]:
    """Simulate Turn 1: user sends vague request → agent calls ask_clarification."""
    if options is None:
        options = ["数学", "英语", "物理"]
    args = json.dumps({"question": clarify_question, "options": options})
    return [
        ModelRequest(parts=[UserPromptPart(content=user_msg)]),
        ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args=args,
                tool_call_id="tc-d9-clarify",
            ),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name=tool_name,
                content=json.dumps(MOCK_RETURNS[tool_name]),
                tool_call_id="tc-d9-clarify",
            ),
        ]),
        ModelResponse(parts=[TextPart(content=clarify_question)]),
    ]


def _build_interactive_clarify_history(
    detail_level: str = "basic",
) -> list[ModelMessage]:
    """Simulate Turn 1: user asks for interactive page → agent clarifies."""
    if detail_level == "detailed":
        user_msg = (
            "生成一个 深色霓虹主题：采用深紫黑色背景配蓝紫色霓虹光效\n"
            "科技感字体：使用Orbitron和Exo 2等未来感字体\n"
            "动态视觉效果：包括发光边框、扫描线动画、悬浮网格背景\n"
            "交互反馈：消息气泡有悬停效果，按钮有光泽流动动画\n"
            "打字指示器：AI思考时显示动态打字效果\n"
            "随机故障效果：偶尔出现的glitch特效增加科技感\n"
            "整体界面更加现代化和吸引人，特别适合年轻学生使用的互动网页"
        )
    else:
        user_msg = "做一个互动网页"
    return _build_clarify_history(
        user_msg,
        "请问您想做什么主题的互动网页？",
        options=["太阳系", "细胞分裂", "化学反应"],
    )


def _build_quiz_clarify_history() -> list[ModelMessage]:
    """Simulate Turn 1: user asks to generate exercises → agent clarifies."""
    return _build_clarify_history(
        "Generate targeted practice exercises based on 高一数学课",
        "请告诉我您希望针对高一数学的哪个具体主题生成练习题？",
        options=["集合与函数", "三角函数", "数列", "不等式", "平面向量"],
    )


def _build_ppt_clarify_history() -> list[ModelMessage]:
    """Simulate Turn 1: user asks for PPT → agent clarifies."""
    return _build_clarify_history(
        "帮我做PPT",
        "请问您想做什么主题的PPT？",
        options=["二次函数", "三角函数", "概率统计"],
    )


# ── Verbose result printer ───────────────────────────────────


def _print_raw(case_id: str, result: QAResult, passed: bool, verdict: str):
    """Push to live monitor first, then print raw detail."""
    has_promise_flag = _has_promise(result.output_text)
    has_reclarify_flag = _has_reclarify(result.output_text)

    # ── Push to live monitor FIRST (before any print that might fail) ──
    try:
        actual_id = case_id.split("/")[-1] if "/" in case_id else case_id
        model_label = case_id.split("/")[0] if "/" in case_id else None
        monitor = LiveMonitor.get()
        if not monitor.started:
            monitor.start_session("D9: Execution Fidelity", DEFAULT_MODEL, ALL_D9_CASES)
        monitor.record(
            case_id=actual_id,
            passed=passed,
            verdict=verdict,
            latency_ms=result.latency_ms,
            tool_calls=[
                {"name": tc["tool_name"], "args": tc["args"]}
                for tc in result.tool_calls_made
            ],
            output_text=result.output_text,
            error=result.error,
            flags={"promise": has_promise_flag, "reclarify": has_reclarify_flag},
            model=model_label,
        )
    except Exception as exc:
        print(f"  !!! monitor error: {exc}")

    # ── Console output ──
    status = "PASS" if passed else "FAIL"
    print(f"\n{'─'*70}")
    print(f"  [{case_id}] {status}  ({result.latency_ms:.0f}ms)")
    print(f"  verdict: {verdict}")
    print(f"  tool_calls: {result.tool_names_list or '(none)'}")
    if result.tool_calls_made:
        for tc in result.tool_calls_made:
            args_str = json.dumps(tc["args"], ensure_ascii=False)
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            print(f"    -> {tc['tool_name']}({args_str})")
    print(f"  output ({len(result.output_text)} chars):")
    output_display = result.output_text
    if len(output_display) > 800:
        output_display = output_display[:800] + f"\n    ...(truncated, total {len(result.output_text)} chars)"
    for line in output_display.split("\n"):
        print(f"    | {line}")
    if result.error:
        print(f"  ERROR: {result.error}")
    print(f"  flags: promise={has_promise_flag}, reclarify={has_reclarify_flag}")


# ── D9a: Promise Without Execution ──────────────────────────


class TestD9aPromiseWithoutExecution:
    """AI says 'let me generate/check...' but tool_calls is empty."""

    @pytest.mark.asyncio
    async def test_pwe01_quiz_after_clarify(self, mock_tools):
        """出题 clarify 后说 '我需要先查看' 但没 call — 来自生产截图 #1"""
        history = _build_quiz_clarify_history()
        result = await run_agent_phase1("三角函数", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        correct_tool = "generate_quiz_questions" in result.tool_names
        no_reclarify = "ask_clarification" not in result.tool_names
        promise_ok = not (_has_promise(result.output_text) and not has_tool)

        passed = has_tool and correct_tool and no_reclarify and promise_ok
        if not passed:
            reasons = []
            if not has_tool:
                reasons.append("no tool call at all")
            if not correct_tool and has_tool:
                reasons.append(f"wrong tool: {result.tool_names_list}")
            if not no_reclarify:
                reasons.append("re-clarified after user already answered")
            if not promise_ok:
                reasons.append("promised to act but didn't")
            verdict = " + ".join(reasons)
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("pwe-01", result, passed, verdict)
        assert passed, f"[pwe-01] {verdict}"

    @pytest.mark.asyncio
    async def test_pwe02_interactive_after_clarify(self, mock_tools):
        """互动网页 clarify 后说 '让我来设计' 但没 call — 来自生产截图 #4"""
        history = _build_interactive_clarify_history()
        result = await run_agent_phase1("太阳系行星运动", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        correct_tool = "generate_interactive_html" in result.tool_names
        no_reclarify = "ask_clarification" not in result.tool_names
        promise_ok = not (_has_promise(result.output_text) and not has_tool)

        passed = has_tool and correct_tool and no_reclarify and promise_ok
        verdict = f"tools={result.tool_names_list}" if not passed else f"correctly called {result.tool_names_list}"
        _print_raw("pwe-02", result, passed, verdict)
        assert passed, f"[pwe-02] {verdict}"

    @pytest.mark.asyncio
    async def test_pwe03_ppt_after_clarify(self, mock_tools):
        """PPT clarify 后说 '我来帮您' 但没 call"""
        history = _build_ppt_clarify_history()
        result = await run_agent_phase1("二次函数复习课", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        correct_tool = "propose_pptx_outline" in result.tool_names
        no_reclarify = "ask_clarification" not in result.tool_names
        promise_ok = not (_has_promise(result.output_text) and not has_tool)

        passed = has_tool and correct_tool and no_reclarify and promise_ok
        verdict = f"tools={result.tool_names_list}" if not passed else f"correctly called {result.tool_names_list}"
        _print_raw("pwe-03", result, passed, verdict)
        assert passed, f"[pwe-03] {verdict}"

    @pytest.mark.asyncio
    async def test_pwe04_rag_quiz_after_clarify(self, mock_tools):
        """根据知识库出题 clarify 后说 '我需要先查看文档' 但没搜索 — 来自截图 #1"""
        history = _build_clarify_history(
            "根据知识库帮我出题",
            "请问您想针对哪个科目或知识点出题？",
            options=["三角函数", "二次方程", "概率"],
        )
        result = await run_agent_phase1("三角函数相关的", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        has_search = "search_teacher_documents" in result.tool_names
        has_quiz = "generate_quiz_questions" in result.tool_names
        no_reclarify = "ask_clarification" not in result.tool_names
        promise_ok = not (_has_promise(result.output_text) and not has_tool)

        passed = has_tool and (has_search or has_quiz) and no_reclarify and promise_ok
        reasons = []
        if not has_tool:
            reasons.append("no tool call")
        if not (has_search or has_quiz) and has_tool:
            reasons.append(f"wrong tools: {result.tool_names_list}")
        if not no_reclarify:
            reasons.append("re-clarified")
        if not promise_ok:
            reasons.append("promised but didn't")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("pwe-04", result, passed, verdict)
        assert passed, f"[pwe-04] {verdict}"

    @pytest.mark.asyncio
    async def test_pwe05_explicit_quiz_after_clarify(self, mock_tools):
        """明确的出题请求 clarify 后仍然不执行"""
        history = _build_clarify_history(
            "生成练习题",
            "请告诉我您需要什么科目和类型的练习题？",
        )
        result = await run_agent_phase1(
            "数学 10道选择题 三角函数", DEFAULT_MODEL, message_history=history,
        )

        has_tool = result.called_any_tool
        correct_tool = "generate_quiz_questions" in result.tool_names
        no_reclarify = "ask_clarification" not in result.tool_names

        passed = has_tool and correct_tool and no_reclarify
        verdict = f"tools={result.tool_names_list}" if not passed else f"correctly called {result.tool_names_list}"
        _print_raw("pwe-05", result, passed, verdict)
        assert passed, f"[pwe-05] {verdict}"


# ── D9b: Clarification Loop ─────────────────────────────────


class TestD9bClarificationLoop:
    """User already provided enough info, AI should NOT re-clarify."""

    @pytest.mark.asyncio
    async def test_cloop01_neon_theme_then_purpose(self, mock_tools):
        """详细霓虹主题需求 → clarify → '对话练习' → 不该再问 — 来自生产截图 #2/#3"""
        history = _build_interactive_clarify_history(detail_level="detailed")
        result = await run_agent_phase1("对话练习", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        no_reclarify = "ask_clarification" not in result.tool_names
        correct_tool = "generate_interactive_html" in result.tool_names

        passed = has_tool and no_reclarify and correct_tool
        reasons = []
        if not has_tool:
            reasons.append("no tool call")
        if not no_reclarify:
            reasons.append("CLARIFICATION LOOP: asked again after user answered")
        if has_tool and not correct_tool:
            reasons.append(f"wrong tool: {result.tool_names_list}")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("cloop-01", result, passed, verdict)
        assert passed, f"[cloop-01] {verdict}"

    @pytest.mark.asyncio
    async def test_cloop02_quiz_topic_provided(self, mock_tools):
        """出题 clarify 后给了主题 → 不该再问题型/难度"""
        history = _build_clarify_history(
            "帮我出一些针对性练习题",
            "请问您想针对哪个科目或知识点？",
        )
        result = await run_agent_phase1("高一数学三角函数", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        no_reclarify = "ask_clarification" not in result.tool_names
        correct_tool = "generate_quiz_questions" in result.tool_names

        passed = has_tool and no_reclarify and correct_tool
        reasons = []
        if not has_tool:
            reasons.append("no tool call")
        if not no_reclarify:
            reasons.append("CLARIFICATION LOOP: re-asked after topic provided")
        if has_tool and not correct_tool:
            reasons.append(f"wrong tool: {result.tool_names_list}")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("cloop-02", result, passed, verdict)
        assert passed, f"[cloop-02] {verdict}"

    @pytest.mark.asyncio
    async def test_cloop03_brownian_motion(self, mock_tools):
        """互动网页 → clarify → '布朗运动' → 不该追问 '哪个方面' — 来自生产截图 #4"""
        history = _build_interactive_clarify_history()
        result = await run_agent_phase1("布朗运动", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        no_reclarify = "ask_clarification" not in result.tool_names
        correct_tool = "generate_interactive_html" in result.tool_names

        passed = has_tool and no_reclarify and correct_tool
        reasons = []
        if not has_tool:
            reasons.append("no tool call")
        if not no_reclarify:
            reasons.append("CLARIFICATION LOOP: asked for sub-topic")
        if has_tool and not correct_tool:
            reasons.append(f"wrong tool: {result.tool_names_list}")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("cloop-03", result, passed, verdict)
        assert passed, f"[cloop-03] {verdict}"

    @pytest.mark.asyncio
    async def test_cloop04_detailed_requirements_still_clarify(self, mock_tools):
        """200字详细需求 → 补充了用途 → 不该再追问 — 来自生产截图 #2/#3"""
        detailed_msg = (
            "生成一个 深色霓虹主题：采用深紫黑色背景配蓝紫色霓虹光效\n"
            "科技感字体：使用Orbitron和Exo 2等未来感字体\n"
            "动态视觉效果：包括发光边框、扫描线动画、悬浮网格背景\n"
            "交互反馈：消息气泡有悬停效果，按钮有光泽流动动画\n"
            "打字指示器：AI思考时显示动态打字效果\n"
            "随机故障效果：偶尔出现的glitch特效增加科技感\n"
            "整体界面更加现代化和吸引人，特别适合年轻学生使用的互动网页"
        )
        history = _build_clarify_history(
            detailed_msg,
            "请问您希望这个互动网页用来做什么？",
            options=["对话练习", "知识问答", "教学演示"],
        )
        result = await run_agent_phase1("对话练习", DEFAULT_MODEL, message_history=history)

        has_tool = result.called_any_tool
        no_reclarify = "ask_clarification" not in result.tool_names
        correct_tool = "generate_interactive_html" in result.tool_names

        passed = has_tool and no_reclarify and correct_tool
        reasons = []
        if not has_tool:
            reasons.append("no tool call at all (200ch detail + purpose provided!)")
        if not no_reclarify:
            reasons.append("CLARIFICATION LOOP: STILL asking after 200ch + purpose")
        if has_tool and not correct_tool:
            reasons.append(f"wrong tool: {result.tool_names_list}")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("cloop-04", result, passed, verdict)
        assert passed, f"[cloop-04] {verdict}"

    @pytest.mark.asyncio
    async def test_cloop05_multiple_topics_one_shot(self, mock_tools):
        """用户同时给了多个主题 → 不该追问选哪个 — 来自截图 #4"""
        history = _build_interactive_clarify_history()
        result = await run_agent_phase1(
            "化学-元素周期表", DEFAULT_MODEL, message_history=history,
        )

        has_tool = result.called_any_tool
        no_reclarify = "ask_clarification" not in result.tool_names
        correct_tool = "generate_interactive_html" in result.tool_names

        passed = has_tool and no_reclarify and correct_tool
        reasons = []
        if not has_tool:
            reasons.append("no tool call")
        if not no_reclarify:
            reasons.append("CLARIFICATION LOOP: topic was clear")
        if has_tool and not correct_tool:
            reasons.append(f"wrong tool: {result.tool_names_list}")
        verdict = " + ".join(reasons) if reasons else f"correctly called {result.tool_names_list}"

        _print_raw("cloop-05", result, passed, verdict)
        assert passed, f"[cloop-05] {verdict}"


# ── D9c: Intent Lost After Clarify ──────────────────────────


class TestD9cIntentLostAfterClarify:
    """After clarification, AI calls the WRONG tool (intent drift)."""

    @pytest.mark.asyncio
    async def test_ilac01_quiz_becomes_search(self, mock_tools):
        """出题 → clarify → '三角函数' → 应出题不应去搜索"""
        history = _build_clarify_history(
            "帮我出题",
            "请问您想出什么科目的题目？",
        )
        result = await run_agent_phase1("三角函数", DEFAULT_MODEL, message_history=history)

        correct = "generate_quiz_questions" in result.tool_names
        wrong_search_only = (
            "search_teacher_documents" in result.tool_names
            and "generate_quiz_questions" not in result.tool_names
        )

        passed = correct and not wrong_search_only
        if wrong_search_only:
            verdict = "INTENT DRIFT: searched instead of generating quiz"
        elif not result.called_any_tool:
            verdict = "no tool call"
        elif not correct:
            verdict = f"wrong tool: {result.tool_names_list}"
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("ilac-01", result, passed, verdict)
        assert passed, f"[ilac-01] {verdict}"

    @pytest.mark.asyncio
    async def test_ilac02_interactive_becomes_report(self, mock_tools):
        """互动网页 → clarify → '化学元素周期表' → 应 interactive 不应 report"""
        history = _build_interactive_clarify_history()
        result = await run_agent_phase1("化学元素周期表", DEFAULT_MODEL, message_history=history)

        correct = "generate_interactive_html" in result.tool_names
        wrong_report = "build_report_page" in result.tool_names and not correct

        passed = correct
        if wrong_report:
            verdict = "INTENT DRIFT: called build_report_page instead of generate_interactive_html"
        elif not result.called_any_tool:
            verdict = "no tool call"
        elif not correct:
            verdict = f"wrong tool: {result.tool_names_list}"
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("ilac-02", result, passed, verdict)
        assert passed, f"[ilac-02] {verdict}"

    @pytest.mark.asyncio
    async def test_ilac03_interactive_re_clarified(self, mock_tools):
        """互动网页 → clarify → '生物细胞结构' → 不应重新 clarify"""
        history = _build_interactive_clarify_history()
        result = await run_agent_phase1("生物细胞结构", DEFAULT_MODEL, message_history=history)

        correct = "generate_interactive_html" in result.tool_names
        re_clarified = "ask_clarification" in result.tool_names and not correct

        passed = correct
        if re_clarified:
            verdict = "INTENT LOST: re-clarified instead of executing"
        elif not result.called_any_tool:
            verdict = "no tool call at all"
        elif not correct:
            verdict = f"wrong tool: {result.tool_names_list}"
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("ilac-03", result, passed, verdict)
        assert passed, f"[ilac-03] {verdict}"

    @pytest.mark.asyncio
    async def test_ilac04_ppt_becomes_quiz(self, mock_tools):
        """PPT → clarify → '光合作用' → 应 PPT outline 不应出题"""
        history = _build_ppt_clarify_history()
        result = await run_agent_phase1("光合作用", DEFAULT_MODEL, message_history=history)

        correct = "propose_pptx_outline" in result.tool_names
        wrong_quiz = "generate_quiz_questions" in result.tool_names and not correct

        passed = correct
        if wrong_quiz:
            verdict = "INTENT DRIFT: generated quiz instead of PPT outline"
        elif not result.called_any_tool:
            verdict = "no tool call"
        elif not correct:
            verdict = f"wrong tool: {result.tool_names_list}"
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("ilac-04", result, passed, verdict)
        assert passed, f"[ilac-04] {verdict}"

    @pytest.mark.asyncio
    async def test_ilac05_analysis_text_only(self, mock_tools):
        """成绩分析 → clarify → '三年一班' → 应调数据工具不应纯文本编造"""
        history = _build_clarify_history(
            "帮我分析成绩",
            "请问您想分析哪个班级的成绩？",
            options=["三年一班", "三年二班"],
        )
        deps = AgentDeps(
            teacher_id="t-qa-001",
            conversation_id="conv-qa-test",
            language="zh-CN",
            class_id="c-001",
        )
        result = await run_agent_phase1(
            "三年一班", DEFAULT_MODEL, deps=deps, message_history=history,
        )

        data_tools = {"get_teacher_classes", "get_class_detail", "calculate_stats",
                       "get_assignment_submissions", "analyze_student_weakness"}
        has_data_tool = bool(result.tool_names & data_tools)

        passed = has_data_tool
        if not result.called_any_tool:
            verdict = "no tool call — likely fabricating data"
        elif not has_data_tool:
            verdict = f"wrong tools (no data query): {result.tool_names_list}"
        else:
            verdict = f"correctly called {result.tool_names_list}"

        _print_raw("ilac-05", result, passed, verdict)
        assert passed, f"[ilac-05] {verdict}"


# ── Multi-model comparison ───────────────────────────────────


ALL_D9_CASES = [
    # (case_id, sub_dim, description)
    ("pwe-01", "D9a", "出题 clarify → 三角函数"),
    ("pwe-02", "D9a", "互动网页 clarify → 太阳系"),
    ("pwe-03", "D9a", "PPT clarify → 二次函数"),
    ("pwe-04", "D9a", "RAG出题 clarify → 三角函数"),
    ("pwe-05", "D9a", "明确出题 clarify → 数学10道"),
    ("cloop-01", "D9b", "霓虹主题 → 对话练习"),
    ("cloop-02", "D9b", "练习题 → 高一数学三角函数"),
    ("cloop-03", "D9b", "互动网页 → 布朗运动"),
    ("cloop-04", "D9b", "200字需求 → 对话练习"),
    ("cloop-05", "D9b", "互动网页 → 化学元素周期表"),
    ("ilac-01", "D9c", "出题 → 三角函数 (不搜索)"),
    ("ilac-02", "D9c", "互动网页 → 化学 (不 report)"),
    ("ilac-03", "D9c", "互动网页 → 生物 (不 re-clarify)"),
    ("ilac-04", "D9c", "PPT → 光合作用 (不出题)"),
    ("ilac-05", "D9c", "分析成绩 → 三年一班 (不编造)"),
]


async def _run_single_case(
    case_id: str, model_id: str, model_label: str | None = None,
) -> tuple[str, bool, str, float, QAResult]:
    """Run a single D9 case and return (case_id, passed, verdict, latency_ms, raw_result)."""
    try:
        LiveMonitor.get().mark_running(case_id, model=model_label)
    except Exception:
        pass
    # Map case_id → (history_builder, turn2_message, expected_tool, deps_kwargs)
    case_map: dict[str, tuple] = {
        "pwe-01": (_build_quiz_clarify_history, "三角函数", "generate_quiz_questions", {}),
        "pwe-02": (lambda: _build_interactive_clarify_history(), "太阳系行星运动", "generate_interactive_html", {}),
        "pwe-03": (_build_ppt_clarify_history, "二次函数复习课", "propose_pptx_outline", {}),
        "pwe-04": (
            lambda: _build_clarify_history("根据知识库帮我出题", "请问您想针对哪个知识点出题？", options=["三角函数", "二次方程"]),
            "三角函数相关的",
            "generate_quiz_questions|search_teacher_documents",
            {},
        ),
        "pwe-05": (
            lambda: _build_clarify_history("生成练习题", "请告诉我您需要什么科目和类型的练习题？"),
            "数学 10道选择题 三角函数",
            "generate_quiz_questions",
            {},
        ),
        "cloop-01": (
            lambda: _build_interactive_clarify_history(detail_level="detailed"),
            "对话练习",
            "generate_interactive_html",
            {},
        ),
        "cloop-02": (
            lambda: _build_clarify_history("帮我出一些针对性练习题", "请问您想针对哪个科目或知识点？"),
            "高一数学三角函数",
            "generate_quiz_questions",
            {},
        ),
        "cloop-03": (lambda: _build_interactive_clarify_history(), "布朗运动", "generate_interactive_html", {}),
        "cloop-04": (
            lambda: _build_clarify_history(
                "生成一个 深色霓虹主题：采用深紫黑色背景配蓝紫色霓虹光效\n科技感字体...\n整体界面更加现代化和吸引人",
                "请问您希望这个互动网页用来做什么？",
                options=["对话练习", "知识问答", "教学演示"],
            ),
            "对话练习",
            "generate_interactive_html",
            {},
        ),
        "cloop-05": (lambda: _build_interactive_clarify_history(), "化学-元素周期表", "generate_interactive_html", {}),
        "ilac-01": (
            lambda: _build_clarify_history("帮我出题", "请问您想出什么科目的题目？"),
            "三角函数",
            "generate_quiz_questions",
            {},
        ),
        "ilac-02": (lambda: _build_interactive_clarify_history(), "化学元素周期表", "generate_interactive_html", {}),
        "ilac-03": (lambda: _build_interactive_clarify_history(), "生物细胞结构", "generate_interactive_html", {}),
        "ilac-04": (_build_ppt_clarify_history, "光合作用", "propose_pptx_outline", {}),
        "ilac-05": (
            lambda: _build_clarify_history("帮我分析成绩", "请问您想分析哪个班级？", options=["三年一班", "三年二班"]),
            "三年一班",
            "get_teacher_classes|get_class_detail|calculate_stats",
            {"class_id": "c-001"},
        ),
    }

    history_fn, turn2_msg, expected_tools_str, extra_deps = case_map[case_id]
    expected_tools = set(expected_tools_str.split("|"))

    deps_kwargs = {"teacher_id": "t-qa-001", "conversation_id": "conv-qa-test", "language": "zh-CN"}
    deps_kwargs.update(extra_deps)
    deps = AgentDeps(**deps_kwargs)

    history = history_fn() if callable(history_fn) else history_fn
    result = await run_agent_phase1(turn2_msg, model_id, deps=deps, message_history=history)

    # Assess
    has_tool = result.called_any_tool
    has_expected = bool(result.tool_names & expected_tools)
    did_reclarify = "ask_clarification" in result.tool_names
    reclarify_only = did_reclarify and not has_expected   # re-asked WITHOUT doing the right thing
    promise_ok = not (_has_promise(result.output_text) and not has_tool)

    # Pass = called the expected tool + didn't just promise without acting.
    # Re-clarifying alongside the correct tool is a soft warning, not a hard fail —
    # many LLMs replay ask_clarification from history but still execute correctly.
    passed = has_tool and has_expected and promise_ok

    reasons = []
    if not has_tool:
        reasons.append("NO_TOOL")
    if not has_expected and has_tool:
        reasons.append(f"WRONG:{result.tool_names_list}")
    if reclarify_only:
        reasons.append("RE_CLARIFY_ONLY")
    elif did_reclarify:
        reasons.append("~reclarify")   # soft warning: re-asked but also executed
    if not promise_ok:
        reasons.append("PROMISE_NO_ACT")
    verdict = " + ".join(reasons) if reasons else f"OK:{result.tool_names_list}"

    return case_id, passed, verdict, result.latency_ms, result


@pytest.mark.asyncio
async def test_d9_model_comparison(mock_tools):
    """Run all 15 D9 cases across all available models — parallel execution with raw output."""
    if len(MODELS_TO_TEST) < 1:
        pytest.skip("No models available")

    # ── Start multi-model monitor session ──
    model_labels = [m["label"] for m in MODELS_TO_TEST]
    monitor = LiveMonitor.get()
    monitor.start_session(
        "D9: Execution Fidelity", "multi", ALL_D9_CASES, models=model_labels,
    )

    # Rate limits (DashScope, per model, independent):
    #   glm-4.7:       60 RPM → ~1 RPS  → must serialize
    #   kimi-k2.5:     60 RPM → ~1 RPS  → must serialize
    #   deepseek-v3.2: 15,000 RPM        → no limit needed
    #   qwen*:         high RPM           → no limit needed
    #   openai/gemini:  own endpoints     → no limit needed
    _SLOW_MODELS = {"glm", "kimi"}  # 60 RPM — run 1 at a time
    DEFAULT_BATCH = 5
    SLOW_BATCH = 1       # one request at a time
    SLOW_DELAY = 1.2     # seconds between requests (60 RPM ≈ 1/s, leave margin)

    def _is_slow(label: str) -> bool:
        return any(kw in label.lower() for kw in _SLOW_MODELS)

    print(f"\n{'='*70}")
    print(f"  D9: EXECUTION FIDELITY — {len(ALL_D9_CASES)} cases × {len(MODELS_TO_TEST)} models")
    print(f"  (60-RPM models serialized: {_SLOW_MODELS})")
    print(f"{'='*70}")

    async def _run_one_model(model_info: dict) -> tuple[str, list]:
        model_id = model_info["id"]
        label = model_info["label"]
        slow = _is_slow(label)
        batch_size = SLOW_BATCH if slow else DEFAULT_BATCH
        items = []

        case_ids = [c[0] for c in ALL_D9_CASES]
        for i in range(0, len(case_ids), batch_size):
            if i > 0 and slow:
                await asyncio.sleep(SLOW_DELAY)
            batch = case_ids[i:i + batch_size]
            tasks = [_run_single_case(cid, model_id, model_label=label) for cid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    items.append(("error", False, str(r), 0.0))
                else:
                    case_id, passed, verdict, latency, raw = r
                    items.append((case_id, passed, verdict, latency))
                    _print_raw(f"{label}/{case_id}", raw, passed, verdict)

        return label, items

    # Launch all models (semaphore limits actual concurrency)
    tasks = [_run_one_model(m) for m in MODELS_TO_TEST]
    model_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: dict[str, list] = {}
    for r in model_results:
        if isinstance(r, Exception):
            print(f"  MODEL ERROR: {r}")
        else:
            label, items = r
            all_results[label] = items

    # Print summary table
    print_dimension_report("D9: EXECUTION FIDELITY", all_results)

    # Sub-dimension breakdown
    for sub_dim, sub_label in [("D9a", "Promise Without Execution"),
                                ("D9b", "Clarification Loop"),
                                ("D9c", "Intent Lost After Clarify")]:
        sub_case_ids = {c[0] for c in ALL_D9_CASES if c[1] == sub_dim}
        print(f"\n  {sub_dim}: {sub_label}")
        for label, items in all_results.items():
            sub_items = [(cid, p, v, l) for cid, p, v, l in items if cid in sub_case_ids]
            passed = sum(1 for _, p, _, _ in sub_items if p)
            total = len(sub_items)
            print(f"    {label}: {passed}/{total}")

    # Overall pass rate per model
    print(f"\n  {'─'*50}")
    for label, items in all_results.items():
        passed = sum(1 for _, p, *_ in items if p)
        total = len(items)
        pct = passed / total * 100 if total else 0
        status = "✓" if pct >= 90 else "⚠" if pct >= 70 else "✗"
        print(f"  {status} {label}: {passed}/{total} ({pct:.0f}%) — target: 90%")
