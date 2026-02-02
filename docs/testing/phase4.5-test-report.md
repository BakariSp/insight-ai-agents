# Phase 4.5 — 健壮性增强 + 数据契约升级 测试报告

> 测试时间: 2026-02-03
> 运行环境: Python 3.14.2, pytest 9.0.2, Windows
> 测试结果: **230 passed, 0 failed**
> Live 测试: 14/15 PASS (1 timeout), 详见 [phase4.5-conversation-log.md](phase4.5-conversation-log.md)

---

## 1. 总体概览

Phase 4.5 共 4 个步骤，全面提升系统健壮性:

- **Step 4.5.1**: 通用实体解析层（Entity Resolver）— 确定性 class/student/assignment 解析
- **Step 4.5.2**: sourcePrompt 一致性校验 — 防止 LLM 篡改用户原始请求
- **Step 4.5.3**: Action 命名统一化 — `mode` + `action` + `chatKind` 三维结构
- **Step 4.5.4**: Executor 数据阶段错误拦截 — DATA_ERROR SSE 事件

### Step 4.5.1 核心能力:
- **班级解析**: regex 四层匹配（精确 → 别名 → 年级展开 → 模糊）
- **学生解析**: 关键词触发 + 姓名匹配，依赖班级上下文
- **作业解析**: 关键词触发 + 标题匹配，依赖班级上下文
- **依赖链管理**: 学生/作业解析依赖 class context，缺失时返回 `missing_context`
- **API 集成**: 高置信度自动注入 context，歧义/缺失时降级为 clarify

---

## 2. Phase 4.5.1 测试模块清单

| 测试文件 | 测试数 | 状态 | 覆盖范围 |
|----------|--------|------|---------|
| `test_entity_resolver.py` | 28 | ✅ 全通过 | 班级/学生/作业解析 + 混合实体 + 向下兼容 + 序列化 |
| `test_conversation_models.py` | 15 | ✅ 全通过 | 意图枚举 + RouterResult + ClarifyOptions + ConversationRequest/Response + resolvedEntities |
| `test_conversation_api.py` | 14 | ✅ 全通过 | 7 种 action + 错误处理 + clarify 多轮 + 实体解析集成 |
| **Phase 4.5.1 小计** | **57** | ✅ | — |

### Step 4.5.2–4.5.4 新增测试

| 测试文件 | 新增测试数 | 状态 | 覆盖范围 |
|----------|-----------|------|---------|
| `test_planner.py` | +3 | ✅ | sourcePrompt 强制覆写 + LLM 篡改检测 |
| `test_conversation_models.py` | +2 | ✅ | legacyAction 计算 + mode/action/chatKind 结构 |
| `test_conversation_api.py` | +2 | ✅ | _verify_source_prompt 防御 |
| `test_executor.py` | +4 | ✅ | DATA_ERROR SSE + DataFetchError + 异常属性 |
| **Phase 4.5.2–4.5.4 小计** | **+8 → 共 230** | ✅ | — |

非 Phase 4.5 的已有测试（回归验证）:

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| `test_adapters.py` | 15 | ✅ 全通过 |
| `test_api.py` | 10 | ✅ 全通过 |
| `test_chat_agent.py` | 3 | ✅ 全通过 |
| `test_clarify_builder.py` | 8 | ✅ 全通过 |
| `test_e2e_conversation.py` | 5 | ✅ 全通过 |
| `test_e2e_page.py` | 5 | ✅ 全通过 |
| `test_executor.py` | 16 | ✅ 全通过 |
| `test_java_client.py` | 16 | ✅ 全通过 |
| `test_llm_config.py` | 15 | ✅ 全通过 |
| `test_models.py` | 5 | ✅ 全通过 |
| `test_page_chat.py` | 7 | ✅ 全通过 |
| `test_planner.py` | 5 | ✅ 全通过 |
| `test_provider.py` | 7 | ✅ 全通过 |
| `test_resolver.py` | 16 | ✅ 全通过 |
| `test_router.py` | 13 | ✅ 全通过 |
| `test_tools.py` | 13 | ✅ 全通过 |
| **已有测试小计** | **165** | ✅ |

**总计: 230 项测试全部通过** (Phase 4.5.1: 57 + Phase 4.5.2–4.5.4: 8 + 回归: 165)

---

## 3. 各模块测试详情

### 3.1 班级解析 (Class Resolution — 13 项)

| # | 测试名 | 输入 | 预期结果 | 结果 |
|---|--------|------|---------|------|
| 1 | `test_exact_match_form_1a` | `"分析 Form 1A 英语成绩"` | scope=single, id=class-hk-f1a, confidence=1.0, match=exact | ✅ |
| 2 | `test_exact_match_case_insensitive` | `"分析 form 1a 成绩"` | scope=single, id=class-hk-f1a (大小写不敏感) | ✅ |
| 3 | `test_alias_match_1a_ban` | `"分析 1A班 英语成绩"` | scope=single, id=class-hk-f1a (中文别名匹配) | ✅ |
| 4 | `test_alias_match_bare_1a` | `"分析 1A 英语成绩"` | scope=single, id=class-hk-f1a (裸 1A 匹配) | ✅ |
| 5 | `test_alias_match_f1a` | `"分析 F1A 成绩"` | scope=single, id=class-hk-f1a (短别名 F1A) | ✅ |
| 6 | `test_multi_class_and` | `"对比 1A 和 1B 的成绩"` | scope=multi, 2 entities (f1a + f1b) | ✅ |
| 7 | `test_multi_class_comma` | `"分析 1A, 1B 成绩"` | scope=multi, 2 entities | ✅ |
| 8 | `test_grade_expansion` | `"Form 1 全年级成绩分析"` | scope=grade, 2 entities, confidence=0.9, match=grade | ✅ |
| 9 | `test_no_class_mention` | `"分析英语表现"` | scope=none, entities=[] | ✅ |
| 10 | `test_nonexistent_class` | `"分析 2C班 成绩"` | scope=none, entities=[] (2C 不存在) | ✅ |
| 11 | `test_fuzzy_match_typo` | `"分析 Fom 1A 成绩"` | entities≥1, id=class-hk-f1a (容错) | ✅ |
| 12 | `test_empty_teacher_id` | teacher_id="" | scope=none, entities=[] (优雅降级) | ✅ |
| 13 | `test_unknown_teacher` | teacher_id="t-999" | scope=none, entities=[] | ✅ |

### 3.2 学生解析 (Student Resolution — 5 项)

| # | 测试名 | 输入 | 上下文 | 预期结果 | 结果 |
|---|--------|------|--------|---------|------|
| 14 | `test_student_exact_match_with_class` | `"分析 1A 班学生 Wong Ka Ho 的成绩"` | 无 (从消息解析班级) | class=f1a + student=s-001, confidence=1.0 | ✅ |
| 15 | `test_student_with_context_classid` | `"分析学生 Li Mei 的成绩"` | `{classId: "class-hk-f1a"}` | student=s-002, name="Li Mei" | ✅ |
| 16 | `test_student_without_class_triggers_missing_context` | `"分析学生 Wong Ka Ho 的成绩"` | 无 | missing_context=["class"], students=[] | ✅ |
| 17 | `test_student_keyword_without_name` | `"学生成绩分析"` | 无 | missing_context=["class"] | ✅ |
| 18 | `test_student_english_keyword` | `"Analyze student Chan Tai Man's grades"` | `{classId: "class-hk-f1a"}` | student=s-003 | ✅ |

### 3.3 作业解析 (Assignment Resolution — 4 项)

| # | 测试名 | 输入 | 上下文 | 预期结果 | 结果 |
|---|--------|------|--------|---------|------|
| 19 | `test_assignment_exact_match_with_class` | `"分析 1A 班 Test Unit 5 Test 的提交情况"` | 无 (从消息解析班级) | class=f1a + assignment=a-001 | ✅ |
| 20 | `test_assignment_with_context_classid` | `"分析作业 Essay Writing 的成绩"` | `{classId: "class-hk-f1a"}` | assignment=a-002, name="Essay Writing" | ✅ |
| 21 | `test_assignment_without_class_triggers_missing_context` | `"分析考试 Unit 5 Test 的成绩"` | 无 | missing_context=["class"] | ✅ |
| 22 | `test_assignment_keyword_without_title` | `"作业分析"` | 无 | missing_context=["class"] | ✅ |

### 3.4 混合实体解析 (Mixed Entities — 3 项)

| # | 测试名 | 输入 | 预期结果 | 结果 |
|---|--------|------|---------|------|
| 23 | `test_class_and_student_together` | `"分析 1A 班学生 Li Mei 的成绩"` | types={CLASS, STUDENT}, missing_context=[] | ✅ |
| 24 | `test_class_and_assignment_together` | `"分析 1A 班 Test Unit 5 Test"` | types={CLASS, ASSIGNMENT} | ✅ |
| 25 | `test_student_and_assignment_without_class` | `"分析学生 Wong Ka Ho 的作业 Essay Writing"` | missing_context=["class"] | ✅ |

### 3.5 向下兼容 + 序列化 (3 项)

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 26 | `test_resolve_classes_backward_compat` | `resolve_classes()` wrapper 仍可正常使用 | ✅ |
| 27 | `test_resolved_entity_camel_case` | ResolvedEntity → camelCase (entityType/entityId/displayName/matchType) | ✅ |
| 28 | `test_resolve_result_camel_case` | ResolveResult → camelCase (isAmbiguous/scopeMode/missingContext) | ✅ |

### 3.6 API 集成: 实体解析 (4 项新增)

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_conversation_build_with_auto_resolve` | 消息中提到班级 → 自动解析 classId, response 含 resolvedEntities | ✅ |
| 2 | `test_conversation_build_ambiguous_downgrade_to_clarify` | 模糊班级引用 → 降级 clarify，choices 从匹配结果生成 | ✅ |
| 3 | `test_conversation_build_no_class_mention` | 无班级引用 → 跳过实体解析，正常 build | ✅ |
| 4 | `test_conversation_build_skips_resolve_when_context_has_class` | context 已有 classId → 完全跳过解析 | ✅ |

### 3.7 Conversation Models: resolved_entities (2 项新增)

| # | 测试名 | 描述 | 结果 |
|---|--------|------|------|
| 1 | `test_conversation_response_with_resolved_entities` | resolvedEntities 序列化为 camelCase (entityId/entityType/matchType) | ✅ |
| 2 | `test_conversation_response_resolved_entities_none` | 无解析实体时 resolvedEntities=null | ✅ |

---

## 4. Use Case Examples (用例详解)

### Use Case 1: 单班级精确解析 → 自动 build_workflow

**场景**: 教师输入包含明确的班级引用，系统自动解析并生成分析页面。

```
用户: "分析 Form 1A 英语成绩"

Entity Resolver 处理:
  ├─ 提取班级引用: "Form 1A"
  ├─ 获取教师班级列表: [Form 1A (class-hk-f1a), Form 1B (class-hk-f1b)]
  ├─ 精确匹配: "Form 1A" → class-hk-f1a (confidence=1.0)
  └─ 结果: scope_mode="single", entities=[{class, class-hk-f1a, "Form 1A"}]

API Response:
  action: "build_workflow"
  resolvedEntities: [{entityType: "class", entityId: "class-hk-f1a", displayName: "Form 1A", confidence: 1.0, matchType: "exact"}]
  blueprint: <Generated Blueprint>
```

**测试覆盖**: `test_exact_match_form_1a` + `test_conversation_build_with_auto_resolve`

---

### Use Case 2: 中文别名匹配

**场景**: 用户使用中文简写引用班级，系统通过别名匹配识别。

```
用户: "分析 1A班 英语成绩"    → class-hk-f1a (alias: "1A班")
用户: "分析 1A 英语成绩"      → class-hk-f1a (alias: bare "1A")
用户: "分析 F1A 成绩"         → class-hk-f1a (alias: short "F1A")
用户: "分析 form 1a 成绩"     → class-hk-f1a (case-insensitive)

所有变体均可正确解析，confidence=1.0, matchType="exact"
```

**测试覆盖**: `test_alias_match_1a_ban`, `test_alias_match_bare_1a`, `test_alias_match_f1a`, `test_exact_match_case_insensitive`

---

### Use Case 3: 多班级对比 → 自动解析

**场景**: 教师要求对比多个班级，系统识别所有班级引用。

```
用户: "对比 1A 和 1B 的成绩"

Entity Resolver 处理:
  ├─ 提取班级引用: ["1A", "1B"] (通过分隔符 "和" 识别)
  ├─ 匹配: 1A → class-hk-f1a, 1B → class-hk-f1b
  └─ 结果: scope_mode="multi", 2 entities

用户: "分析 1A, 1B 成绩"

Entity Resolver 处理:
  ├─ 提取班级引用: ["1A", "1B"] (通过逗号分隔识别)
  └─ 结果: scope_mode="multi", 2 entities

API 行为:
  → enriched_context: {classIds: ["class-hk-f1a", "class-hk-f1b"]}
  → 传递给 PlannerAgent 生成对比分析 Blueprint
```

**测试覆盖**: `test_multi_class_and`, `test_multi_class_comma`

---

### Use Case 4: 年级全展开

**场景**: 教师要求分析整个年级的数据。

```
用户: "Form 1 全年级成绩分析"

Entity Resolver 处理:
  ├─ 年级模式匹配: "Form 1" + "全年级"
  ├─ 展开: Form 1 下所有班级 → [class-hk-f1a, class-hk-f1b]
  └─ 结果: scope_mode="grade", 2 entities, confidence=0.9, matchType="grade"
```

**测试覆盖**: `test_grade_expansion`

---

### Use Case 5: 班级 + 学生联合解析

**场景**: 教师同时提到班级和学生姓名，系统从消息中解析班级，再从该班级的花名册中匹配学生。

```
用户: "分析 1A 班学生 Wong Ka Ho 的成绩"

Entity Resolver 处理:
  ├─ 班级解析: "1A" → class-hk-f1a
  ├─ 获取班级详情: students=[Wong Ka Ho, Li Mei, Chan Tai Man]
  ├─ 学生姓名匹配: "Wong Ka Ho" → s-001 (exact, confidence=1.0)
  └─ 结果: entities=[
       {CLASS, class-hk-f1a, "Form 1A"},
       {STUDENT, s-001, "Wong Ka Ho"}
     ]

API 行为:
  → enriched_context: {classId: "class-hk-f1a", studentId: "s-001"}
  → PlannerAgent 生成针对该学生的分析 Blueprint
```

**测试覆盖**: `test_student_exact_match_with_class`, `test_class_and_student_together`

---

### Use Case 6: 学生解析依赖 context 中的 classId

**场景**: 上一轮对话已确定了班级（classId 在 context 中），用户只提学生姓名。

```
用户: "分析学生 Li Mei 的成绩"
context: {classId: "class-hk-f1a"}  ← 来自上一轮 clarify 或 build

Entity Resolver 处理:
  ├─ 班级引用: 无 (但 context 有 classId)
  ├─ 学生关键词: "学生 Li Mei" 触发
  ├─ 使用 context.classId 获取班级详情
  ├─ 学生匹配: "Li Mei" → s-002 (exact)
  └─ 结果: entities=[{STUDENT, s-002, "Li Mei"}]
```

**测试覆盖**: `test_student_with_context_classid`

---

### Use Case 7: 缺失班级上下文 → 降级 clarify

**场景**: 用户提到学生或作业，但没有任何班级上下文，系统无法确定从哪个班级查找。

```
用户: "分析学生 Wong Ka Ho 的成绩"
context: null (无班级上下文)

Entity Resolver 处理:
  ├─ 班级引用: 无
  ├─ 学生关键词: "学生 Wong Ka Ho" 触发
  ├─ 无 classId 可用 → 无法获取花名册
  └─ 结果: missing_context=["class"], student entities=[]

API 行为:
  → action: "clarify"
  → chatResponse: "Which class would you like to look at?"
  → clarifyOptions: {type: "single_select", choices: [Form 1A, Form 1B]}
  → 用户选择班级后，系统在下一轮自动解析学生
```

**测试覆盖**: `test_student_without_class_triggers_missing_context`, `test_student_keyword_without_name`

---

### Use Case 8: 作业解析 + 班级上下文

**场景**: 教师要查看某个作业的提交情况。

```
用户: "分析 1A 班 Unit 5 Test 的提交情况"

Entity Resolver 处理:
  ├─ 班级解析: "1A" → class-hk-f1a
  ├─ 获取班级详情: assignments=[Unit 5 Test, Essay Writing]
  ├─ 作业标题匹配: "Unit 5 Test" → a-001 (exact)
  └─ 结果: entities=[
       {CLASS, class-hk-f1a, "Form 1A"},
       {ASSIGNMENT, a-001, "Unit 5 Test"}
     ]

用户: "分析作业 Essay Writing 的成绩"
context: {classId: "class-hk-f1a"}

Entity Resolver 处理:
  ├─ 作业关键词: "作业 Essay Writing" 触发
  ├─ 使用 context.classId 获取作业列表
  ├─ 作业匹配: "Essay Writing" → a-002 (exact)
  └─ 结果: entities=[{ASSIGNMENT, a-002, "Essay Writing"}]
```

**测试覆盖**: `test_assignment_exact_match_with_class`, `test_assignment_with_context_classid`

---

### Use Case 9: 不存在的班级 → 优雅处理

**场景**: 用户提到一个不存在的班级。

```
用户: "分析 2C班 成绩"

Entity Resolver 处理:
  ├─ 提取班级引用: "2C"
  ├─ 获取教师班级列表: [Form 1A, Form 1B]
  ├─ 精确匹配: 无
  ├─ 模糊匹配: 无 (2C 与任何已有班级距离过大)
  └─ 结果: scope_mode="none", entities=[]

API 行为:
  → 无实体匹配 → 正常进入 PlannerAgent (由 LLM 处理)
```

**测试覆盖**: `test_nonexistent_class`

---

### Use Case 10: 歧义匹配 → 降级 clarify 并提供选项

**场景**: 用户的输入导致多个模糊匹配结果，系统无法确定具体班级。

```
用户: "分析 F1 成绩" (F1 可能是 Form 1A 或 Form 1B)

Entity Resolver 处理:
  ├─ 匹配结果: [Form 1A (fuzzy, 0.6), Form 1B (fuzzy, 0.5)]
  ├─ is_ambiguous=True
  └─ 降级为 clarify

API Response:
  action: "clarify"
  chatResponse: "Could you confirm which you'd like to analyze?"
  clarifyOptions:
    type: "single_select"
    choices:
      - {label: "Form 1A", value: "class-hk-f1a", description: "Matched via fuzzy (confidence: 60%)"}
      - {label: "Form 1B", value: "class-hk-f1b", description: "Matched via fuzzy (confidence: 50%)"}
    allowCustomInput: true
```

**测试覆盖**: `test_conversation_build_ambiguous_downgrade_to_clarify`

---

### Use Case 11: Context 已有 classId → 跳过解析

**场景**: 用户通过 clarify 选择了班级（classId 已在 context 中），再次发送消息时不需要重复解析。

```
用户: "分析英语表现"
context: {classId: "class-hk-f1a"}  ← 来自上一轮 clarify 选择

API 行为:
  → context.classId 已存在 → 跳过 resolve_entities 调用
  → 直接传递给 PlannerAgent 生成 Blueprint
  → resolve_entities 函数未被调用 (verified by mock.assert_not_called)
```

**测试覆盖**: `test_conversation_build_skips_resolve_when_context_has_class`

---

### Use Case 12: 英文关键词触发

**场景**: 用户使用英文输入，系统同样能识别实体引用。

```
用户: "Analyze student Chan Tai Man's grades"
context: {classId: "class-hk-f1a"}

Entity Resolver 处理:
  ├─ 英文学生关键词匹配: "Student Chan Tai Man"
  ├─ 从班级 f1a 花名册中匹配
  └─ 结果: student=s-003, name="Chan Tai Man"
```

**测试覆盖**: `test_student_english_keyword`

---

## 5. 完整交互流程示例

### 流程 A: 模糊请求 → clarify → 学生分析

```
Round 1:
  用户: "分析学生 Wong Ka Ho 的成绩"
  系统: missing_context=["class"] → clarify
  响应: "Which class would you like to look at?"
        choices: [Form 1A, Form 1B]

Round 2:
  用户: "分析学生 Wong Ka Ho 的成绩"
  context: {classId: "class-hk-f1a"}  ← 用户选择了 Form 1A
  系统: resolve student "Wong Ka Ho" from class f1a → s-001
  响应: action="build_workflow", resolvedEntities=[class+student], blueprint=<...>
```

### 流程 B: 多实体一次解析

```
用户: "分析 1A 班学生 Li Mei 的 Essay Writing 作业成绩"
系统:
  ├─ 班级解析: 1A → class-hk-f1a
  ├─ 学生解析: Li Mei → s-002
  ├─ 作业解析: Essay Writing → a-002
  └─ enriched_context: {classId, studentId, assignmentId}
响应: action="build_workflow", 3 resolvedEntities
```

### 流程 C: 班级不存在 + 年级展开

```
Round 1:
  用户: "分析 2C 班成绩"
  系统: 2C 不匹配任何班级 → scope_mode="none"
  → 正常进入 PlannerAgent (可能由 LLM 回复 "未找到该班级")

Round 2:
  用户: "Form 1 全年级成绩分析"
  系统: 年级展开 → [Form 1A, Form 1B] (scope_mode="grade")
  → enriched_context: {classIds: ["class-hk-f1a", "class-hk-f1b"]}
  → PlannerAgent 生成年级级对比分析
```

---

## 6. 数据模型示例

### ResolvedEntity (camelCase 序列化)

```json
{
  "entityType": "class",
  "entityId": "class-hk-f1a",
  "displayName": "Form 1A",
  "confidence": 1.0,
  "matchType": "exact"
}
```

### ResolveResult (camelCase 序列化)

```json
{
  "entities": [
    {
      "entityType": "student",
      "entityId": "s-001",
      "displayName": "Wong Ka Ho",
      "confidence": 1.0,
      "matchType": "exact"
    }
  ],
  "isAmbiguous": false,
  "scopeMode": "single",
  "missingContext": []
}
```

### ConversationResponse with resolvedEntities (Step 4.5.3 新结构)

```json
{
  "mode": "entry",
  "action": "build",
  "chatKind": null,
  "chatResponse": "Generated analysis: English Unit 5 Test Analysis",
  "blueprint": { ... },
  "resolvedEntities": [
    {"entityType": "class", "entityId": "class-hk-f1a", "displayName": "Form 1A", "confidence": 1.0, "matchType": "exact"},
    {"entityType": "student", "entityId": "s-001", "displayName": "Wong Ka Ho", "confidence": 1.0, "matchType": "exact"}
  ],
  "clarifyOptions": null,
  "conversationId": null,
  "legacyAction": "build_workflow"
}
```

### Action 三维结构对照表 (Step 4.5.3)

| mode | action | chatKind | legacyAction |
|------|--------|----------|-------------|
| `entry` | `chat` | `smalltalk` | `chat_smalltalk` |
| `entry` | `chat` | `qa` | `chat_qa` |
| `entry` | `build` | — | `build_workflow` |
| `entry` | `clarify` | — | `clarify` |
| `followup` | `chat` | `page` | `chat` |
| `followup` | `refine` | — | `refine` |
| `followup` | `rebuild` | — | `rebuild` |

---

## 7. 实体解析策略一览

### 班级匹配 (4 层优先级)

| 层级 | 策略 | 示例 | Confidence |
|------|------|------|-----------|
| 1 | 精确匹配 (名称/别名/ID) | `"Form 1A"`, `"1A班"`, `"F1A"` | 1.0 |
| 2 | 年级展开 | `"Form 1 全年级"` → 所有 Form 1 班级 | 0.9 |
| 3 | 裸代码匹配 | `"1A"` → 全局 `\b(\d[A-Za-z])\b` | 1.0 |
| 4 | 模糊匹配 (Levenshtein) | `"Fom 1A"` (typo) | 0.6~0.99 |

### 学生/作业匹配

| 条件 | 有 classId | 无 classId |
|------|-----------|-----------|
| 有名字/标题 | 从花名册匹配 | `missing_context=["class"]` |
| 仅关键词 | 从花名册匹配 | `missing_context=["class"]` |
| 无触发 | 不解析 | 不解析 |

### API 路由决策

| 解析结果 | API 行为 |
|----------|---------|
| scope=none, missing_context=[] | 正常 build (无实体相关) |
| scope=none, missing_context=["class"] | clarify → 展示班级选项 |
| scope=single/multi, is_ambiguous=false | auto-inject context → build |
| is_ambiguous=true | clarify → 匹配结果作为选项 |
| context 已有 classId | 跳过解析 → 直接 build |

---

## 8. Warnings 说明

运行过程中产生 15 个 `DeprecationWarning`，均来自 `litellm` 第三方依赖:

```
litellm/litellm_core_utils/logging_utils.py:273: DeprecationWarning:
'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16;
use inspect.iscoroutinefunction() instead
```

此为 litellm 库内部代码使用了已弃用的 `asyncio.iscoroutinefunction`，不影响功能。

---

## 9. 结论

Phase 4.5 全部 4 个步骤 **230 项测试全部通过**，15 项 Live 对话测试 14 PASS / 1 TIMEOUT。

### Step 4.5.1 — 实体解析层
1. **自动解析** 用户消息中的班级/学生/作业引用（无需 LLM 调用）
2. **中英文混合** 支持多种引用格式（`1A班`、`Form 1A`、`F1A`、`student Wong Ka Ho`、`作业 Essay Writing`）
3. **依赖链管理** 学生/作业解析自动依赖已解析的班级或 context 中的 classId
4. **智能降级** 缺少上下文时降级为 clarify，提供交互式选项
5. **歧义处理** 多个模糊匹配时转为选项让用户确认

### Step 4.5.2 — sourcePrompt 一致性
6. **sourcePrompt 强制覆写** `generate_blueprint()` 始终写入用户原始 prompt
7. **API 层防御校验** `_verify_source_prompt()` 在 build/refine/rebuild 共 5 处调用

### Step 4.5.3 — Action 命名统一化
8. **三维结构化** `mode` + `action` + `chatKind` 替代扁平 action 字符串
9. **legacyAction 向下兼容** `@computed_field` 自动计算旧 action 值

### Step 4.5.4 — Executor 错误拦截
10. **DATA_ERROR SSE 事件** 数据获取失败时发送结构化错误事件
11. **异常体系** ToolError → DataFetchError → EntityNotFoundError

230 项测试全部通过，Phase 4.5 完成。

---

## 附录: Phase 4 测试回顾

> 以下为 Phase 4 完成时的测试报告摘要，详见 [phase4-test-report.md](phase4-test-report.md) 和 [phase4-conversation-log.md](phase4-conversation-log.md)。

### Phase 4 + 4.5 测试总结 (151 → 222 → 230 项)

| Phase | 新增测试 | 关键模块 |
|-------|---------|---------|
| Phase 4.1 | 13 | Conversation Models (IntentType, RouterResult, ClarifyOptions, Request/Response) |
| Phase 4.2 | 13 | RouterAgent (置信度路由 + 双模式意图分类) |
| Phase 4.3 | 3 | ChatAgent (闲聊 + QA) |
| Phase 4.4 | 8 | Clarify Builder (选项生成: 班级/时间/作业/科目) |
| Phase 4.5 (PageChat) | 7 | PageChatAgent (页面追问) |
| Phase 4.6 | 10 | Conversation API (7 种 action + 错误处理) |
| Phase 4.7 | 5 | E2E 闭环 (闲聊→生成, clarify→生成, 追问全路径) |
| **Phase 4.5.1** | **57** | **Entity Resolver (class/student/assignment + API 集成)** |
| **Phase 4.5.2** | **+3** | **sourcePrompt 强制覆写 + LLM 篡改检测** |
| **Phase 4.5.3** | **+2** | **legacyAction 计算 + mode/action/chatKind 结构** |
| **Phase 4.5.4** | **+4** | **DATA_ERROR SSE + DataFetchError + 异常属性** |

### Phase 4 Live Test 结果 (LLM 实际调用)

| # | 场景 | Action | 耗时 | 结果 |
|---|------|--------|------|------|
| 1 | 闲聊 "你好" | chat_smalltalk | 5.14s | ✅ 友好回复 + 功能引导 |
| 2 | QA "KPI是什么意思？" | chat_qa | 6.48s | ✅ 教育领域解释 |
| 3 | 模糊 "分析英语表现" | clarify | 1.31s | ✅ 班级选项列表 |
| 4 | 明确 "分析 Form 1A 班英语 Unit 5 考试成绩..." | build_workflow | 17.42s | ✅ Blueprint 生成 |
| 5 | 追问 "哪些学生的成绩需要重点关注？" | chat | 5.22s | ✅ 基于数据回复 |
| 6 | 微调 "只显示不及格的学生" | refine | 26.07s | ✅ 新 Blueprint |
| 7 | 重建 "加一个语法分析模块" | rebuild | 22.20s | ✅ 新 Blueprint |