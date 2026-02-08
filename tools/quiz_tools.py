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
) -> dict:
    """Generate quiz questions as a tool-call result for Unified Agent mode."""
    from skills.quiz_skill import generate_quiz

    if types is None:
        types = ["SINGLE_CHOICE", "FILL_IN_BLANK"]
    if weakness_focus is None:
        weakness_focus = []

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
    ):
        questions.append(question.model_dump(by_alias=True))

    return {
        "questions": questions,
        "total": len(questions),
    }
