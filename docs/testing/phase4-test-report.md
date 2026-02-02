# Phase 4.7 — 多 Agent 联调与端到端验证 测试报告

> 测试时间: 2026-02-02
> 运行环境: Python 3.14.2, pytest 9.0.2, Windows
> 测试结果: **151 passed, 0 failed** (16.76s)

---

## 1. 总体概览

Phase 4.7 作为 Phase 4 的收尾步骤，验证了统一会话网关的完整闭环：

- 所有 Response model 继承 `CamelModel`，序列化 `by_alias=True` ✅
- 初始流程联调：闲聊 → clarify 选项 → build_workflow → Blueprint ✅
- 追问流程联调：chat → refine → rebuild 全路径 ✅
- 现有端点向后兼容（`/api/workflow/generate`, `/api/health`）✅
- `POST /chat` 已标记 deprecated ✅

---

## 2. Phase 4 相关测试模块清单

| 测试文件 | 测试数 | 状态 | 覆盖范围 |
|----------|--------|------|---------|
| `test_conversation_models.py` | 13 | ✅ 全通过 | 意图枚举、RouterResult、ClarifyOptions、ConversationRequest/Response 序列化 |
| `test_router.py` | 13 | ✅ 全通过 | 置信度路由逻辑 + 初始/追问双模式意图分类 |
| `test_chat_agent.py` | 3 | ✅ 全通过 | 闲聊回复、QA 回复、不返回 JSON |
| `test_clarify_builder.py` | 8 | ✅ 全通过 | 选项生成（班级/时间/作业/科目/未知 hint） |
| `test_page_chat.py` | 7 | ✅ 全通过 | 页面上下文摘要、prompt 构建、Agent 回复 |
| `test_conversation_api.py` | 10 | ✅ 全通过 | 6 种 action 路径 + 错误处理 + clarify 多轮 |
| `test_e2e_conversation.py` | 5 | ✅ 全通过 | 完整闭环: 闲聊→生成, clarify→生成, 生成→追问→微调→重建 |
| **Phase 4 小计** | **59** | ✅ | — |

非 Phase 4 的已有测试（回归验证）:

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| `test_api.py` | 10 | ✅ 全通过 |
| `test_e2e_page.py` | 5 | ✅ 全通过 |
| `test_executor.py` | 16 | ✅ 全通过 |
| `test_llm_config.py` | 15 | ✅ 全通过 |
| `test_models.py` | 5 | ✅ 全通过 |
| `test_planner.py` | 5 | ✅ 全通过 |
| `test_provider.py` | 7 | ✅ 全通过 |
| `test_resolver.py` | 16 | ✅ 全通过 |
| `test_tools.py` | 13 | ✅ 全通过 |
| **已有测试小计** | **92** | ✅ |

**总计: 151 项测试全部通过**

---

## 3. 各模块测试详情

### 3.1 Conversation Models (`test_conversation_models.py` — 13 项)

验证 Phase 4.1 定义的意图模型和交互数据契约。

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_intent_type_values` | IntentType 枚举值: chat_smalltalk, chat_qa, build_workflow, clarify | ✅ |
| 2 | `test_followup_intent_type_values` | FollowupIntentType 枚举值: chat, refine, rebuild | ✅ |
| 3 | `test_router_result_camel_case` | RouterResult 序列化为 camelCase (shouldBuild, clarifyingQuestion, routeHint) | ✅ |
| 4 | `test_router_result_with_clarify` | RouterResult 含 clarifyingQuestion + routeHint 时正确赋值 | ✅ |
| 5 | `test_clarify_options_camel_case` | ClarifyOptions 序列化为 camelCase (allowCustomInput) | ✅ |
| 6 | `test_clarify_options_defaults` | ClarifyOptions 默认值: type=single_select, choices=[], allowCustomInput=True | ✅ |
| 7 | `test_conversation_request_minimal` | ConversationRequest 最小构造: 仅 message，其余为默认值 | ✅ |
| 8 | `test_conversation_request_camel_case` | ConversationRequest 序列化含 teacherId, conversationId, pageContext | ✅ |
| 9 | `test_conversation_request_from_camel` | 前端 camelCase JSON → ConversationRequest (teacherId → teacher_id) | ✅ |
| 10 | `test_conversation_response_chat` | ConversationResponse chat 回复: action + chatResponse，无 blueprint | ✅ |
| 11 | `test_conversation_response_build_workflow` | ConversationResponse build_workflow: action + chatResponse | ✅ |
| 12 | `test_conversation_response_clarify` | ConversationResponse clarify: action + clarifyOptions (含 choices) | ✅ |
| 13 | `test_conversation_response_all_actions` | 验证全部 7 种 action 均可设置 | ✅ |

### 3.2 RouterAgent (`test_router.py` — 13 项)

验证 Phase 4.2 的意图分类器和置信度路由策略。

**置信度路由单元测试 (6 项):**

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_confidence_high_build` | confidence ≥ 0.7 + build_workflow → should_build=True | ✅ |
| 2 | `test_confidence_medium_forces_clarify` | 0.4 ≤ confidence < 0.7 + build_workflow → 强制 clarify | ✅ |
| 3 | `test_confidence_medium_clarify_keeps_question` | 0.4 ≤ confidence < 0.7 + clarify 已有 question → 保留 question | ✅ |
| 4 | `test_confidence_low_forces_chat` | confidence < 0.4 + build_workflow → 降级为 chat_smalltalk | ✅ |
| 5 | `test_confidence_low_keeps_chat` | confidence < 0.4 + 已是 chat → 保持不变 | ✅ |
| 6 | `test_confidence_medium_chat_qa_passthrough` | 0.4 ≤ confidence < 0.7 + chat_qa → 不覆盖（透传） | ✅ |

**Agent 级测试 (7 项, 使用 PydanticAI TestModel):**

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 7 | `test_classify_smalltalk` | 问候消息 → chat_smalltalk, confidence ≥ 0.8 | ✅ |
| 8 | `test_classify_build_workflow` | 明确分析请求 → build_workflow, confidence ≥ 0.7 | ✅ |
| 9 | `test_classify_clarify` | 模糊请求 → clarify + clarifyingQuestion + routeHint | ✅ |
| 10 | `test_classify_intent_initial_mode` | 初始模式 (无 blueprint) → chat_qa 分类 | ✅ |
| 11 | `test_classify_intent_followup_mode` | 追问模式 (有 blueprint) → followup chat 分类 | ✅ |
| 12 | `test_followup_refine` | 追问模式 → refine, should_build=True | ✅ |
| 13 | `test_followup_rebuild` | 追问模式 → rebuild, should_build=True | ✅ |

### 3.3 ChatAgent (`test_chat_agent.py` — 3 项)

验证 Phase 4.3 的闲聊和知识问答处理。

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_chat_smalltalk_response` | 闲聊输入 → 返回非空文本 | ✅ |
| 2 | `test_chat_qa_response` | QA 输入 (KPI 是什么) → 返回非空文本 | ✅ |
| 3 | `test_chat_does_not_return_json` | 回复不以 `{` 或 `[` 开头（非 JSON） | ✅ |

### 3.4 Clarify Builder (`test_clarify_builder.py` — 8 项)

验证 Phase 4.4 的交互式反问选项构建。

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_build_class_choices` | needClassId → 获取班级列表（2 个: Form 1A, Form 1B） | ✅ |
| 2 | `test_build_class_choices_unknown_teacher` | 未知 teacher → 空 choices，允许自定义输入 | ✅ |
| 3 | `test_build_time_range_choices` | needTimeRange → 3 个预设选项 (this_week/this_month/this_semester) | ✅ |
| 4 | `test_build_assignment_choices` | needAssignment → 空 choices（缺 class_id），允许自定义输入 | ✅ |
| 5 | `test_build_subject_choices` | needSubject → 4 个科目选项 (english/math/...) | ✅ |
| 6 | `test_unknown_route_hint` | 未知 hint → 空 choices，允许自定义输入 | ✅ |
| 7 | `test_none_route_hint` | None hint → 空 choices，允许自定义输入 | ✅ |
| 8 | `test_clarify_options_camel_case_output` | ClarifyOptions 序列化为 camelCase (allowCustomInput) | ✅ |

### 3.5 PageChatAgent (`test_page_chat.py` — 7 项)

验证 Phase 4.5 的页面追问对话。

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_summarize_empty_context` | 空/None 上下文 → "No page data available." | ✅ |
| 2 | `test_summarize_dict_values` | dict 上下文 → 正确提取 stats/title | ✅ |
| 3 | `test_summarize_list_values` | list 上下文 → "2 items" 摘要 | ✅ |
| 4 | `test_build_page_chat_prompt_injects_context` | prompt 注入 blueprint 名称/描述/页面摘要 | ✅ |
| 5 | `test_build_page_chat_prompt_defaults` | 默认 prompt 含 "Unknown" / "No description" | ✅ |
| 6 | `test_page_chat_agent_response` | Agent 基于页面上下文返回文本回复 | ✅ |
| 7 | `test_page_chat_agent_no_json` | 回复不以 `{` 开头（非 JSON） | ✅ |

### 3.6 Conversation API (`test_conversation_api.py` — 10 项)

验证 Phase 4.6 的统一会话端点 `POST /api/conversation`。

**初始模式 (4 项):**

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_conversation_smalltalk` | 闲聊 → action=chat_smalltalk, chatResponse 有值, blueprint=null | ✅ |
| 2 | `test_conversation_chat_qa` | QA → action=chat_qa, chatResponse 含 "KPI" | ✅ |
| 3 | `test_conversation_build_workflow` | 明确请求 → action=build_workflow, blueprint 有值 | ✅ |
| 4 | `test_conversation_clarify` | 模糊请求 → action=clarify, clarifyOptions 含 2 个 choices | ✅ |

**追问模式 (3 项):**

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 5 | `test_conversation_followup_chat` | 页面追问 → action=chat, chatResponse 含数据 | ✅ |
| 6 | `test_conversation_followup_refine` | 微调请求 → action=refine, blueprint 有值 | ✅ |
| 7 | `test_conversation_followup_rebuild` | 重建请求 → action=rebuild, blueprint 有值 | ✅ |

**错误处理与多轮 (3 项):**

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 8 | `test_conversation_missing_message` | 缺少 message → HTTP 422 | ✅ |
| 9 | `test_conversation_agent_error` | Agent 异常 → HTTP 502, "Conversation processing failed" | ✅ |
| 10 | `test_conversation_clarify_then_build` | clarify 多轮: 用户补充 context → build_workflow | ✅ |

### 3.7 E2E Conversation (`test_e2e_conversation.py` — 5 项)

验证 Phase 4.7 的完整闭环联调。

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_e2e_smalltalk_to_build` | 闲聊(chat_smalltalk) → 分析请求(build_workflow) → Blueprint | ✅ |
| 2 | `test_e2e_clarify_to_build` | 模糊请求(clarify) → 用户选择班级(context) → build_workflow → Blueprint | ✅ |
| 3 | `test_e2e_build_then_followup` | 生成页面 → 追问(chat) → 微调(refine) → 重建(rebuild) 全路径 | ✅ |
| 4 | `test_e2e_response_camel_case` | 所有响应字段为 camelCase，无 snake_case 泄漏 | ✅ |
| 5 | `test_e2e_existing_endpoints_still_work` | 现有端点兼容: /api/health + /api/workflow/generate | ✅ |

---

## 4. 回归测试结果

Phase 1-3 的 92 项已有测试全部通过，Phase 4 的改动未引入任何回归问题:

| 模块 | 测试数 | 结果 |
|------|--------|------|
| API 端点 (test_api.py) | 10 | ✅ |
| E2E 页面 (test_e2e_page.py) | 5 | ✅ |
| ExecutorAgent (test_executor.py) | 16 | ✅ |
| LLM 配置 (test_llm_config.py) | 15 | ✅ |
| Blueprint 模型 (test_models.py) | 5 | ✅ |
| PlannerAgent (test_planner.py) | 5 | ✅ |
| Provider (test_provider.py) | 7 | ✅ |
| Resolver (test_resolver.py) | 16 | ✅ |
| Tools (test_tools.py) | 13 | ✅ |

---

## 5. 测试覆盖的关键场景

### 5.1 意图路由 (7 种 action)

| action | 模式 | 测试覆盖 |
|--------|------|---------|
| `chat_smalltalk` | 初始 | conversation_api #1, e2e #1, router #7 |
| `chat_qa` | 初始 | conversation_api #2, router #10 |
| `build_workflow` | 初始 | conversation_api #3, e2e #1 #2, router #8 |
| `clarify` | 初始 | conversation_api #4, e2e #2, router #9 |
| `chat` | 追问 | conversation_api #5, e2e #3, router #11 |
| `refine` | 追问 | conversation_api #6, e2e #3, router #12 |
| `rebuild` | 追问 | conversation_api #7, e2e #3, router #13 |

### 5.2 置信度路由边界

| confidence 区间 | 路由行为 | 测试覆盖 |
|----------------|---------|---------|
| `≥ 0.7` | 直接 build_workflow | router #1 |
| `0.4 ~ 0.7` | 强制 clarify | router #2, #3 |
| `< 0.4` | 降级为 chat | router #4, #5 |
| `0.4 ~ 0.7` + chat_qa | 透传不覆盖 | router #6 |

### 5.3 完整闭环流程

1. **闲聊 → 生成** (`test_e2e_smalltalk_to_build`):
   - Round 1: "你好" → chat_smalltalk → 友好回复
   - Round 2: "分析 1A 班英语成绩" → build_workflow → Blueprint

2. **反问 → 生成** (`test_e2e_clarify_to_build`):
   - Round 1: "分析英语表现" → clarify → 班级选项列表 (2 个)
   - Round 2: 用户选择 classId → build_workflow → Blueprint

3. **生成 → 追问 → 微调 → 重建** (`test_e2e_build_then_followup`):
   - Round 1: 追问 "哪些学生需要关注？" → chat → 基于数据回复
   - Round 2: "只显示不及格的学生" → refine → 新 Blueprint
   - Round 3: "加一个语法分析板块" → rebuild → 新 Blueprint

---

## 6. Warnings 说明

运行过程中产生 15 个 `DeprecationWarning`，均来自 `litellm` 第三方依赖:

```
litellm/litellm_core_utils/logging_utils.py:273: DeprecationWarning:
'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16;
use inspect.iscoroutinefunction() instead
```

此为 litellm 库内部代码使用了已弃用的 `asyncio.iscoroutinefunction`，不影响功能，需等待 litellm 上游修复。

---

## 7. 结论

Phase 4.7 联调验证 **全部通过**。统一会话网关 `POST /api/conversation` 可正确处理:

- 4 种初始模式意图 (chat_smalltalk / chat_qa / build_workflow / clarify)
- 3 种追问模式意图 (chat / refine / rebuild)
- 置信度路由策略 (≥0.7 直接执行 / 0.4~0.7 反问 / <0.4 闲聊)
- Clarify 多轮交互 (反问 → 用户选择 → 重新分类)
- camelCase 序列化（前端零适配）
- 错误处理 (422 参数校验 / 502 Agent 异常)
- 向后兼容 (旧端点正常工作)

Phase 4 **全部完成**，可进入 Phase 5（Java 后端对接）。
