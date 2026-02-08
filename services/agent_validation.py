from __future__ import annotations

import logging

from models.agent_output import FinalResult

logger = logging.getLogger(__name__)


class RetryNeeded(RuntimeError):
    pass


class SoftRetryNeeded(RuntimeError):
    pass


ARTIFACT_EVENT_TYPES = {
    'data-file-ready',
    'data-quiz-complete',
    'data-interactive-content',
    'data-pptx-outline',
}

ARTIFACT_TOOL_SET = {
    'generate_pptx', 'propose_pptx_outline', 'generate_docx', 'render_pdf',
    'generate_quiz_questions', 'request_interactive_content', 'generate_interactive_html',
}


def validate_terminal_state(
    result: FinalResult,
    emitted_events: set[str],
    called_tools: set[str],
    expected_mode: str,
) -> None:
    has_artifact_event = bool(emitted_events & ARTIFACT_EVENT_TYPES)
    has_artifact_tool = bool(called_tools & ARTIFACT_TOOL_SET)

    if result.status == 'artifact_ready':
        if not has_artifact_event and not has_artifact_tool:
            raise RetryNeeded('artifact_ready but no artifact event/tool call')
        if has_artifact_tool and not has_artifact_event:
            raise RetryNeeded('artifact tools were called but no artifact event emitted')

    if result.status == 'clarify_needed':
        if not result.clarify or not (result.clarify.question or '').strip():
            raise RetryNeeded('clarify_needed but clarify payload is empty')

        question = result.clarify.question.strip()
        if len(question) < 5:
            raise RetryNeeded(
                f'clarify question too short ({len(question)} chars): {question!r}'
            )

        # Reject generic template questions that lack specificity
        _generic_patterns = [
            '请补充更多信息',
            '请提供更多细节',
            'please provide more',
            'could you provide more',
            'can you give more',
        ]
        question_lower = question.lower()
        for pattern in _generic_patterns:
            if question_lower == pattern or (
                question_lower.startswith(pattern)
                and len(question) < len(pattern) + 10
            ):
                raise RetryNeeded(
                    f'clarify question is too generic: {question!r}'
                )

    if expected_mode == 'artifact' and result.status == 'answer_ready':
        if not has_artifact_event and not has_artifact_tool:
            logger.warning('Router expected artifact, agent returned answer_ready without artifacts; soft retry')
            raise SoftRetryNeeded('expected artifact but got answer-only result')
