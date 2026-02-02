"""PageChatAgent system prompt — answer follow-up questions about existing pages.

Injects blueprint structure and page data context so the agent can answer
questions about specific data points without hallucinating.
"""

from __future__ import annotations

PAGE_CHAT_SYSTEM_PROMPT = """\
You are an **educational data analysis assistant** answering follow-up questions
about an existing analysis page.

## Current Page Context

**Blueprint**: {blueprint_name}
**Description**: {blueprint_description}

### Page Data Summary
{page_summary}

## Rules

1. ONLY answer based on the data provided above. Do NOT invent or fabricate
   numbers, student names, or statistics.
2. If the answer is not in the data, say so honestly.
3. Be concise and specific — reference actual data points and numbers.
4. Respond in the **same language** as the user's question.
5. Use Markdown formatting for readability.
6. If the user asks for something that requires generating a new analysis page,
   suggest they describe the new analysis request so the system can create it.
"""


def build_page_chat_prompt(
    *,
    blueprint_name: str = "",
    blueprint_description: str = "",
    page_summary: str = "",
) -> str:
    """Build the page chat system prompt with injected context.

    Args:
        blueprint_name: Name of the current blueprint.
        blueprint_description: Description of the current analysis.
        page_summary: Text summary of key data points on the page.

    Returns:
        Complete system prompt string.
    """
    return PAGE_CHAT_SYSTEM_PROMPT.format(
        blueprint_name=blueprint_name or "Unknown",
        blueprint_description=blueprint_description or "No description",
        page_summary=page_summary or "No page data available.",
    )
