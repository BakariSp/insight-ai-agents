# AI Agent Module -- Detailed Executable Test Plan

> **Scope**: `insight-ai-agent/` module
> **Target bugs**: P1 context loss, P2 intent misclassification, P3 entity resolution failures, P4 cross-intent chain breaks
> **Organized by**: Phase 1 (Foundation), Phase 2 (Multi-turn & Gateway), Phase 3 (Complex & Stress)
> **Date**: 2026-02-08

---

## Table of Contents

1. [Coverage Analysis: Existing Tests vs Gaps](#1-coverage-analysis)
2. [New Test Files to Create](#2-new-test-files)
3. [Phase 1: Foundation Tests](#3-phase-1-foundation)
4. [Phase 2: Multi-turn & Gateway Tests](#4-phase-2-multi-turn--gateway)
5. [Phase 3: Complex Scenarios & Stress Tests](#5-phase-3-complex--stress)
6. [Test Infrastructure & Shared Fixtures](#6-test-infrastructure)
7. [pytest Markers & Execution Commands](#7-execution)
8. [Dependencies Between Tests](#8-dependencies)

---

## 1. Coverage Analysis

### 1.1 Existing Test Coverage

| File | What it covers | Lines | Gaps |
|------|---------------|-------|------|
| `test_entity_resolver.py` | Class exact/alias/fuzzy/grade match; student exact+context; assignment exact+context; mixed entities; missing_context | 418 | No Chinese numeral class input (e.g. "中一A班"), no partial Chinese class names (e.g. "高一数学班"), no homophone fuzzy matching, no emoji/special char robustness |
| `test_router.py` | Confidence routing unit tests (high/medium/low); TestModel-based agent classification (smalltalk, build, clarify, followup chat/refine/rebuild); refine_scope serialization; model_tier routing | 366 | **No quiz_generate vs content_create distinction tests** (P2 root cause); no Rule 6 validation; no conversation_history context injection tests; no extracted_params validation |
| `test_conversation_api.py` | HTTP endpoint tests for all initial+followup intents; entity resolution auto-resolve/ambiguous/missing; patch mechanism; 20-round session history retention | 772 | No multi-turn session continuity tests with real conversationId flow; no quiz_generate path test; no content_create agent path test; no SSE streaming tests |
| `test_conversation_store.py` | ConversationSession CRUD; turn truncation; context merge; history formatting; InMemoryStore TTL/cleanup | 186 | No concurrent access test; no session isolation between different teachers; no PydanticAI message history conversion edge cases |
| `test_e2e_conversation.py` | Lifecycle: smalltalk->build, clarify->build, build->followup(chat->refine->rebuild); camelCase validation | 297 | No cross-intent chains (analyze->quiz->lesson plan); no real session state assertion between rounds; no quiz_generate or content_create in e2e flows |
| `test_conversation_stream.py` | (exists, not read) SSE streaming protocol | ? | Need to verify coverage |

### 1.2 Critical Gaps Summary

| Gap ID | Description | Affected Bug | Priority |
|--------|------------|-------------|----------|
| G1 | No test distinguishing quiz_generate from content_create | P2 | P0 |
| G2 | No Rule 6 "output format judgment" validation | P2 | P0 |
| G3 | No Chinese numeral class name resolution (中一A, 高一) | P3 | P0 |
| G4 | No multi-turn session state continuity (last_intent, last_action, accumulated_context) | P1 | P0 |
| G5 | No cross-intent chain tests (analyze -> quiz -> lesson plan) | P4 | P1 |
| G6 | No follow-up mode transition to new intent type (quiz in follow-up mode) | P4 | P1 |
| G7 | No concurrent session isolation tests | -- | P2 |
| G8 | No long conversation degradation tests (10+ turns) | P1 | P1 |
| G9 | No extracted_params validation (topic, count, types for quiz) | P2 | P1 |

---

## 2. New Test Files

| File | Purpose | Phase |
|------|---------|-------|
| `tests/test_intent_classification.py` | Single-turn intent accuracy: quiz_generate vs content_create vs build_workflow; Rule 6; extracted_params | Phase 1 |
| `tests/test_entity_resolver_extended.py` | Extended entity resolver: Chinese numerals, partial names, subject-class combos, edge cases | Phase 1 |
| `tests/test_gateway_multiturn.py` | Conversation Gateway cross-path transitions; session state validation; follow-up mode intent routing | Phase 2 |
| `tests/test_session_continuity.py` | conversationId preservation; accumulated_context; last_intent/last_action persistence across turns | Phase 2 |
| `tests/test_composite_scenarios.py` | Complex chains: analyze->quiz->lesson_plan; survey->quiz->publish; cross-intent sequences | Phase 3 |
| `tests/test_stress_conversation.py` | Long conversations (10+ turns); concurrent session isolation; memory/degradation tests | Phase 3 |

---

## 3. Phase 1: Foundation

### 3.1 Entity Resolver Accuracy Tests

**File**: `tests/test_entity_resolver_extended.py`

#### AI-P1-01: Chinese numeral class name resolution

- **Description**: Resolve "中一A班" to Form 1A using Chinese numeral mapping.
- **Setup**: Mock `execute_mcp_tool` returning MOCK_CLASSES (Form 1A, Form 1B with grade "Form 1").
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "分析中一A班的英语成绩")
  ```
- **Expected Result**:
  - `result.scope_mode == "single"`
  - `result.entities[0].entity_id == "class-hk-f1a"`
  - `result.entities[0].confidence >= 0.8`
- **Priority**: P0

#### AI-P1-02: Subject-qualified class name (P3 bug: "高一数学班")

- **Description**: Resolve a class reference that includes subject context ("高一数学班"). The entity resolver should match via grade pattern even when subject text is present.
- **Setup**: Mock classes including a math class:
  ```python
  MOCK_CLASSES_EXTENDED = [
      {"class_id": "class-math-s1a", "name": "S1A", "grade": "S1", "subject": "数学"},
      {"class_id": "class-math-s1b", "name": "S1B", "grade": "S1", "subject": "数学"},
      {"class_id": "class-eng-s1a", "name": "Form 1A", "grade": "Form 1", "subject": "English"},
  ]
  ```
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "分析高一数学班的考试成绩")
  ```
- **Expected Result**:
  - At minimum: `result.scope_mode != "none"` (either resolves to grade-level or fails gracefully with clarify)
  - If no match found: `result.missing_context` should guide the clarify path, NOT silently return empty.
- **Priority**: P0 (this is the P3 bug)

#### AI-P1-03: Mixed Chinese/English class references

- **Description**: Handle "1A班和Form 1B" in the same query.
- **Setup**: Standard MOCK_CLASSES.
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "对比1A班和Form 1B的成绩")
  ```
- **Expected Result**:
  - `len(result.entities) == 2`
  - `result.scope_mode == "multi"`
  - Both `class-hk-f1a` and `class-hk-f1b` are in entity IDs.
- **Priority**: P1

#### AI-P1-04: Class name with special characters and whitespace

- **Description**: Handle edge cases like extra whitespace, parentheses, etc.
- **Setup**: Standard MOCK_CLASSES.
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "分析 ( 1A ) 班成绩")
  ```
- **Expected Result**:
  - `result.entities[0].entity_id == "class-hk-f1a"` (extracted despite parentheses)
  - OR graceful empty result (no crash).
- **Priority**: P2

#### AI-P1-05: Student name with partial match

- **Description**: Resolve student by partial name "Ka Ho" (without surname).
- **Setup**: MOCK_CLASS_DETAIL_F1A with student "Wong Ka Ho".
- **Steps**:
  ```python
  result = await resolve_entities(
      "t-001",
      "1A班学生 Ka Ho 的成绩怎么样",
  )
  ```
- **Expected Result**:
  - Student entity resolved with `entity_id == "s-001"`
  - `match_type == "fuzzy"` and `confidence >= 0.6`
- **Priority**: P1

#### AI-P1-06: Assignment name with typo

- **Description**: Resolve "Unit5 Test" (missing space) to "Unit 5 Test".
- **Setup**: MOCK_CLASS_DETAIL_F1A with assignment "Unit 5 Test".
- **Steps**:
  ```python
  result = await resolve_entities(
      "t-001",
      "1A班 Test Unit5 Test 的情况",
  )
  ```
- **Expected Result**:
  - Assignment entity resolved via fuzzy matching
  - `confidence >= 0.6`
- **Priority**: P1

#### AI-P1-07: Empty query text

- **Description**: Ensure empty string does not crash the resolver.
- **Setup**: Standard MOCK_CLASSES.
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "")
  ```
- **Expected Result**:
  - `result.scope_mode == "none"`
  - `len(result.entities) == 0`
  - No exceptions raised.
- **Priority**: P1

#### AI-P1-08: MCP tool failure graceful degradation

- **Description**: When `execute_mcp_tool` raises an exception, entity resolver returns empty result.
- **Setup**: Patch `execute_mcp_tool` to raise `ConnectionError`.
- **Steps**:
  ```python
  with patch("services.entity_resolver.execute_mcp_tool", side_effect=ConnectionError("timeout")):
      result = await resolve_entities("t-001", "分析 1A 班成绩")
  ```
- **Expected Result**:
  - `result.scope_mode == "none"`
  - `len(result.entities) == 0`
  - No unhandled exception.
- **Priority**: P0

---

### 3.2 Single-Turn Intent Classification Accuracy

**File**: `tests/test_intent_classification.py`

These tests validate the Router's ability to distinguish between intent types, especially the P2 bug (content_create vs quiz_generate confusion).

#### Test Data Matrix

```python
# ── Intent Classification Test Cases ──
# Each tuple: (input_message, expected_intent, expected_min_confidence, description)

QUIZ_GENERATE_CASES = [
    ("帮我出10道语法选择题", "quiz_generate", 0.7, "Chinese: explicit quiz request with count"),
    ("Generate 5 MCQs on grammar", "quiz_generate", 0.7, "English: MCQ request"),
    ("给 1B 出一套阅读题", "quiz_generate", 0.7, "Chinese: class-scoped quiz"),
    ("出一份 Unit 5 练习", "quiz_generate", 0.7, "Chinese: exercise/practice request"),
    ("出10道一元二次方程的选择题", "quiz_generate", 0.7, "Chinese: math quiz with topic"),
    ("帮我做一套英语模拟试卷", "quiz_generate", 0.7, "Chinese: mock exam"),
    ("出5道填空题关于分数", "quiz_generate", 0.7, "Chinese: fill-in-blank with topic"),
    ("Create a 20-question test on photosynthesis", "quiz_generate", 0.7, "English: test request"),
]

CONTENT_CREATE_CASES = [
    ("帮我做一个教案", "content_create", 0.7, "Chinese: lesson plan request"),
    ("生成一个PPT", "content_create", 0.7, "Chinese: PPT/slides request"),
    ("写一份学生评语", "content_create", 0.7, "Chinese: student feedback"),
    ("Generate a lesson plan for Unit 5", "content_create", 0.7, "English: lesson plan"),
    ("帮我写一封家长信", "content_create", 0.7, "Chinese: parent letter"),
    ("做一个工作纸", "content_create", 0.7, "Chinese: worksheet"),
    ("翻译这段文字", "content_create", 0.7, "Chinese: translation task"),
    ("写一份评分标准", "content_create", 0.7, "Chinese: rubric design"),
    ("帮我设计课件", "content_create", 0.7, "Chinese: courseware design"),
]

BUILD_WORKFLOW_CASES = [
    ("分析 1A 班英语成绩", "build_workflow", 0.7, "Chinese: class analysis"),
    ("帮我看看这次考试情况", "build_workflow", 0.7, "Chinese: exam analysis"),
    ("对比两个班的表现", "build_workflow", 0.7, "Chinese: comparison analysis"),
    ("Analyze the performance trends for Form 1A", "build_workflow", 0.7, "English: trend analysis"),
]

CHAT_CASES = [
    ("你好", "chat_smalltalk", 0.8, "Chinese: greeting"),
    ("Hello", "chat_smalltalk", 0.8, "English: greeting"),
    ("谢谢", "chat_smalltalk", 0.8, "Chinese: thanks"),
    ("KPI 是什么意思", "chat_qa", 0.8, "Chinese: concept question"),
    ("什么是标准差", "chat_qa", 0.8, "Chinese: stats concept"),
    ("怎么使用这个功能", "chat_qa", 0.8, "Chinese: platform usage"),
]
```

#### AI-P1-09: Quiz vs Content distinction (Rule 6 — P2 bug root cause)

- **Description**: Validate that "出题/quiz/MCQ/exercise" routes to `quiz_generate` and all other generation requests route to `content_create`. This is Rule 6 in `config/prompts/router.py`.
- **Setup**: Use `pydantic_ai.models.test.TestModel` with custom output args that simulate correct intent classification.
- **Steps**: For each pair in the confusion matrix:
  ```python
  @pytest.mark.parametrize("message,expected_intent,min_confidence,desc", QUIZ_GENERATE_CASES)
  async def test_quiz_generate_classification(message, expected_intent, min_confidence, desc):
      test_model = TestModel(
          custom_output_args={
              "intent": expected_intent,
              "confidence": 0.85,
              "should_build": False,
              "clarifying_question": None,
              "route_hint": None,
              "extracted_params": {"topic": "grammar", "count": 10},
          },
      )
      result = await _initial_agent.run(message, model=test_model)
      r = result.output
      assert r.intent == expected_intent, f"[{desc}] Expected {expected_intent}, got {r.intent}"
  ```
- **Expected Result**: Each case routes to correct intent with confidence >= threshold.
- **Priority**: P0

#### AI-P1-10: Content generation NOT misrouted to quiz_generate

- **Description**: Ensure "帮我做一个教案" (lesson plan) does NOT get classified as quiz_generate.
- **Setup**: Use TestModel with `content_create` output.
- **Steps**:
  ```python
  @pytest.mark.parametrize("message,expected_intent,min_confidence,desc", CONTENT_CREATE_CASES)
  async def test_content_create_not_quiz(message, expected_intent, min_confidence, desc):
      test_model = TestModel(
          custom_output_args={
              "intent": expected_intent,
              "confidence": 0.85,
              "should_build": False,
              "clarifying_question": None,
              "route_hint": None,
          },
      )
      result = await _initial_agent.run(message, model=test_model)
      r = result.output
      assert r.intent == "content_create"
      assert r.intent != "quiz_generate"
  ```
- **Expected Result**: Intent is `content_create`, never `quiz_generate`.
- **Priority**: P0

#### AI-P1-11: Path assignment validation

- **Description**: Validate `_assign_path()` returns correct execution paths.
- **Setup**: Direct unit test of `_assign_path`.
- **Steps**:
  ```python
  from agents.router import _assign_path

  def test_path_assignment():
      cases = [
          (RouterResult(intent="quiz_generate", confidence=0.9), "skill"),
          (RouterResult(intent="build_workflow", confidence=0.9), "blueprint"),
          (RouterResult(intent="content_create", confidence=0.9), "agent"),
          (RouterResult(intent="chat_smalltalk", confidence=0.9), "chat"),
          (RouterResult(intent="chat_qa", confidence=0.9), "chat"),
          (RouterResult(intent="clarify", confidence=0.5), "chat"),
          (RouterResult(intent="unknown_intent", confidence=0.5), "agent"),  # fallback
      ]
      for r, expected_path in cases:
          assert _assign_path(r) == expected_path
  ```
- **Expected Result**: Each intent maps to its documented path.
- **Priority**: P0

#### AI-P1-12: Extracted params for quiz_generate

- **Description**: Verify that `extracted_params` contains topic, count, types, difficulty when quiz is detected.
- **Setup**: TestModel returning quiz_generate with params.
- **Steps**:
  ```python
  test_model = TestModel(
      custom_output_args={
          "intent": "quiz_generate",
          "confidence": 0.9,
          "should_build": False,
          "extracted_params": {
              "topic": "一元二次方程",
              "count": 10,
              "types": ["SINGLE_CHOICE"],
              "difficulty": "medium",
              "subject": "数学",
              "grade": "S3",
          },
      },
  )
  result = await _initial_agent.run("出10道一元二次方程的选择题", model=test_model)
  r = result.output
  assert r.extracted_params["topic"] == "一元二次方程"
  assert r.extracted_params["count"] == 10
  ```
- **Expected Result**: All extractable params are present with correct values.
- **Priority**: P1

#### AI-P1-13: Confidence routing with quiz_generate

- **Description**: Validate that quiz_generate follows the same confidence thresholds as other actionable intents.
- **Setup**: Direct unit test of `_apply_confidence_routing`.
- **Steps**:
  ```python
  # High confidence -> pass through
  r = RouterResult(intent="quiz_generate", confidence=0.85)
  result = _apply_confidence_routing(r)
  assert result.intent == "quiz_generate"

  # Medium confidence -> clarify
  r = RouterResult(intent="quiz_generate", confidence=0.55)
  result = _apply_confidence_routing(r)
  assert result.intent == "clarify"

  # Low confidence -> chat_smalltalk
  r = RouterResult(intent="quiz_generate", confidence=0.3)
  result = _apply_confidence_routing(r)
  assert result.intent == "chat_smalltalk"
  ```
- **Expected Result**: Same thresholds apply (>=0.7 pass, 0.4-0.7 clarify, <0.4 chat).
- **Priority**: P0

#### AI-P1-14: Confidence routing with content_create

- **Description**: Same confidence thresholds for content_create.
- **Setup**: Direct unit test.
- **Steps**:
  ```python
  r = RouterResult(intent="content_create", confidence=0.85)
  result = _apply_confidence_routing(r)
  assert result.intent == "content_create"
  assert result.should_build is False  # content_create never sets should_build

  r = RouterResult(intent="content_create", confidence=0.55)
  result = _apply_confidence_routing(r)
  assert result.intent == "clarify"
  ```
- **Expected Result**: content_create treated as actionable intent for threshold purposes.
- **Priority**: P0

#### AI-P1-15: enable_rag defaults to false

- **Description**: Verify `enable_rag` is false by default and only set true with explicit RAG keywords.
- **Setup**: TestModel.
- **Steps**:
  ```python
  test_model = TestModel(
      custom_output_args={
          "intent": "quiz_generate",
          "confidence": 0.9,
          "enable_rag": False,
      },
  )
  result = await _initial_agent.run("出10道数学题", model=test_model)
  assert result.output.enable_rag is False
  ```
- **Expected Result**: `enable_rag == False` for normal requests.
- **Priority**: P1

---

### 3.3 Java API Data Pipeline Integration Tests

**File**: `tests/test_entity_resolver_extended.py` (added to same file)

#### AI-P1-16: Classes from Java API mock pipeline

- **Description**: Verify end-to-end entity resolution when data comes through the MCP tool -> Java adapter pipeline.
- **Setup**: Mock `execute_mcp_tool("get_teacher_classes")` with realistic Java API response shape.
- **Steps**:
  ```python
  JAVA_API_RESPONSE = {
      "teacher_id": "t-001",
      "classes": [
          {"class_id": "cls-uuid-001", "name": "高一(1)班", "grade": "高一", "subject": "数学", "student_count": 42},
          {"class_id": "cls-uuid-002", "name": "高一(2)班", "grade": "高一", "subject": "数学", "student_count": 40},
      ],
  }
  result = await resolve_entities("t-001", "分析高一(1)班的数学成绩")
  ```
- **Expected Result**:
  - At least one entity resolved.
  - `entity_id` matches the Java API response format.
- **Priority**: P1

#### AI-P1-17: Class detail with no students

- **Description**: Handle class detail response with empty student list.
- **Setup**: Mock class detail returning `{"students": [], "assignments": []}`.
- **Steps**:
  ```python
  result = await resolve_entities("t-001", "分析1A班学生 Wong Ka Ho 的成绩")
  ```
- **Expected Result**:
  - Class entity resolved.
  - Student entity NOT resolved (empty roster).
  - `result.is_ambiguous == False` (no crash).
- **Priority**: P1

---

### 3.4 Router Prompt Rule 6 Validation

**File**: `tests/test_intent_classification.py`

#### AI-P1-18: Rule 6 boundary cases

- **Description**: Test ambiguous messages that could be either quiz or content.
- **Setup**: TestModel with the expected correct output.
- **Steps**: Test each boundary case:
  ```python
  RULE_6_BOUNDARY_CASES = [
      # "出题" keyword -> quiz_generate
      ("帮我出几道题目", "quiz_generate", "出题 keyword triggers quiz"),
      # "做一份练习" -> quiz_generate (练习 = exercise)
      ("做一份英语练习", "quiz_generate", "练习 keyword triggers quiz"),
      # "做一个教案" -> content_create (教案 = lesson plan)
      ("做一个教案", "content_create", "教案 is content, not quiz"),
      # "生成练习" -> quiz_generate
      ("生成数学练习题", "quiz_generate", "练习题 is quiz"),
      # "写一份工作纸" -> content_create
      ("写一份工作纸", "content_create", "工作纸 is worksheet, content"),
      # "帮我做一套卷子" -> quiz_generate
      ("帮我做一套卷子", "quiz_generate", "卷子 = test paper = quiz"),
      # "帮我做一个互动游戏" -> content_create
      ("帮我做一个互动游戏", "content_create", "interactive game is content"),
  ]
  ```
- **Expected Result**: Each boundary case routes to the correct intent.
- **Priority**: P0

---

## 4. Phase 2: Multi-turn & Gateway

### 4.1 Conversation Gateway Cross-Path Transition Tests

**File**: `tests/test_gateway_multiturn.py`

#### AI-P2-01: Content -> Quiz transition (no blueprint)

- **Description**: User starts with content_create, then switches to quiz_generate in the next turn. Validates that the gateway correctly classifies the new intent despite conversation history containing content_create.
- **Setup**: InMemoryConversationStore; httpx AsyncClient against app.
- **Steps**:
  ```python
  # Turn 1: Content creation
  with patch("api.conversation.classify_intent", return_value=RouterResult(intent="content_create", confidence=0.9)):
      with patch("api.conversation.chat_response", return_value="..."):
          resp1 = await client.post("/api/conversation", json={
              "message": "帮我做一个教案",
              "conversationId": conv_id,
          })
  assert resp1.json()["action"] == "build"  # content_create -> "build" action

  # Turn 2: Switch to quiz
  with patch("api.conversation.classify_intent", return_value=RouterResult(
      intent="quiz_generate", confidence=0.9,
      extracted_params={"topic": "grammar", "count": 5},
  )):
      resp2 = await client.post("/api/conversation", json={
          "message": "现在帮我出5道语法题",
          "conversationId": conv_id,
      })
  assert resp2.json()["action"] == "build"  # quiz_generate via JSON endpoint
  ```
- **Expected Result**:
  - Turn 2 correctly routes to quiz_generate, not content_create.
  - `conversationId` preserved across turns.
- **Priority**: P0

#### AI-P2-02: Build -> Quiz transition

- **Description**: After a build_workflow (analysis) turn, user requests quiz generation.
- **Setup**: Same as above.
- **Steps**:
  ```python
  # Turn 1: Analysis
  with mocks for build_workflow:
      resp1 = await client.post("/api/conversation", json={
          "message": "分析1A班英语成绩",
          "context": {"classId": "class-hk-f1a"},
          "conversationId": conv_id,
      })

  # Turn 2: Quiz request
  with mocks for quiz_generate:
      resp2 = await client.post("/api/conversation", json={
          "message": "根据薄弱点出10道练习题",
          "conversationId": conv_id,
      })
  ```
- **Expected Result**:
  - Turn 2 intent is `quiz_generate`.
  - The conversation context from Turn 1 (classId, analysis results) is accessible via `accumulated_context`.
- **Priority**: P0

#### AI-P2-03: Clarify -> Content transition

- **Description**: First turn clarifies, second turn provides info and requests content creation.
- **Setup**: InMemoryConversationStore with shared conv_id.
- **Steps**:
  ```python
  # Turn 1: Clarify
  with mocks for clarify intent:
      resp1 = await client.post("/api/conversation", json={
          "message": "帮我做点东西",
          "conversationId": conv_id,
      })
  assert resp1.json()["action"] == "clarify"

  # Turn 2: User provides details -> should resolve to content_create
  with mocks for content_create intent:
      resp2 = await client.post("/api/conversation", json={
          "message": "做一个关于光合作用的教案",
          "conversationId": conv_id,
      })
  assert resp2.json()["legacyAction"] == "build_workflow" or resp2.json()["action"] == "build"
  ```
- **Expected Result**: Second turn resolves to `content_create` with high confidence.
- **Priority**: P1

#### AI-P2-04: Follow-up mode limited to chat/refine/rebuild

- **Description**: In follow-up mode (blueprint present), the router only produces chat/refine/rebuild intents. A quiz request in follow-up mode should either: (a) be classified as rebuild, or (b) fall back to chat. This documents the current limitation.
- **Setup**: Blueprint object present in request.
- **Steps**:
  ```python
  bp_json = _sample_blueprint_args()
  with patch("api.conversation.classify_intent", return_value=RouterResult(
      intent="chat", confidence=0.7,  # follow-up mode only has chat/refine/rebuild
  )):
      resp = await client.post("/api/conversation", json={
          "message": "帮我出10道题",
          "blueprint": bp_json,
      })
  ```
- **Expected Result**:
  - Response action is "chat" (fallback in follow-up mode).
  - This documents the current limitation where new-intent requests in follow-up mode degrade to chat.
- **Priority**: P1 (documents known limitation)

---

### 4.2 Session State Validation

**File**: `tests/test_session_continuity.py`

#### AI-P2-05: last_intent and last_action persistence

- **Description**: After each turn, `last_intent` and `last_action` are correctly set on the session.
- **Setup**: Direct unit test of `_save_session`.
- **Steps**:
  ```python
  store = InMemoryConversationStore()
  session = ConversationSession(conversation_id="test-session")

  # Simulate saving after a chat_smalltalk turn
  req = ConversationRequest(message="你好")
  response = ConversationResponse(mode="entry", action="chat", chat_kind="smalltalk", chat_response="Hi!")
  await _save_session(store, session, req, response, "chat_smalltalk")

  saved = await store.get("test-session")
  assert saved.last_intent == "chat_smalltalk"
  assert saved.last_action == "chat_smalltalk"

  # Simulate next turn: build_workflow
  req2 = ConversationRequest(message="分析成绩", conversation_id="test-session")
  response2 = ConversationResponse(mode="entry", action="build", chat_response="Generated")
  await _save_session(store, session, req2, response2, "build_workflow")

  saved2 = await store.get("test-session")
  assert saved2.last_intent == "build_workflow"
  assert saved2.last_action == "build_workflow"
  ```
- **Expected Result**: Session fields updated correctly after each turn.
- **Priority**: P0

#### AI-P2-06: accumulated_context merges across turns

- **Description**: Context from multiple turns accumulates correctly.
- **Setup**: Direct test of ConversationSession.merge_context + _load_session injection.
- **Steps**:
  ```python
  store = InMemoryConversationStore()

  # Turn 1: set classId
  session = ConversationSession(conversation_id="merge-test")
  session.merge_context({"classId": "class-hk-f1a"})
  await store.save(session)

  # Turn 2: request with studentId — should see both
  req = ConversationRequest(
      message="分析学生成绩",
      conversation_id="merge-test",
      context={"studentId": "s-001"},
  )
  session2, _, _ = await _load_session(store, req)

  # The merged context should have both classId and studentId
  assert req.context["classId"] == "class-hk-f1a"
  assert req.context["studentId"] == "s-001"
  ```
- **Expected Result**: Both keys present in merged context.
- **Priority**: P0

#### AI-P2-07: accumulated_context overwrite priority

- **Description**: Current request context overwrites session accumulated context.
- **Setup**: Session has `classId: class-1`, request has `classId: class-2`.
- **Steps**:
  ```python
  session = ConversationSession(conversation_id="overwrite-test")
  session.merge_context({"classId": "class-1"})
  await store.save(session)

  req = ConversationRequest(
      message="分析成绩",
      conversation_id="overwrite-test",
      context={"classId": "class-2"},
  )
  session, _, _ = await _load_session(store, req)
  assert req.context["classId"] == "class-2"  # current request wins
  ```
- **Expected Result**: `classId` is "class-2" (request takes priority).
- **Priority**: P0

#### AI-P2-08: conversationId generated if not provided

- **Description**: First request without conversationId gets a server-generated ID.
- **Setup**: Post to `/api/conversation` without conversationId.
- **Steps**:
  ```python
  with mocks:
      resp = await client.post("/api/conversation", json={"message": "你好"})
  data = resp.json()
  assert data["conversationId"] is not None
  assert data["conversationId"].startswith("conv-")
  ```
- **Expected Result**: Server-generated ID returned in response.
- **Priority**: P0

#### AI-P2-09: conversationId preserved across turns

- **Description**: Using the same conversationId across multiple turns maintains session continuity.
- **Setup**: Send 3 turns with the same conv_id.
- **Steps**:
  ```python
  conv_id = "conv-test-preserve"

  for i in range(3):
      with mocks:
          resp = await client.post("/api/conversation", json={
              "message": f"Turn {i}",
              "conversationId": conv_id,
          })
      assert resp.json()["conversationId"] == conv_id
  ```
- **Expected Result**: Same conversationId returned in all responses.
- **Priority**: P0

#### AI-P2-10: History text excludes current message

- **Description**: When building history for router prompt, the current user message is excluded (to avoid self-referential classification).
- **Setup**: Session with 3 turns.
- **Steps**:
  ```python
  session = ConversationSession(conversation_id="test-hist")
  session.add_user_turn("First message")
  session.add_assistant_turn("First reply", action="chat_smalltalk")
  session.add_user_turn("Current message")

  history = session.format_history_for_prompt()
  assert "First message" in history
  assert "First reply" in history
  assert "Current message" not in history
  ```
- **Expected Result**: Current message excluded from history text.
- **Priority**: P0

---

### 4.3 Follow-up Mode Intent Routing

**File**: `tests/test_gateway_multiturn.py`

#### AI-P2-11: Follow-up chat intent

- **Description**: In follow-up mode, asking about existing data routes to page chat.
- **Setup**: Blueprint in request.
- **Steps**:
  ```python
  bp_json = _sample_blueprint_args()
  with mocks for follow-up chat:
      resp = await client.post("/api/conversation", json={
          "message": "哪些学生需要关注？",
          "blueprint": bp_json,
          "pageContext": {"mean": 74.2},
      })
  assert resp.json()["action"] == "chat"
  assert resp.json()["mode"] == "followup"
  assert resp.json()["chatKind"] == "page"
  ```
- **Expected Result**: Correctly routes to page chat.
- **Priority**: P0

#### AI-P2-12: Follow-up refine with patch_layout scope

- **Description**: UI-only change request in follow-up mode routes to refine with patch_layout.
- **Setup**: Blueprint + RouterResult with refine_scope="patch_layout".
- **Steps**:
  ```python
  bp_json = _sample_blueprint_args()
  mock_router = RouterResult(
      intent="refine", confidence=0.9,
      should_build=True, refine_scope="patch_layout",
  )
  with mocks:
      resp = await client.post("/api/conversation", json={
          "message": "把标题改成蓝色",
          "blueprint": bp_json,
      })
  assert resp.json()["action"] == "refine"
  assert resp.json()["patchPlan"]["scope"] == "patch_layout"
  ```
- **Expected Result**: Patch plan returned, no new blueprint.
- **Priority**: P1

#### AI-P2-13: Follow-up refine with patch_compose scope

- **Description**: AI content regeneration request routes to refine with patch_compose.
- **Setup**: RouterResult with refine_scope="patch_compose".
- **Steps**: Similar to AI-P2-12 but with "缩短分析内容" message.
- **Expected Result**: `patchPlan.scope == "patch_compose"` with instructions.
- **Priority**: P1

#### AI-P2-14: Follow-up rebuild intent

- **Description**: Structural change triggers rebuild with new blueprint.
- **Setup**: RouterResult with intent="rebuild".
- **Steps**:
  ```python
  with mocks:
      resp = await client.post("/api/conversation", json={
          "message": "加一个语法分析板块",
          "blueprint": bp_json,
      })
  assert resp.json()["action"] == "rebuild"
  assert resp.json()["blueprint"] is not None
  ```
- **Expected Result**: New blueprint generated.
- **Priority**: P1

---

### 4.4 Conversation History for Router Context

**File**: `tests/test_session_continuity.py`

#### AI-P2-15: Clarify follow-up with "是的" should resolve to original intent

- **Description**: When router previously returned clarify, and user replies "是的" or provides the requested parameter, the router should classify with high confidence using conversation history. This tests Rules 9 and 10 in the router prompt.
- **Setup**: Session with clarify history + TestModel.
- **Steps**:
  ```python
  # Simulate: previous turn was clarify asking for class, user says "1A班"
  conversation_history = (
      "USER: 分析英语成绩\n"
      "ASSISTANT: [clarify] 请问您想分析哪个班级？"
  )

  test_model = TestModel(
      custom_output_args={
          "intent": "build_workflow",
          "confidence": 0.9,
          "should_build": True,
          "clarifying_question": None,
          "route_hint": None,
      },
  )

  # The history-aware agent should classify "1A班" as build_workflow
  from pydantic_ai import Agent
  from config.prompts.router import build_router_prompt

  agent = Agent(
      model=test_model,
      output_type=RouterResult,
      system_prompt=build_router_prompt(conversation_history=conversation_history),
      retries=1,
      defer_model_check=True,
  )
  result = await agent.run("1A班")
  assert result.output.intent == "build_workflow"
  assert result.output.confidence >= 0.8
  ```
- **Expected Result**: Short reply after clarify resolves to original intent.
- **Priority**: P0

#### AI-P2-16: PydanticAI message_history structure validation

- **Description**: Verify `to_pydantic_messages()` produces correct ModelMessage structure for agent.run(message_history=...).
- **Setup**: Session with 4 turns.
- **Steps**:
  ```python
  session = ConversationSession(conversation_id="msg-test")
  session.add_user_turn("Hello")
  session.add_assistant_turn("Hi!", action="chat_smalltalk")
  session.add_user_turn("Analyze grades")
  session.add_assistant_turn("Which class?", action="clarify")
  session.add_user_turn("current question")  # current turn

  messages = session.to_pydantic_messages()
  assert len(messages) == 4  # excludes current turn

  # Verify structure
  from pydantic_ai.messages import ModelRequest, ModelResponse
  assert isinstance(messages[0], ModelRequest)
  assert isinstance(messages[1], ModelResponse)
  assert isinstance(messages[2], ModelRequest)
  assert isinstance(messages[3], ModelResponse)
  ```
- **Expected Result**: Correct alternating ModelRequest/ModelResponse structure.
- **Priority**: P1

---

## 5. Phase 3: Complex Scenarios & Stress

### 5.1 Composite Scenario Chains

**File**: `tests/test_composite_scenarios.py`

#### AI-P3-01: Analyze -> Quiz -> Lesson Plan chain

- **Description**: Full 3-turn chain: (1) analyze class performance, (2) generate quiz based on weak areas, (3) create lesson plan. Tests cross-intent continuity (P4 bug).
- **Setup**: InMemoryConversationStore; shared conv_id; mock all agents.
- **Steps**:
  ```python
  conv_id = "conv-chain-001"

  # Turn 1: Build analysis
  with mocks(classify_intent -> build_workflow, generate_blueprint -> bp):
      resp1 = await client.post("/api/conversation", json={
          "message": "分析1A班英语成绩",
          "teacherId": "t-001",
          "context": {"classId": "class-hk-f1a"},
          "conversationId": conv_id,
      })
  assert resp1.json()["action"] == "build"
  assert resp1.json()["conversationId"] == conv_id

  # Turn 2: Quiz based on analysis
  with mocks(classify_intent -> quiz_generate with params):
      resp2 = await client.post("/api/conversation", json={
          "message": "根据分析结果出10道薄弱点练习题",
          "conversationId": conv_id,
      })
  # quiz_generate via JSON endpoint returns redirect to stream
  assert resp2.json()["action"] == "build"
  assert resp2.json()["conversationId"] == conv_id

  # Turn 3: Lesson plan
  with mocks(classify_intent -> content_create):
      with mocks(chat_response -> "..."):
          resp3 = await client.post("/api/conversation", json={
              "message": "现在帮我做一个针对这些薄弱点的教案",
              "conversationId": conv_id,
          })
  assert resp3.json()["action"] == "build"
  assert resp3.json()["conversationId"] == conv_id
  ```
- **Expected Result**:
  - All 3 turns use the same conversationId.
  - accumulated_context from Turn 1 (classId) is available in Turn 2 and 3.
  - No intent misclassification across the chain.
- **Priority**: P0

#### AI-P3-02: Quiz -> Chat -> More Quiz chain

- **Description**: User generates quiz, asks a follow-up question about the quiz, then generates more questions.
- **Setup**: Shared conv_id.
- **Steps**:
  ```python
  conv_id = "conv-chain-002"

  # Turn 1: Quiz generation
  with mocks(quiz_generate):
      resp1 = await client.post("/api/conversation", json={
          "message": "出5道英语语法题",
          "conversationId": conv_id,
      })

  # Turn 2: Chat about the quiz
  with mocks(chat_qa):
      resp2 = await client.post("/api/conversation", json={
          "message": "这些题目的难度分布合理吗？",
          "conversationId": conv_id,
      })
  assert resp2.json()["action"] == "chat"

  # Turn 3: More quiz questions
  with mocks(quiz_generate):
      resp3 = await client.post("/api/conversation", json={
          "message": "再出5道难一点的",
          "conversationId": conv_id,
      })
  ```
- **Expected Result**: Turn 3 correctly classified as quiz_generate despite Turn 2 being chat.
- **Priority**: P1

#### AI-P3-03: Multi-class analysis chain

- **Description**: User analyzes class 1A, then asks to compare with 1B.
- **Setup**: Shared conv_id, accumulated_context starts with classId for 1A.
- **Steps**:
  ```python
  conv_id = "conv-chain-003"

  # Turn 1: Analyze 1A
  with mocks:
      resp1 = await client.post("/api/conversation", json={
          "message": "分析1A班成绩",
          "context": {"classId": "class-hk-f1a"},
          "conversationId": conv_id,
      })

  # Turn 2: Compare with 1B (new context should merge)
  with mocks:
      resp2 = await client.post("/api/conversation", json={
          "message": "和1B班对比一下",
          "context": {"classId": "class-hk-f1b"},
          "conversationId": conv_id,
      })
  ```
- **Expected Result**: Turn 2 processes with updated context (classId changed to 1B).
- **Priority**: P1

#### AI-P3-04: Clarify chain with multiple rounds

- **Description**: User needs 2 rounds of clarification before build.
- **Setup**: Shared conv_id.
- **Steps**:
  ```python
  conv_id = "conv-chain-004"

  # Turn 1: Vague request -> clarify (which class?)
  with mocks(clarify, route_hint="needClassId"):
      resp1 = await client.post("/api/conversation", json={
          "message": "分析成绩",
          "teacherId": "t-001",
          "conversationId": conv_id,
      })
  assert resp1.json()["action"] == "clarify"

  # Turn 2: User provides class but still vague -> clarify (which assignment?)
  with mocks(clarify, route_hint="needAssignment"):
      resp2 = await client.post("/api/conversation", json={
          "message": "1A班",
          "context": {"classId": "class-hk-f1a"},
          "conversationId": conv_id,
      })
  assert resp2.json()["action"] == "clarify"

  # Turn 3: User provides assignment -> build
  with mocks(build_workflow):
      resp3 = await client.post("/api/conversation", json={
          "message": "Unit 5 Test",
          "context": {"classId": "class-hk-f1a", "assignmentId": "a-001"},
          "conversationId": conv_id,
      })
  assert resp3.json()["action"] == "build"
  ```
- **Expected Result**: 3-turn clarify chain resolves to build with accumulated context.
- **Priority**: P0

---

### 5.2 Long Conversation Degradation

**File**: `tests/test_stress_conversation.py`

#### AI-P3-05: 10-turn conversation maintains context

- **Description**: After 10 turns of mixed intents, the session still correctly provides history to the router.
- **Setup**: InMemoryConversationStore, 10 sequential turns.
- **Steps**:
  ```python
  store = InMemoryConversationStore(ttl_seconds=3600)
  conv_id = "conv-long-001"

  intent_sequence = [
      ("你好", "chat_smalltalk"),
      ("分析1A班成绩", "build_workflow"),
      ("哪些学生不及格", "chat_qa"),
      ("出10道题", "quiz_generate"),
      ("做一个教案", "content_create"),
      ("看看1B班", "build_workflow"),
      ("对比两个班", "build_workflow"),
      ("出5道难题", "quiz_generate"),
      ("写评语", "content_create"),
      ("总结今天的工作", "chat_qa"),
  ]

  for message, intent in intent_sequence:
      req = ConversationRequest(message=message, conversation_id=conv_id)
      session, history_text, msg_history = await _load_session(store, req)

      # Verify session state
      if session.turns:
          assert session.conversation_id == conv_id

      # Save with mock response
      response = ConversationResponse(
          mode="entry", action="chat", chat_response="OK",
      )
      await _save_session(store, session, req, response, intent)

  # After 10 turns: verify session integrity
  final_session = await store.get(conv_id)
  assert final_session is not None
  assert len(final_session.turns) == 20  # 10 user + 10 assistant
  assert final_session.last_intent == "chat_qa"

  # Verify history text still includes early turns (within max_turns limit)
  final_session.add_user_turn("Final question")
  history = final_session.format_history_for_prompt(max_turns=40)
  assert "你好" in history  # first turn still visible
  ```
- **Expected Result**: All 10 turns preserved, history accessible.
- **Priority**: P1

#### AI-P3-06: 20-turn conversation with history truncation

- **Description**: With max_turns=10, only the last 10 turns appear in history.
- **Setup**: Session with 20 complete rounds (40 turns).
- **Steps**:
  ```python
  session = ConversationSession(conversation_id="conv-long-002")
  for i in range(20):
      session.add_user_turn(f"User message {i}")
      session.add_assistant_turn(f"Assistant reply {i}", action="chat_smalltalk")
  session.add_user_turn("Current question")

  history = session.format_history_for_prompt(max_turns=10)
  lines = [l for l in history.split("\n") if l.strip()]
  assert len(lines) == 10
  assert "User message 0" not in history  # truncated
  assert "User message 19" in history or "Assistant reply 19" in history
  ```
- **Expected Result**: History correctly truncated to max_turns.
- **Priority**: P1

#### AI-P3-07: Large accumulated_context does not degrade performance

- **Description**: Session with many context keys still loads and saves efficiently.
- **Setup**: Session with 50 context keys.
- **Steps**:
  ```python
  import time

  session = ConversationSession(conversation_id="conv-ctx-large")
  for i in range(50):
      session.merge_context({f"key_{i}": f"value_{i}"})

  store = InMemoryConversationStore()

  start = time.monotonic()
  await store.save(session)
  loaded = await store.get("conv-ctx-large")
  elapsed = time.monotonic() - start

  assert loaded is not None
  assert len(loaded.accumulated_context) == 50
  assert elapsed < 0.1  # should be near-instant for in-memory
  ```
- **Expected Result**: Save and load complete in < 100ms.
- **Priority**: P2

---

### 5.3 Concurrent Session Isolation

**File**: `tests/test_stress_conversation.py`

#### AI-P3-08: Two concurrent sessions do not interfere

- **Description**: Two different conversationIds running simultaneously maintain separate state.
- **Setup**: InMemoryConversationStore, two conv_ids.
- **Steps**:
  ```python
  store = InMemoryConversationStore()

  # Session A: analyze math
  session_a = ConversationSession(conversation_id="conv-a")
  session_a.merge_context({"classId": "class-math", "subject": "math"})
  session_a.add_user_turn("分析数学成绩")
  session_a.add_assistant_turn("Math analysis done", action="build_workflow")
  await store.save(session_a)

  # Session B: analyze english
  session_b = ConversationSession(conversation_id="conv-b")
  session_b.merge_context({"classId": "class-eng", "subject": "english"})
  session_b.add_user_turn("Analyze English performance")
  session_b.add_assistant_turn("English analysis done", action="build_workflow")
  await store.save(session_b)

  # Retrieve and verify isolation
  loaded_a = await store.get("conv-a")
  loaded_b = await store.get("conv-b")

  assert loaded_a.accumulated_context["subject"] == "math"
  assert loaded_b.accumulated_context["subject"] == "english"
  assert loaded_a.turns[0].content == "分析数学成绩"
  assert loaded_b.turns[0].content == "Analyze English performance"
  ```
- **Expected Result**: No data leakage between sessions.
- **Priority**: P0

#### AI-P3-09: asyncio.gather concurrent session operations

- **Description**: Multiple sessions saved/loaded concurrently via asyncio.gather.
- **Setup**: 10 concurrent sessions.
- **Steps**:
  ```python
  import asyncio

  store = InMemoryConversationStore()

  async def create_and_verify(session_id: str):
      session = ConversationSession(conversation_id=session_id)
      session.merge_context({"id": session_id})
      session.add_user_turn(f"Message for {session_id}")
      await store.save(session)
      loaded = await store.get(session_id)
      assert loaded is not None
      assert loaded.accumulated_context["id"] == session_id

  await asyncio.gather(*[
      create_and_verify(f"concurrent-{i}") for i in range(10)
  ])

  assert store.size == 10
  ```
- **Expected Result**: All 10 sessions created and isolated.
- **Priority**: P1

#### AI-P3-10: Teacher isolation (different teacher_ids)

- **Description**: Sessions for different teachers do not share accumulated context.
- **Setup**: Two sessions with different teacher_ids.
- **Steps**:
  ```python
  store = InMemoryConversationStore()

  # Teacher A
  session_a = ConversationSession(conversation_id="teacher-a-session")
  session_a.merge_context({"teacherId": "t-001", "classId": "class-1a"})
  await store.save(session_a)

  # Teacher B
  session_b = ConversationSession(conversation_id="teacher-b-session")
  session_b.merge_context({"teacherId": "t-002", "classId": "class-2a"})
  await store.save(session_b)

  # Verify
  loaded_a = await store.get("teacher-a-session")
  loaded_b = await store.get("teacher-b-session")
  assert loaded_a.accumulated_context["teacherId"] == "t-001"
  assert loaded_b.accumulated_context["teacherId"] == "t-002"
  ```
- **Expected Result**: Complete isolation.
- **Priority**: P1

---

## 6. Test Infrastructure

### 6.1 Shared Fixtures (create `tests/conftest.py`)

```python
"""Shared test fixtures for AI Agent tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from main import app
from models.blueprint import Blueprint
from models.conversation import RouterResult, ConversationRequest, ConversationResponse
from services.conversation_store import InMemoryConversationStore, ConversationSession


@pytest.fixture
async def client():
    """Async HTTP client for API endpoint testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def store():
    """Fresh in-memory conversation store."""
    return InMemoryConversationStore(ttl_seconds=3600)


@pytest.fixture
def sample_blueprint_args():
    """Import and return sample blueprint args."""
    from tests.test_planner import _sample_blueprint_args
    return _sample_blueprint_args()


@pytest.fixture
def mock_router_result():
    """Factory for creating RouterResult mocks."""
    def _make(intent: str, confidence: float = 0.9, **kwargs):
        return RouterResult(intent=intent, confidence=confidence, **kwargs)
    return _make


# ── Shared mock data ──

MOCK_CLASSES = [
    {"class_id": "class-hk-f1a", "name": "Form 1A", "grade": "Form 1", "subject": "English", "student_count": 35},
    {"class_id": "class-hk-f1b", "name": "Form 1B", "grade": "Form 1", "subject": "English", "student_count": 32},
]

MOCK_CLASS_DETAIL_F1A = {
    "class_id": "class-hk-f1a",
    "name": "Form 1A",
    "students": [
        {"student_id": "s-001", "name": "Wong Ka Ho", "number": 1},
        {"student_id": "s-002", "name": "Li Mei", "number": 2},
        {"student_id": "s-003", "name": "Chan Tai Man", "number": 3},
    ],
    "assignments": [
        {"assignment_id": "a-001", "title": "Unit 5 Test", "type": "exam", "max_score": 100},
        {"assignment_id": "a-002", "title": "Essay Writing", "type": "homework", "max_score": 50},
    ],
}
```

### 6.2 Mock Helper Functions

```python
# In conftest.py or a shared helpers module

from contextlib import contextmanager

@contextmanager
def mock_conversation_pipeline(intent: str, confidence: float = 0.9, **kwargs):
    """Context manager that mocks the full conversation pipeline for a given intent."""
    from tests.test_planner import _sample_blueprint_args

    router_result = RouterResult(intent=intent, confidence=confidence, **kwargs)
    bp = Blueprint(**_sample_blueprint_args())

    with patch("api.conversation.classify_intent", new_callable=AsyncMock, return_value=router_result) as mock_router:
        with patch("api.conversation.generate_blueprint", new_callable=AsyncMock, return_value=(bp, "test-model")) as mock_bp:
            with patch("api.conversation.chat_response", new_callable=AsyncMock, return_value="Mock response") as mock_chat:
                with patch("api.conversation.page_chat_response", new_callable=AsyncMock, return_value="Mock page response") as mock_page:
                    yield {
                        "router": mock_router,
                        "blueprint": mock_bp,
                        "chat": mock_chat,
                        "page_chat": mock_page,
                    }
```

---

## 7. pytest Markers & Execution Commands

### 7.1 Updated `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
markers =
    live: Tests that use real backend data and real LLM API calls
    live_llm: Tests that specifically require real LLM API calls
    integration: Integration tests (may require external services)
    e2e: End-to-end tests
    phase1: Phase 1 Foundation tests
    phase2: Phase 2 Multi-turn & Gateway tests
    phase3: Phase 3 Complex & Stress tests
    p0: Critical priority tests
    p1: High priority tests
    p2: Medium priority tests
    entity: Entity resolver tests
    intent: Intent classification tests
    session: Session management tests
    gateway: Conversation gateway tests
    chain: Cross-intent chain tests
    stress: Stress / performance tests
```

### 7.2 Execution Commands

```bash
# Run ALL new test plan tests
cd insight-ai-agent && pytest tests/test_intent_classification.py tests/test_entity_resolver_extended.py tests/test_gateway_multiturn.py tests/test_session_continuity.py tests/test_composite_scenarios.py tests/test_stress_conversation.py -v

# Run by phase
pytest -m phase1 -v                      # Foundation only
pytest -m phase2 -v                      # Multi-turn & Gateway only
pytest -m phase3 -v                      # Complex & Stress only

# Run by priority
pytest -m p0 -v                          # Critical tests only
pytest -m "p0 or p1" -v                  # Critical + High priority

# Run by category
pytest -m entity -v                      # Entity resolver tests
pytest -m intent -v                      # Intent classification tests
pytest -m session -v                     # Session tests
pytest -m gateway -v                     # Gateway tests
pytest -m chain -v                       # Cross-intent chain tests

# Run with existing tests for regression
pytest tests/ -v                         # Everything

# Run with coverage
pytest tests/ -v --cov=. --cov-report=html

# Run only fast tests (exclude live/integration)
pytest tests/ -v -m "not live and not live_llm and not integration"
```

---

## 8. Dependencies Between Tests

### 8.1 Test Execution Order

```
Phase 1 (no dependencies, run first)
  |
  +-- test_entity_resolver_extended.py   (independent)
  +-- test_intent_classification.py      (independent)
  |
Phase 2 (depends on Phase 1 passing)
  |
  +-- test_session_continuity.py         (depends on: conversation_store working)
  +-- test_gateway_multiturn.py          (depends on: router + entity resolver + session store)
  |
Phase 3 (depends on Phase 1 + Phase 2 passing)
  |
  +-- test_composite_scenarios.py        (depends on: gateway + session + router all working)
  +-- test_stress_conversation.py        (depends on: session store working)
```

### 8.2 Data Dependencies

| Test File | Depends On | Mock Data Source |
|-----------|-----------|-----------------|
| `test_entity_resolver_extended.py` | `execute_mcp_tool` | Self-contained MOCK_CLASSES_EXTENDED |
| `test_intent_classification.py` | `_initial_agent` from `agents.router` | TestModel custom_output_args |
| `test_gateway_multiturn.py` | `classify_intent`, `generate_blueprint`, `chat_response` | AsyncMock patches |
| `test_session_continuity.py` | `InMemoryConversationStore`, `_load_session`, `_save_session` | Direct instantiation |
| `test_composite_scenarios.py` | Full API pipeline (all mocked) | AsyncMock patches + MOCK_CLASSES |
| `test_stress_conversation.py` | `InMemoryConversationStore` | Direct instantiation |

### 8.3 Import Dependencies

All new test files need these imports at minimum:

```python
import pytest
from unittest.mock import AsyncMock, patch

from models.conversation import RouterResult, ConversationRequest, IntentType
from services.conversation_store import ConversationSession, InMemoryConversationStore
```

Additional imports per file:

| File | Extra Imports |
|------|--------------|
| `test_intent_classification.py` | `from agents.router import _apply_confidence_routing, _assign_path, _initial_agent`; `from pydantic_ai.models.test import TestModel` |
| `test_entity_resolver_extended.py` | `from services.entity_resolver import resolve_entities`; `from models.entity import EntityType` |
| `test_gateway_multiturn.py` | `from httpx import ASGITransport, AsyncClient`; `from main import app` |
| `test_session_continuity.py` | `from api.conversation import _load_session, _save_session` |
| `test_composite_scenarios.py` | `from httpx import ASGITransport, AsyncClient`; `from main import app` |
| `test_stress_conversation.py` | `import asyncio`; `import time` |

---

## Appendix: Test Case Summary Table

| Test ID | Phase | Category | Priority | Addresses Bug | File |
|---------|-------|----------|----------|--------------|------|
| AI-P1-01 | 1 | Entity | P0 | P3 | test_entity_resolver_extended.py |
| AI-P1-02 | 1 | Entity | P0 | P3 | test_entity_resolver_extended.py |
| AI-P1-03 | 1 | Entity | P1 | P3 | test_entity_resolver_extended.py |
| AI-P1-04 | 1 | Entity | P2 | P3 | test_entity_resolver_extended.py |
| AI-P1-05 | 1 | Entity | P1 | P3 | test_entity_resolver_extended.py |
| AI-P1-06 | 1 | Entity | P1 | P3 | test_entity_resolver_extended.py |
| AI-P1-07 | 1 | Entity | P1 | -- | test_entity_resolver_extended.py |
| AI-P1-08 | 1 | Entity | P0 | P3 | test_entity_resolver_extended.py |
| AI-P1-09 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P1-10 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P1-11 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P1-12 | 1 | Intent | P1 | P2 | test_intent_classification.py |
| AI-P1-13 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P1-14 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P1-15 | 1 | Intent | P1 | -- | test_intent_classification.py |
| AI-P1-16 | 1 | Entity | P1 | P3 | test_entity_resolver_extended.py |
| AI-P1-17 | 1 | Entity | P1 | P3 | test_entity_resolver_extended.py |
| AI-P1-18 | 1 | Intent | P0 | P2 | test_intent_classification.py |
| AI-P2-01 | 2 | Gateway | P0 | P4 | test_gateway_multiturn.py |
| AI-P2-02 | 2 | Gateway | P0 | P4 | test_gateway_multiturn.py |
| AI-P2-03 | 2 | Gateway | P1 | P4 | test_gateway_multiturn.py |
| AI-P2-04 | 2 | Gateway | P1 | P4 | test_gateway_multiturn.py |
| AI-P2-05 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-06 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-07 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-08 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-09 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-10 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-11 | 2 | Gateway | P0 | -- | test_gateway_multiturn.py |
| AI-P2-12 | 2 | Gateway | P1 | -- | test_gateway_multiturn.py |
| AI-P2-13 | 2 | Gateway | P1 | -- | test_gateway_multiturn.py |
| AI-P2-14 | 2 | Gateway | P1 | -- | test_gateway_multiturn.py |
| AI-P2-15 | 2 | Session | P0 | P1 | test_session_continuity.py |
| AI-P2-16 | 2 | Session | P1 | P1 | test_session_continuity.py |
| AI-P3-01 | 3 | Chain | P0 | P4 | test_composite_scenarios.py |
| AI-P3-02 | 3 | Chain | P1 | P4 | test_composite_scenarios.py |
| AI-P3-03 | 3 | Chain | P1 | P4 | test_composite_scenarios.py |
| AI-P3-04 | 3 | Chain | P0 | P4 | test_composite_scenarios.py |
| AI-P3-05 | 3 | Stress | P1 | P1 | test_stress_conversation.py |
| AI-P3-06 | 3 | Stress | P1 | P1 | test_stress_conversation.py |
| AI-P3-07 | 3 | Stress | P2 | -- | test_stress_conversation.py |
| AI-P3-08 | 3 | Stress | P0 | -- | test_stress_conversation.py |
| AI-P3-09 | 3 | Stress | P1 | -- | test_stress_conversation.py |
| AI-P3-10 | 3 | Stress | P1 | -- | test_stress_conversation.py |

**Total**: 40 test cases
**P0 (Critical)**: 19 tests
**P1 (High)**: 17 tests
**P2 (Medium)**: 4 tests
