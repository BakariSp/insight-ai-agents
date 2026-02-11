"""D8: Context Pressure — find breakpoints where tool calling drops off.

Three sub-dimensions:
  D8a: Verbose Intent — same intent, increasing message length
  D8b: History Depth — fixed message, increasing conversation history
  D8c: File Injection — fixed message, increasing prepended document content

Uses Phase 1 mock (instant tool returns, only tests LLM decision).

Usage:
    cd insight-ai-agent
    pytest tests/test_tool_calling_qa/test_d8_pressure.py -v -s
    pytest tests/test_tool_calling_qa/test_d8_pressure.py -v -s -k "d8a"
    pytest tests/test_tool_calling_qa/test_d8_pressure.py -v -s -k "d8b"
    pytest tests/test_tool_calling_qa/test_d8_pressure.py -v -s -k "d8c"
"""

from __future__ import annotations

import pytest

import tools.native_tools  # noqa: F401

from agents.native_agent import AgentDeps
from tests.test_tool_calling_qa.conftest import (
    DEFAULT_MODEL,
    MODELS_TO_TEST,
    run_agent_phase1,
    build_chat_history,
    build_tool_history,
    build_injected_prompt,
    print_dimension_report,
    _has_api_key,
)

pytestmark = pytest.mark.skipif(not _has_api_key, reason="No LLM API key")


# ═══════════════════════════════════════════════════════════════
#  D8a: Verbose Intent — escalating message length
# ═══════════════════════════════════════════════════════════════

VERBOSE_INTERACTIVE: list[tuple[str, str]] = [
    ("15ch", "做一个太阳系的互动网页"),
    ("100ch",
     "做一个关于太阳系的互动网页，展示八大行星的基本信息，"
     "包括轨道运动动画和行星的基本参数。"),
    ("300ch",
     "做一个关于太阳系的互动网页，要有八大行星的轨道运动动画，"
     "每个行星可以点击查看详细信息，包括质量、与太阳的距离和公转周期。"
     "背景使用深蓝色星空效果，左上角放标题，右侧放信息面板，"
     "底部有一个导航条可以切换行星。整体风格要科技感强，"
     "适合初中生使用，字体清晰，按钮要大一些方便操作。"),
    ("600ch",
     "做一个关于太阳系的互动网页，要有八大行星的轨道运动动画，"
     "每个行星可以点击查看详细信息，包括质量、与太阳的距离和公转周期。"
     "背景使用深蓝色星空效果，左上角放标题'太阳系探索之旅'，右侧放信息面板。"
     "底部有一个导航条可以切换行星，还要有一个搜索框可以搜索行星名称。"
     "整体风格要科技感强，适合初中生使用，字体用14px以上，按钮要大一些方便触屏操作。"
     "每个行星的详细信息要包含：中文名称、英文名称、质量（相对于地球）、"
     "赤道直径、与太阳平均距离、公转周期、自转周期、已知卫星数量。"
     "行星轨道要按照真实比例缩放，运动速度也要有差异（内行星快外行星慢）。"
     "还要有一个'比较模式'，可以同时选择两颗行星进行参数对比，"
     "用柱状图展示它们的差异。页面要支持移动端响应式布局。"),
    ("1000ch",
     "做一个关于太阳系的互动网页，要有八大行星的轨道运动动画，"
     "每个行星可以点击查看详细信息，包括质量、与太阳的距离和公转周期。"
     "背景使用深蓝色星空效果，左上角放标题'太阳系探索之旅'，右侧放信息面板。"
     "底部有一个导航条可以切换行星，还要有一个搜索框可以搜索行星名称。"
     "整体风格要科技感强，适合初中生使用，字体用14px以上，按钮要大一些方便触屏操作。"
     "每个行星的详细信息要包含：中文名称、英文名称、质量（相对于地球）、"
     "赤道直径、与太阳平均距离、公转周期、自转周期、已知卫星数量。"
     "行星轨道要按照真实比例缩放，运动速度也要有差异（内行星快外行星慢）。"
     "还要有一个'比较模式'，可以同时选择两颗行星进行参数对比，"
     "用柱状图展示它们的差异。页面要支持移动端响应式布局。"
     "首页进入时有一个欢迎动画，太阳从中心亮起，然后行星依次出现在轨道上。"
     "信息面板分为三个tab：基本参数、有趣事实、相关习题。"
     "有趣事实tab里放2-3条关于该行星的冷知识。"
     "相关习题tab里放1-2道与该行星相关的选择题，答对后有星星动画奖励。"
     "页面左下角有一个'知识测验'按钮，点击后弹出5道关于太阳系的综合测验。"
     "测验结束后显示得分和错题解析。整个页面的配色方案：主色 #0a1628，"
     "强调色 #4fc3f7，文字颜色 #e0e0e0，行星信息面板背景 rgba(10,22,40,0.85)。"
     "字体使用 Noto Sans SC，标题用 700 weight，正文用 400 weight。"),
]

VERBOSE_QUIZ: list[tuple[str, str]] = [
    ("10ch", "出10道数学选择题"),
    ("100ch",
     "帮我出10道中等难度的数学选择题，范围是高一上学期的内容，"
     "主要涉及二次函数和三角函数基础。"),
    ("300ch",
     "帮我出10道中等难度的数学选择题，范围是高一上学期的内容，"
     "主要涉及二次函数和三角函数基础。每道题要有4个选项，"
     "其中只有一个正确答案。干扰项要有一定的迷惑性，"
     "不能明显错误。题目难度分布：3道基础题、5道中等题、2道提高题。"
     "基础题主要考察概念理解，中等题考察简单应用，提高题考察综合分析。"
     "每道题附带简要解析，说明解题思路和关键步骤。"),
    ("600ch",
     "帮我出10道中等难度的数学选择题，范围是高一上学期的内容，"
     "主要涉及二次函数和三角函数基础。每道题要有4个选项，"
     "其中只有一个正确答案。干扰项要有一定的迷惑性，"
     "不能明显错误。题目难度分布：3道基础题、5道中等题、2道提高题。"
     "基础题主要考察概念理解，中等题考察简单应用，提高题考察综合分析。"
     "每道题附带简要解析，说明解题思路和关键步骤。"
     "具体知识点分布要求如下：二次函数部分出6道题，其中顶点式与图像变换2道，"
     "判别式与根的分布2道，二次函数应用题2道。三角函数部分出4道题，"
     "其中三角函数定义与基本公式2道，三角恒等变换1道，三角函数图像性质1道。"
     "选项格式统一，纯数字答案用分数或小数表示，表达式答案用LaTeX格式。"
     "题目序号用阿拉伯数字，选项用大写字母ABCD。"
     "最后附一个答案表，方便教师批改时参考。"),
]

VERBOSE_PPT: list[tuple[str, str]] = [
    ("15ch", "做一个关于二次函数复习课的PPT"),
    ("200ch",
     "做一个关于二次函数复习课的PPT，面向高一学生，大概15-20页。"
     "内容包括二次函数的三种表示形式、图像变换规律、"
     "最值问题和实际应用。每页要有关键公式和配图说明。"),
    ("500ch",
     "做一个关于二次函数复习课的PPT，面向高一学生，大概15-20页。"
     "内容包括二次函数的三种表示形式（一般式、顶点式、交点式）、"
     "图像变换规律（平移、伸缩、对称）、最值问题和实际应用。"
     "每页要有关键公式和配图说明。配色方案用蓝白为主，"
     "标题字体用黑体24号，正文用宋体18号。"
     "第一页是课题引入，用一个实际问题（比如抛体运动）引发思考。"
     "中间部分按知识点分块，每个知识点配2-3道典型例题。"
     "最后3页是综合练习、课堂小结和课后作业。"
     "练习题要分基础和提高两个层次。课堂小结用思维导图形式。"
     "页面间要有逻辑过渡，不能跳跃。每页内容不要太多，"
     "留白要充足，一页最多6行文字加一个图或公式。"),
]


# ═══════════════════════════════════════════════════════════════
#  D8b: History Depth
# ═══════════════════════════════════════════════════════════════

HISTORY_DEPTHS = [0, 3, 5, 8, 12]
HISTORY_MESSAGE = "帮我出5道英语选择题，关于过去完成时"
HISTORY_EXPECTED_TOOL = "generate_quiz_questions"


# ═══════════════════════════════════════════════════════════════
#  D8c: File Content Injection
# ═══════════════════════════════════════════════════════════════

INJECTION_LENGTHS = [0, 500, 2000, 5000, 10000]
INJECTION_MESSAGE = "帮我出5道选择题"
INJECTION_EXPECTED_TOOL = "generate_quiz_questions"
INJECTION_INTERFERENCE_MESSAGE = "这个文档讲了什么内容，帮我概括一下"


# ═══════════════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════════════


class TestD8aVerboseInteractive:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("label,message", VERBOSE_INTERACTIVE,
                             ids=[v[0] for v in VERBOSE_INTERACTIVE])
    async def test_d8a_interactive(self, mock_tools, label, message):
        result = await run_agent_phase1(message, DEFAULT_MODEL)
        print(f"  D8a interactive [{label}] {len(message)}ch: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)"
              + (f" ERROR={result.error}" if result.error else ""))

        # Infrastructure timeout is not a tool-calling decision failure
        if result.error and ("timed out" in result.error.lower() or "connection error" in result.error.lower()):
            pytest.skip(f"API infrastructure error at {label}: {result.error}")

        assert "generate_interactive_html" in result.tool_names, (
            f"[D8a-interactive-{label}] {len(message)} chars: "
            f"Expected generate_interactive_html, got: {result.tool_names_list or '(none)'}\n"
            f"Output: {result.output_text[:200]}"
        )


class TestD8aVerboseQuiz:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("label,message", VERBOSE_QUIZ,
                             ids=[v[0] for v in VERBOSE_QUIZ])
    async def test_d8a_quiz(self, mock_tools, label, message):
        result = await run_agent_phase1(message, DEFAULT_MODEL)
        print(f"  D8a quiz [{label}] {len(message)}ch: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        assert "generate_quiz_questions" in result.tool_names, (
            f"[D8a-quiz-{label}] {len(message)} chars: "
            f"Expected generate_quiz_questions, got: {result.tool_names_list or '(none)'}\n"
            f"Output: {result.output_text[:200]}"
        )


class TestD8aVerbosePPT:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("label,message", VERBOSE_PPT,
                             ids=[v[0] for v in VERBOSE_PPT])
    async def test_d8a_ppt(self, mock_tools, label, message):
        result = await run_agent_phase1(message, DEFAULT_MODEL)
        print(f"  D8a PPT [{label}] {len(message)}ch: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        acceptable = {"propose_pptx_outline", "ask_clarification"}
        assert result.tool_names & acceptable, (
            f"[D8a-ppt-{label}] {len(message)} chars: "
            f"Expected propose_pptx_outline or ask_clarification, got: "
            f"{result.tool_names_list or '(none)'}\n"
            f"Output: {result.output_text[:200]}"
        )


class TestD8bHistoryDepth:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("turns", HISTORY_DEPTHS, ids=[f"{t}t" for t in HISTORY_DEPTHS])
    async def test_d8b_chat_history(self, mock_tools, turns):
        history = build_chat_history(turns) if turns > 0 else None
        result = await run_agent_phase1(HISTORY_MESSAGE, DEFAULT_MODEL, message_history=history)
        print(f"  D8b chat [{turns}t]: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        assert HISTORY_EXPECTED_TOOL in result.tool_names, (
            f"[D8b-chat-{turns}t] Expected {HISTORY_EXPECTED_TOOL}, "
            f"got: {result.tool_names_list or '(none)'}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("turns", HISTORY_DEPTHS, ids=[f"{t}t" for t in HISTORY_DEPTHS])
    async def test_d8b_tool_history(self, mock_tools, turns):
        history = build_tool_history(turns) if turns > 0 else None
        result = await run_agent_phase1(HISTORY_MESSAGE, DEFAULT_MODEL, message_history=history)
        print(f"  D8b tool [{turns}t]: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        assert HISTORY_EXPECTED_TOOL in result.tool_names, (
            f"[D8b-tool-{turns}t] Expected {HISTORY_EXPECTED_TOOL}, "
            f"got: {result.tool_names_list or '(none)'}"
        )


class TestD8cFileInjection:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("doc_chars", INJECTION_LENGTHS,
                             ids=[f"{c}ch" for c in INJECTION_LENGTHS])
    async def test_d8c_injection(self, mock_tools, doc_chars):
        user_prompt = build_injected_prompt(doc_chars, INJECTION_MESSAGE)
        result = await run_agent_phase1(
            INJECTION_MESSAGE, DEFAULT_MODEL, user_prompt=user_prompt,
        )
        print(f"  D8c inject [{doc_chars}ch]: "
              f"tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)"
              + (f" ERROR={result.error}" if result.error else ""))

        # Infrastructure timeout is not a tool-calling decision failure
        if result.error and ("timed out" in result.error.lower() or "connection error" in result.error.lower()):
            pytest.skip(f"API infrastructure error at {doc_chars}ch: {result.error}")

        # accept ask_clarification as soft pass (model is trying to act, just cautious)
        acceptable = {INJECTION_EXPECTED_TOOL, "ask_clarification"}
        assert result.tool_names & acceptable, (
            f"[D8c-{doc_chars}ch] Expected {INJECTION_EXPECTED_TOOL} or ask_clarification, "
            f"got: {result.tool_names_list or '(none)'}\n"
            f"Prompt len: {len(user_prompt)} chars"
        )

    @pytest.mark.asyncio
    async def test_d8c_interference_no_false_trigger(self, mock_tools):
        """Doc with '生成''分析' words + non-tool question — should NOT trigger gen/analysis."""
        user_prompt = build_injected_prompt(2000, INJECTION_INTERFERENCE_MESSAGE)
        result = await run_agent_phase1(
            INJECTION_INTERFERENCE_MESSAGE, DEFAULT_MODEL, user_prompt=user_prompt,
        )
        gen_tools = {"generate_quiz_questions", "generate_interactive_html",
                     "propose_pptx_outline", "generate_pptx", "generate_docx"}
        analysis_tools = {"calculate_stats", "compare_performance", "analyze_student_weakness"}
        triggered_bad = result.tool_names & (gen_tools | analysis_tools)
        print(f"  D8c interference: tools={result.tool_names_list or '(none)'} ({result.latency_ms:.0f}ms)")
        assert not triggered_bad, (
            f"[D8c-interference] Doc keywords should NOT trigger: {triggered_bad}"
        )


# ═══════════════════════════════════════════════════════════════
#  Multi-model breakpoint analysis
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_d8_model_comparison(mock_tools):
    """Run D8a + D8c across all models concurrently — find per-model breakpoints."""
    import asyncio

    if len(MODELS_TO_TEST) < 2:
        pytest.skip("Need >= 2 models for comparison")

    async def _run_one_model(model_info):
        model_id = model_info["id"]
        label = model_info["label"]
        items: list[tuple[str, bool, str, float]] = []

        # D8a: Verbose interactive
        for tag, message in VERBOSE_INTERACTIVE:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_interactive_html" in result.tool_names
            detail = f"{len(message)}ch {'OK' if passed else 'MISS'}"
            items.append((f"d8a-html-{tag}", passed, detail, result.latency_ms))
            status = "PASS" if passed else "FAIL"
            print(f"    [{label}] d8a-html-{tag}: [{status}] {len(message)}ch ({result.latency_ms:.0f}ms)")

        # D8a: Verbose quiz
        for tag, message in VERBOSE_QUIZ:
            result = await run_agent_phase1(message, model_id)
            passed = "generate_quiz_questions" in result.tool_names
            detail = f"{len(message)}ch {'OK' if passed else 'MISS'}"
            items.append((f"d8a-quiz-{tag}", passed, detail, result.latency_ms))
            status = "PASS" if passed else "FAIL"
            print(f"    [{label}] d8a-quiz-{tag}: [{status}] {len(message)}ch ({result.latency_ms:.0f}ms)")

        # D8c: File injection
        for doc_chars in INJECTION_LENGTHS:
            user_prompt = build_injected_prompt(doc_chars, INJECTION_MESSAGE)
            result = await run_agent_phase1(INJECTION_MESSAGE, model_id, user_prompt=user_prompt)
            passed = "generate_quiz_questions" in result.tool_names
            detail = f"{doc_chars}doc {'OK' if passed else 'MISS'}"
            items.append((f"d8c-{doc_chars}", passed, detail, result.latency_ms))
            status = "PASS" if passed else "FAIL"
            print(f"    [{label}] d8c-{doc_chars}doc: [{status}] ({result.latency_ms:.0f}ms)")

        return label, items

    print(f"\n  === D8 Pressure: running {len(MODELS_TO_TEST)} models concurrently ===")
    tasks = [_run_one_model(m) for m in MODELS_TO_TEST]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: dict[str, list[tuple[str, bool, str, float]]] = {}
    for r in results_list:
        if isinstance(r, Exception):
            print(f"    ERROR: {r}")
            continue
        label, items = r
        all_results[label] = items

    print_dimension_report("D8: CONTEXT PRESSURE — BREAKPOINT ANALYSIS", all_results)

    # Breakpoint summary
    print("\n  BREAKPOINTS:")
    for label, items in all_results.items():
        for prefix in ["d8a-html", "d8a-quiz", "d8c"]:
            series = [(cid, p) for cid, p, *_ in items if cid.startswith(prefix)]
            bp_found = False
            for i, (cid, passed) in enumerate(series):
                if not passed:
                    prev = series[i - 1][0] if i > 0 else "(start)"
                    print(f"    {label} {prefix}: breaks at {cid} (last pass: {prev})")
                    bp_found = True
                    break
            if not bp_found:
                print(f"    {label} {prefix}: ALL PASS")
