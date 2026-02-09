"""Quiz tools exposed to Agent Path."""

from __future__ import annotations


async def generate_quiz_questions(
    topic: str,
    count: int = 10,
    difficulty: str = "medium",
    types: list[str] | None = None,
    subject: str = "",
    grade: str = "",
    context: str = "",
    weakness_focus: list[str] | None = None,
    model_name: str = "",
) -> dict:
    """Generate quiz questions as a tool-call result for Unified Agent mode.

    When running inside a :class:`ToolTracker`-wrapped context, each question
    is pushed as a ``stream-item`` event so the SSE layer can emit
    ``data-quiz-question`` events incrementally instead of waiting for
    the entire batch to complete.
    """
    from services.tool_tracker import ToolEvent, current_tracker
    from skills.quiz_skill import generate_quiz

    if types is None:
        types = ["SINGLE_CHOICE", "FILL_IN_BLANK"]
    if weakness_focus is None:
        weakness_focus = []

    tracker = current_tracker.get()

    questions: list[dict] = []
    async for question in generate_quiz(
        topic=topic,
        count=count,
        difficulty=difficulty,
        types=types,
        subject=subject,
        grade=grade,
        context=context,
        weakness_focus=weakness_focus,
        model_name=model_name,
    ):
        q_dict = question.model_dump(by_alias=True)
        questions.append(q_dict)

        # Push incremental quiz-question event for real-time SSE streaming
        if tracker is not None:
            await tracker.push(
                ToolEvent(
                    tool="generate_quiz_questions",
                    status="stream-item",
                    data={
                        "event": "quiz-question",
                        "index": len(questions) - 1,
                        "question": q_dict,
                        "status": "generated",
                    },
                )
            )

    return {
        "artifact_type": "quiz",
        "status": "ok",
        "questions": questions,
        "total": len(questions),
    }


async def refine_quiz_questions(
    questions: list[dict],
    instruction: str,
    action: str = "replace_one",
    target_index: int | None = None,
) -> dict:
    """Refine existing quiz questions.

    Args:
        questions: Existing quiz questions (list of QuizQuestionV1 dicts).
        instruction: User's natural-language refinement instruction.
        action: One of "replace_one", "regenerate_all", "clarify".
        target_index: 1-based question index for replace_one.
    """
    from models.quiz_output import QuizQuestionV1
    from skills.quiz_skill import generate_quiz, regenerate_question

    if not questions:
        return {"status": "error", "message": "No quiz questions available to refine."}

    normalized_action = (action or "").strip().lower()
    if normalized_action == "clarify":
        return {
            "status": "clarify",
            "message": (
                "请指定要修改的题号，例如“第3题太简单了，换一道”；"
                "或说“重新出题”来全部重做。"
            ),
        }

    if normalized_action == "replace_one":
        if target_index is None:
            return {"status": "clarify", "message": "请告诉我要改第几题。"}
        try:
            idx = int(target_index) - 1  # convert from 1-based to 0-based
        except (TypeError, ValueError):
            return {"status": "clarify", "message": "题号无法识别，请用数字说明，例如“第2题”。"}
        if idx < 0 or idx >= len(questions):
            return {
                "status": "clarify",
                "message": f"题号超出范围。目前共有 {len(questions)} 题。",
            }

        original = QuizQuestionV1(**questions[idx])
        replaced = await regenerate_question(original, feedback=instruction)
        replaced_dict = replaced.model_dump(by_alias=True)
        updated_questions = list(questions)
        updated_questions[idx] = replaced_dict
        return {
            "status": "replaced",
            "target_index": idx,
            "question": replaced_dict,
            "questions": updated_questions,
        }

    if normalized_action == "regenerate_all":
        count = len(questions)
        first = questions[0] if questions else {}
        topic = str(
            first.get("knowledgePoint")
            or first.get("knowledge_point")
            or first.get("question")
            or "General Quiz"
        )
        difficulty = str(first.get("difficulty") or "medium")
        existing_types = [
            str(q.get("questionType") or q.get("question_type") or "").strip()
            for q in questions
        ]
        types = [t for t in dict.fromkeys(existing_types) if t]
        if not types:
            types = ["SINGLE_CHOICE", "FILL_IN_BLANK"]

        regenerated: list[dict] = []
        async for q in generate_quiz(
            topic=topic,
            count=count,
            difficulty=difficulty,
            types=types,
            context=instruction,
        ):
            regenerated.append(q.model_dump(by_alias=True))

        return {
            "status": "regenerated",
            "questions": regenerated,
            "total": len(regenerated),
        }

    return {
        "status": "error",
        "message": f"Unsupported action: {action}",
    }
