"""Blueprint distillation service.

Converts conversation history into a reusable Soft Blueprint via LLM extraction.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic_ai import Agent

from agents.provider import create_model
from config.llm_config import LLMConfig
from models.soft_blueprint import SoftBlueprint
from services.conversation_store import get_conversation_store

logger = logging.getLogger(__name__)

# Distillation LLM config — low temperature for consistency
DISTILL_LLM_CONFIG = LLMConfig(temperature=0.2, max_tokens=8192)

# Module-level agent
_distill_agent = Agent(
    model=create_model(),
    output_type=SoftBlueprint,
    retries=2,  # Up to 3 attempts total
    defer_model_check=True,
)


def _build_distill_prompt(conversation_history: list[dict[str, Any]]) -> str:
    """
    Build distillation prompt from conversation history.

    Args:
        conversation_history: List of messages with role, content, tool_calls_summary

    Returns:
        Formatted prompt for distillation
    """
    # Format conversation
    conv_lines = []
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_summary = msg.get("tool_calls_summary", "")

        if role == "user":
            conv_lines.append(f"Teacher: {content}")
        elif role == "assistant":
            if tool_summary:
                conv_lines.append(f"AI: [Tools used: {tool_summary}]")
            if content:
                # Truncate long assistant messages
                truncated = content[:500] + "..." if len(content) > 500 else content
                conv_lines.append(f"AI: {truncated}")

    conversation_text = "\n".join(conv_lines)

    prompt = f"""你是一个 Blueprint 蒸馏器。阅读以下教师与 AI 的对话历史，提取一个可复用的 Soft Blueprint。

## 规则

1. entity_slots: 识别对话中的可替换参数
   - 班级/学生/作业 → 对应的 selector type
   - 如果某个参数在对话中是固定的但逻辑上应该可变，也要提取

2. execution_prompt: 写一段精炼的可复用指令
   - 用 {{{{slot_key}}}} 作为占位符 (例如 {{{{class_name}}}}, {{{{assignment_name}}}})
   - 包含输出结构的参考（模仿教师满意的那次输出）
   - 不要包含具体班级/学生名字，用占位符代替

3. output_hints: 从最终输出中提取结构
   - expected_artifacts: 识别对话中产生了哪些 artifact 类型
     枚举: "report" (分析报告/文本), "quiz" (题目生成), "interactive" (互动网页), "document" (文档/PPT)
   - tabs: 仅当 expected_artifacts 含 "report" 时提取 tab 划分
   - preferred_components 从以下枚举中选择:
     kpi_grid, chart, table, ai_narrative, suggestion_list, question_generator, quiz_list, interactive_content

4. 多 artifact 对话处理:
   - 如果对话中 AI 调用了多个生成工具 (如 出题 + 生成互动网页),
     execution_prompt 应描述完整的流水线意图
   - expected_artifacts 按执行顺序列出所有 artifact 类型
   - 不要把 artifact 的原始内容 (题目JSON/HTML代码) 写入 prompt, 只描述"生成什么"

## 对话历史

{conversation_text}

---

现在输出 JSON，schema 如下:
{{{{
  "name": "string — 简洁的模板名称",
  "description": "string — 一句话描述",
  "icon": "string — chart|quiz|file-text|lightbulb|book|globe",
  "tags": ["string"],
  "entity_slots": [
    {{{{"key": "string", "label": "string", "type": "string", "required": bool, "depends_on": "string|null"}}}}
  ],
  "execution_prompt": "string — 含占位符的指令模板",
  "output_hints": {{{{
    "expected_artifacts": ["string — report|quiz|interactive|document"],
    "tabs": [{{{{"key": "string", "label": "string", "description": "string"}}}}] | null,
    "preferred_components": ["string"]
  }}}}
}}}}
"""
    return prompt


def _validate_blueprint(blueprint: SoftBlueprint) -> None:
    """
    Validate distilled blueprint.

    Raises:
        ValueError: If validation fails
    """
    # Check entity_slots not empty
    if not blueprint.entity_slots:
        raise ValueError("entity_slots cannot be empty")

    # Check placeholder consistency
    placeholders_in_prompt = set(re.findall(r"\{(\w+)\}", blueprint.execution_prompt))
    slot_keys = {slot.key for slot in blueprint.entity_slots}

    # Allow both {key} and {key_name} patterns
    expected_placeholders = set()
    for key in slot_keys:
        expected_placeholders.add(key)
        expected_placeholders.add(f"{key}_name")

    if not placeholders_in_prompt.issubset(expected_placeholders):
        logger.warning(
            "Placeholder mismatch: prompt has %s, slots have %s",
            placeholders_in_prompt,
            slot_keys,
        )

    # Check for system prompt injection
    dangerous_patterns = ["system:", "<system>", "[SYSTEM]", "ignore previous"]
    prompt_lower = blueprint.execution_prompt.lower()
    for pattern in dangerous_patterns:
        if pattern in prompt_lower:
            raise ValueError(f"Potential prompt injection detected: '{pattern}'")

    # Check length
    if len(blueprint.execution_prompt) > 5000:
        raise ValueError("execution_prompt too long (max 5000 chars)")


async def distill_conversation(
    teacher_id: str,
    conversation_id: str,
    language: str = "zh",
) -> SoftBlueprint:
    """
    Distill a conversation into a Soft Blueprint.

    Args:
        teacher_id: Teacher ID
        conversation_id: Source conversation ID
        language: Language code (default: "zh")

    Returns:
        SoftBlueprint object

    Raises:
        ValueError: If conversation not found or validation fails
        RuntimeError: If distillation fails after retries
    """
    # Get conversation from store
    store = get_conversation_store()
    session = await store.get(conversation_id)

    if not session:
        raise ValueError(f"Conversation not found or expired: {conversation_id}")

    # Build conversation history from turns
    conversation_history = []
    for turn in session.turns:
        msg_dict = {
            "role": turn.role,
            "content": turn.content,
        }
        if turn.tool_calls_summary:
            msg_dict["tool_calls_summary"] = turn.tool_calls_summary
        conversation_history.append(msg_dict)

    if not conversation_history:
        raise ValueError("Conversation history is empty")

    # Build prompt
    distill_prompt = _build_distill_prompt(conversation_history)

    logger.info("Distilling conversation %s for teacher %s", conversation_id, teacher_id)

    # Run agent with retries (handled by PydanticAI)
    try:
        result = await _distill_agent.run(
            distill_prompt,
            model_settings=DISTILL_LLM_CONFIG.to_litellm_kwargs(),
        )

        blueprint: SoftBlueprint = result.output

        # Post-processing
        blueprint.source_conversation_id = conversation_id

        # Validation
        _validate_blueprint(blueprint)

        logger.info(
            "Distillation successful: %s (%d slots)", blueprint.name, len(blueprint.entity_slots)
        )

        return blueprint

    except Exception as e:
        logger.exception("Distillation failed for conversation %s", conversation_id)
        raise RuntimeError(f"Failed to distill blueprint: {str(e)}") from e
