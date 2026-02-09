"""Quiz generation skill — fast path for question generation.

Single LLM call, streaming parse: yields one QuizQuestionV1 as soon as a
complete question JSON object is extracted from the LLM output buffer.

This replaces the Blueprint -> Executor -> QuestionPipeline path for simple
quiz-generation requests, reducing latency from ~100s to ~5-12s.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import AsyncGenerator

from agents.provider import create_model
from config.settings import get_settings
from models.quiz_output import QuestionTypeV1, QuizQuestionV1

logger = logging.getLogger(__name__)


# ── Quiz generation prompt builder ───────────────────────────


def _build_quiz_prompt(
    topic: str,
    count: int,
    difficulty: str,
    types: list[str],
    subject: str,
    grade: str,
    context: str,
    weakness_focus: list[str],
) -> str:
    """Build the quiz generation prompt — all logic in prompt engineering."""
    type_desc = ", ".join(types)

    sections = [
        f"[重要] 你必须生成恰好 {count} 道题目。不能少于 {count} 道。JSON 数组格式输出。",
        f"学科: {subject}" if subject else "",
        f"年级: {grade}" if grade else "",
        f"知识点/主题: {topic}" if topic else "",
        f"题型要求: {type_desc}",
        f"难度: {difficulty}",
    ]

    if weakness_focus:
        sections.append(f"重点关注学生薄弱点: {', '.join(weakness_focus)}")

    if context:
        sections.append(f"\n参考材料:\n{context}")

    sections.append(f"""
每道题的 JSON 格式:
{{
  "questionType": "SINGLE_CHOICE|FILL_IN_BLANK|TRUE_FALSE|SHORT_ANSWER",
  "question": "题目文本",
  "options": ["选项内容（不要带字母前缀）", "选项内容", "选项内容", "选项内容"],
  "correctAnswer": "B",
  "explanation": "解析",
  "difficulty": "easy|medium|hard",
  "knowledgePoint": "知识点名称",
  "points": 1
}}

要求:
1. 题目质量要高——清晰、无歧义、答案唯一
2. 难度分布: 简单30% / 中等50% / 困难20%
3. 直接输出 JSON 数组，不要任何其他文字
4. 选择题必须有 options 字段（4个选项），correctAnswer 是选项字母
5. 填空题不需要 options，correctAnswer 是答案文本
6. 判断题 options 为 ["对", "错"]，correctAnswer 为 A 或 B
7. **选项内容不要带字母前缀**（不要写 "A. xxx"，直接写 "xxx"），前端会自动添加字母标签
8. **数学公式必须用 LaTeX 格式**：行内公式用 $...$ 包裹（如 $\\frac{{1}}{{2}}$、$x^2 + 1$），不要用纯文本写数学表达式
9. 题目和选项中的数学符号一律用 LaTeX（积分 $\\int$、求导 $\\frac{{dy}}{{dx}}$、极限 $\\lim$、根号 $\\sqrt{{}}$ 等）
10. **纯数字不要用 LaTeX 包裹**：选项如果只是数字（如 0.8、100、3.14），直接写数字即可，不要写成 $0.8$。只有包含运算符、变量或数学命令的表达式才需要 $...$（如 $2x+1$、$\\frac{{1}}{{3}}$）

[再次强调] 你必须输出恰好 {count} 道题目的 JSON 数组。从第1道写到第{count}道，缺少任何一道都不合格。""")

    return "\n".join(s for s in sections if s)


# ── Streaming JSON parser ─────────────────────────────────────


def _fix_invalid_json_escapes(s: str) -> str:
    r"""Fix invalid JSON escape sequences produced by LLMs.

    LLMs frequently emit LaTeX notation like ``\(x^2\)`` or ``\frac{}{}``
    inside JSON strings.  These are invalid JSON escapes (only ``\"``,
    ``\\``, ``\/``, ``\b``, ``\f``, ``\n``, ``\r``, ``\t``, ``\uXXXX``
    are legal).  Replace lone backslashes before non-escape characters
    with double-backslashes so ``json.loads`` succeeds.

    Special handling: ``\f``, ``\b``, ``\n``, ``\r``, ``\t`` are valid
    JSON escapes, but LLMs use them as LaTeX prefixes (``\frac``,
    ``\begin``, ``\not``, ``\right``, ``\text``).  When followed by
    2+ letters, these are LaTeX commands, not JSON control characters.
    """
    # Step 0: Protect valid \\ (JSON literal backslash) from being split
    # by subsequent regex steps.  Without this, Step 1 matches the second
    # backslash of \\ when followed by a non-escape char (e.g. "\\ 4" → "\\\ 4").
    _PH = "\x00\x01"
    s = s.replace("\\\\", _PH)

    # Step 1: Fix obvious non-JSON escapes (e.g. \s, \l, \i, \(, \), \x)
    s = re.sub(
        r'\\(?!["\\/bfnrtu])',
        r"\\\\",
        s,
    )
    # Step 2: Fix LaTeX commands that START with valid JSON escape letters.
    # \frac, \forall, \flat → \f + alpha  (not form-feed)
    # \begin, \bar, \bmod   → \b + alpha  (not backspace)
    # \not, \nu, \nabla     → \n + alpha  (not newline)
    # \right, \rangle, \rho → \r + alpha  (not carriage-return)
    # \text, \theta, \times → \t + alpha  (not tab)
    # Pattern: \X followed by at least 2 ASCII letters → must be LaTeX
    s = re.sub(
        r'\\([bfnrt])([a-zA-Z]{2,})',
        r'\\\\' + r'\1\2',
        s,
    )

    # Step 3: Restore protected \\ sequences
    s = s.replace(_PH, "\\\\")
    return s


def _try_extract_question(buffer: str) -> tuple[dict | None, str]:
    """Try to extract a complete JSON object from the buffer.

    Scans for balanced ``{ ... }`` blocks inside the buffer.
    Returns ``(parsed_dict, remaining_buffer)`` or ``(None, buffer)``.
    """
    # Find the first '{' in the buffer
    start = buffer.find("{")
    if start == -1:
        return None, buffer

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(buffer)):
        ch = buffer[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # Found a complete JSON object
                json_str = buffer[start : i + 1]
                try:
                    obj = json.loads(json_str)
                    return obj, buffer[i + 1 :]
                except json.JSONDecodeError:
                    pass
                # Retry with invalid escape fix (LLM LaTeX like \( \))
                try:
                    obj = json.loads(_fix_invalid_json_escapes(json_str))
                    return obj, buffer[i + 1 :]
                except json.JSONDecodeError as e2:
                    # Truly malformed — skip this block and continue
                    logger.warning(
                        "Dropped malformed JSON block (len=%d, err=%s). "
                        "Content: %s",
                        len(json_str), e2, repr(json_str[:500]),
                    )
                    return None, buffer[i + 1 :]

    # No complete object found yet
    return None, buffer


def _parse_to_v1(raw: dict, order: int) -> QuizQuestionV1:
    """Convert a raw LLM-generated question dict to QuizQuestionV1."""
    q_type_raw = raw.get("questionType", "SHORT_ANSWER")

    # Normalise type to V1 enum
    q_type_upper = q_type_raw.upper().replace(" ", "_")
    try:
        q_type = QuestionTypeV1(q_type_upper)
    except ValueError:
        logger.warning("Unknown question type '%s', falling back to SHORT_ANSWER", q_type_raw)
        q_type = QuestionTypeV1.SHORT_ANSWER

    # Build options list
    options = raw.get("options")

    # Correct answer
    correct_answer = raw.get("correctAnswer", raw.get("correct_answer"))

    return QuizQuestionV1(
        id=raw.get("id", f"q-{order:03d}"),
        order=order,
        question_type=q_type,
        question=raw.get("question", raw.get("stem", "")),
        options=options,
        correct_answer=correct_answer,
        explanation=raw.get("explanation", ""),
        difficulty=raw.get("difficulty", "medium"),
        points=float(raw.get("points", 1.0)),
        knowledge_point=raw.get("knowledgePoint", raw.get("knowledge_point")),
    )


# ── Core skill: generate_quiz ─────────────────────────────────


async def generate_quiz(
    topic: str,
    count: int = 10,
    difficulty: str = "medium",
    types: list[str] | None = None,
    subject: str = "",
    grade: str = "",
    context: str = "",
    weakness_focus: list[str] | None = None,
    model_name: str | None = None,
) -> AsyncGenerator[QuizQuestionV1, None]:
    """Stream-generate quiz questions — single LLM call, one question per yield.

    Yields each :class:`QuizQuestionV1` as soon as the streaming LLM output
    contains a complete JSON object.
    """
    if types is None:
        types = ["SINGLE_CHOICE", "FILL_IN_BLANK"]
    if weakness_focus is None:
        weakness_focus = []

    prompt = _build_quiz_prompt(
        topic=topic,
        count=count,
        difficulty=difficulty,
        types=types,
        subject=subject,
        grade=grade,
        context=context,
        weakness_focus=weakness_focus,
    )

    settings = get_settings()
    selected_model = (model_name or "").strip() or settings.executor_model
    model = create_model(selected_model)

    # Use PydanticAI Agent for streaming
    from pydantic_ai import Agent

    agent = Agent(
        model=model,
        output_type=str,
        system_prompt=(
            "You are a professional quiz question generator. "
            "Output ONLY a JSON array containing EXACTLY the requested number of questions. "
            "Never stop early. Always generate all questions requested."
        ),
        retries=1,
        defer_model_check=True,
    )

    buffer = ""
    question_count = 0
    _dropped_count = 0

    logger.info(
        "Quiz generation starting: requested=%d, topic='%s', model=%s",
        count,
        topic,
        selected_model,
    )

    async with agent.run_stream(prompt) as stream:
        async for chunk in stream.stream_text(delta=True):
            buffer += chunk

            # Try to extract complete question objects from buffer
            while True:
                question_json, remaining = _try_extract_question(buffer)
                if question_json is None:
                    # A malformed block was skipped — keep trying
                    if remaining != buffer:
                        _dropped_count += 1
                        buffer = remaining
                        continue
                    break

                buffer = remaining
                question_count += 1

                try:
                    v1_question = _parse_to_v1(question_json, order=question_count)
                    yield v1_question
                except Exception as e:
                    logger.warning("Failed to parse question %d: %s", question_count, e)

    # Handle any remaining content in buffer after stream ends
    if buffer.strip():
        while True:
            question_json, remaining = _try_extract_question(buffer)
            if question_json is None:
                break
            buffer = remaining
            question_count += 1
            try:
                v1_question = _parse_to_v1(question_json, order=question_count)
                yield v1_question
            except Exception as e:
                logger.warning("Failed to parse trailing question: %s", e)

    if question_count < count:
        logger.warning(
            "Quiz generation count mismatch: requested=%d, yielded=%d, dropped=%d",
            count, question_count, _dropped_count,
        )


# ── Skill: regenerate_question ────────────────────────────────


async def regenerate_question(
    original_question: QuizQuestionV1,
    feedback: str = "",
    keep_difficulty: bool = True,
    keep_knowledge_point: bool = True,
) -> QuizQuestionV1:
    """Replace a single question while preserving knowledge point and difficulty."""
    constraints = []
    if keep_difficulty:
        constraints.append(f"难度保持: {original_question.difficulty}")
    if keep_knowledge_point and original_question.knowledge_point:
        constraints.append(f"知识点保持: {original_question.knowledge_point}")

    prompt = f"""替换以下题目，生成一道新题。输出单个 JSON 对象（不要数组）。

原题:
{json.dumps(original_question.model_dump(by_alias=True), ensure_ascii=False, indent=2)}

{f'教师反馈: {feedback}' if feedback else ''}
{chr(10).join(constraints)}

要求:
1. 与原题不同但考察相同知识点
2. 输出格式与原题相同（单个 JSON 对象）
3. 不要输出任何其他文字
4. 选项不要带字母前缀（不要写 "A. xxx"）
5. 数学公式用 LaTeX 格式：行内用 $...$ 包裹
6. 纯数字选项（如 0.8、100）不要用 $...$ 包裹，只有含变量或运算符的表达式才需要 LaTeX
"""

    settings = get_settings()
    model = create_model(settings.executor_model)

    from pydantic_ai import Agent

    agent = Agent(
        model=model,
        output_type=str,
        system_prompt="You are a quiz question generator. Output ONLY a single JSON object.",
        retries=1,
        defer_model_check=True,
    )

    result = await agent.run(prompt)
    raw_text = result.output

    # Extract JSON from response
    question_json, _ = _try_extract_question(raw_text)
    if question_json is None:
        raise ValueError(f"Failed to parse regenerated question from LLM output: {raw_text[:200]}")

    return _parse_to_v1(question_json, order=original_question.order)


# ── Helper: build intro text ──────────────────────────────────


def build_quiz_intro(params: dict, language: str = "zh") -> str:
    """Build a friendly intro message before quiz generation starts."""
    topic = params.get("topic", "")
    count = params.get("count", 10)
    difficulty = params.get("difficulty", "中等")

    difficulty_map = {
        "easy": "简单", "medium": "中等", "hard": "困难",
        "简单": "简单", "中等": "中等", "困难": "困难",
    }
    diff_display = difficulty_map.get(difficulty, difficulty)

    if language.startswith("zh") or any("\u4e00" <= ch <= "\u9fff" for ch in topic[:10]):
        return f"好的，正在为你生成 {count} 道关于「{topic}」的题目（{diff_display}难度）..."
    return f"Generating {count} questions on '{topic}' ({difficulty} difficulty)..."
