---
name: live-test
description: "Live testing skill for real backend data + AI integration tests. Use this for end-to-end validation with production-like conditions."
---

# Live Test Skill

**Announce at start:** "I'm using the live-test skill to perform integration tests with real backend data and AI."

## Purpose

Execute integration and E2E tests using **real Java backend data** (not mock) and **real AI/LLM calls** to validate complete system behavior under production-like conditions.

## When to Use

- Testing new features that depend on backend data (Phase 7+)
- Validating AI-generated content quality
- End-to-end workflow verification
- Pre-deployment sanity checks

## Prerequisites Check

Before running live tests, verify:

1. **Java Backend Availability**
   ```bash
   curl -s http://localhost:8082/dify/teacher/t-test/classes/me | head -20
   ```
   Expected: JSON response with class data

2. **Environment Configuration**
   ```bash
   grep -E "USE_MOCK_DATA|SPRING_BOOT_BASE_URL" .env
   ```
   Expected:
   - `USE_MOCK_DATA=false` (for live tests)
   - `SPRING_BOOT_BASE_URL=http://localhost:8082`

3. **LLM API Key**
   ```bash
   grep "OPENAI_API_KEY\|ANTHROPIC_API_KEY" .env | head -1
   ```
   Expected: Valid API key configured

## Test Execution Workflow

### Step 1: Environment Preparation

```bash
# Ensure real backend mode
export USE_MOCK_DATA=false

# Start Python service if not running
python main.py &
sleep 3
curl -s http://localhost:8000/api/health
```

### Step 2: Run Phase 7 Tests

```bash
# Run all Phase 7 related tests
pytest tests/test_rag_service.py tests/test_knowledge_service.py tests/test_rubric_service.py tests/test_assessment_tools.py tests/test_question_pipeline.py -v --tb=short

# Run with live LLM (mark: live_llm)
pytest tests/ -m "live_llm" -v --tb=short
```

### Step 3: Run E2E Integration Tests

```bash
# Full E2E with real data
pytest tests/test_e2e_page.py tests/test_e2e_phase6.py -v --tb=short

# Specific live tests
pytest tests/test_live_integration.py -v --tb=short
```

### Step 4: Interactive Verification

Use these API calls to manually verify behavior:

```bash
# Test conversation with real data routing
curl -X POST http://localhost:8000/api/conversation \
  -H "Content-Type: application/json" \
  -d '{"message": "分析 1A 班的英语成绩", "language": "zh", "teacherId": "t-test"}'

# Test question generation pipeline
curl -X POST http://localhost:8000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"userPrompt": "给 1A 班生成一套针对阅读理解的练习题", "language": "zh", "context": {"teacherId": "t-test"}}'
```

## Test Categories

### Category 1: Data Layer Tests
- **Focus:** Java backend connectivity, adapter transformations
- **Files:** `tests/test_data_tools.py`, `tests/test_adapters.py`
- **Mark:** `@pytest.mark.integration`

### Category 2: RAG & Knowledge Tests
- **Focus:** Knowledge point retrieval, rubric loading
- **Files:** `tests/test_rag_service.py`, `tests/test_knowledge_service.py`, `tests/test_rubric_service.py`
- **Mark:** `@pytest.mark.rag`

### Category 3: AI Generation Tests
- **Focus:** LLM-powered content generation, quality checks
- **Files:** `tests/test_question_pipeline.py`, `tests/test_executor.py`
- **Mark:** `@pytest.mark.live_llm`

### Category 4: Full Pipeline E2E
- **Focus:** Complete user prompt → page output workflow
- **Files:** `tests/test_e2e_*.py`, `tests/test_live_integration.py`
- **Mark:** `@pytest.mark.e2e`

## Expected Test File Structure

```
tests/
├── test_live_integration.py    # Real backend + AI tests (new)
├── test_rag_service.py         # RAG service unit tests
├── test_knowledge_service.py   # Knowledge point tests
├── test_rubric_service.py      # Rubric loading tests
├── test_assessment_tools.py    # Assessment analysis tests
├── test_question_pipeline.py   # Question generation tests
└── test_e2e_phase6.py          # Phase 6 E2E tests
```

## Failure Handling

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| `ConnectionRefusedError` | Java backend not running | Start Java service on port 8082 |
| `CircuitOpenError` | Backend repeatedly failing | Wait 60s for circuit reset, check Java logs |
| `LLM timeout` | API rate limit or network | Retry with backoff, check API key |
| `ValidationError` on response | Model schema mismatch | Update Pydantic models to match Java API |

## Rules

1. **Never use mock data** during live tests -- set `USE_MOCK_DATA=false`
2. **Record test results** in `docs/testing/` with timestamp
3. **Log failures** with full stack trace and request/response payloads
4. **Clean up test data** after each test run if tests create side effects
5. **Document new test cases** in `docs/testing/use-cases.md`

## Reporting

After test completion, generate a summary:

```bash
# Generate test report
pytest tests/ -v --tb=short --html=docs/testing/report-$(date +%Y%m%d).html

# Or text summary
pytest tests/ -v --tb=short > docs/testing/report-$(date +%Y%m%d).txt 2>&1
```

## Common Live Test Scenarios

### Scenario 1: Analyze Class Performance
```python
# Expected flow: Router → build_workflow → PlannerAgent → Blueprint
message = "分析 1A 班的英语成绩表现"
# Verify: Blueprint contains data_contract with get_teacher_classes + get_class_detail
```

### Scenario 2: Generate Targeted Questions
```python
# Expected flow: assess weakness → fetch rubric → question pipeline
message = "根据学生弱项为 1A 班生成练习题"
# Verify: Questions target identified weak knowledge points
```

### Scenario 3: Refine Page Content
```python
# Expected flow: Router (followup) → refine → PatchAgent → patch plan
message = "把分析内容缩短一半"
context = {"blueprint": {...}, "pageContext": {...}}
# Verify: Returns patch_plan with scope=patch_compose
```
