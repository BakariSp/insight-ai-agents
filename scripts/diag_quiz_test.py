"""Diagnostic script: test quiz generation and capture [QUIZ-DIAG] logs."""
import asyncio
import logging
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Configure logging FIRST so all [QUIZ-DIAG] messages appear
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
# Ensure quiz_skill logger is at DEBUG for buffer diagnostics
logging.getLogger("skills.quiz_skill").setLevel(logging.DEBUG)

from skills.quiz_skill import generate_quiz  # noqa: E402


async def main():
    sys.stderr.write("=" * 60 + "\n")
    sys.stderr.write("QUIZ GENERATION DIAGNOSTIC TEST\n")
    sys.stderr.write("Requesting 10 questions: math calculus + linear algebra\n")
    sys.stderr.write("=" * 60 + "\n\n")

    questions = []
    try:
        async for q in generate_quiz(
            topic="calculus derivatives, linear algebra vectors",
            count=10,
            difficulty="medium",
            types=["SINGLE_CHOICE", "FILL_IN_BLANK"],
            subject="math",
            grade="university",
        ):
            questions.append(q)
            sys.stderr.write(
                f"  [OK] Q{q.order}: [{q.question_type.value}] "
                f"{q.question[:80]}...\n"
            )
    except Exception as e:
        sys.stderr.write(f"\n[ERROR] Generation stopped with exception: {e}\n")

    sys.stderr.write(f"\n{'=' * 60}\n")
    sys.stderr.write(f"RESULT: {len(questions)}/10 questions generated\n")
    sys.stderr.write(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
