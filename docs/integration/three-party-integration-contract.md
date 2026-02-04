# 三方集成契约规范

> Insight AI Agent 前端 ↔ Python 后端 ↔ Java 后端完整对接规范

**文档版本**: v1.0
**创建日期**: 2026-02-04
**适用阶段**: Phase 6+ (前端集成)
**目标读者**: 前端开发、Python 开发、Java 开发、测试工程师

---

## 总览

### 三方定位

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  前端 Next.js │ ←──▶ │ Python FastAPI│ ←──▶ │ Java Spring  │
│              │      │              │      │   Boot       │
│  用户交互     │      │  AI 编排     │      │  数据服务    │
│  SSE 消费     │      │  Blueprint   │      │  权限控制    │
│  页面渲染     │      │  页面执行    │      │  业务规则    │
└──────────────┘      └──────────────┘      └──────────────┘
     Client               Orchestrator           Data Layer
```

### 数据流向

**用户请求流 (Build Workflow)**:
```
用户输入 "分析 1A 班英语成绩"
    ↓
前端: POST /api/ai/conversation
    ↓
Python: RouterAgent 意图分类 → build_workflow
    ↓
Python: EntityResolver 解析 "1A" → classId
    ↓
Python: PlannerAgent 生成 Blueprint
    ↓
前端: 收到 ConversationResponse (action: build, blueprint: {...})
    ↓
前端: POST /api/ai/page/generate (SSE)
    ↓
Python: ExecutorAgent Phase A (Data Binding)
    ├─ Java: GET /dify/teacher/t-001/classes/me
    └─ Java: GET /dify/teacher/t-001/classes/class-1a
    ↓
Python: ExecutorAgent Phase B (Compute)
    ├─ calculate_stats (numpy)
    └─ 生成 KPI / Chart 数据
    ↓
Python: ExecutorAgent Phase C (Compose)
    ├─ SSE: BLOCK_START (markdown)
    ├─ SSE: SLOT_DELTA ("## 分析总结...")
    ├─ SSE: BLOCK_COMPLETE (markdown)
    └─ SSE: COMPLETE (page: {...})
    ↓
前端: 渲染 Page (6 种 Block 组件)
```

---

## 1. 前端 ↔ Python 后端集成

### 1.1 API Proxy 路由

**前端 Next.js API Routes** (`app/api/ai/[...path]/route.ts`):

```typescript
// 代理所有 /api/ai/* 请求到 Python 后端
export async function POST(request: Request, { params }: { params: { path: string[] } }) {
  const pythonBackendUrl = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';
  const path = params.path.join('/');
  const targetUrl = `${pythonBackendUrl}/api/${path}`;

  const body = await request.json();

  // 转发请求
  const response = await fetch(targetUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  // SSE 流式响应
  if (response.headers.get('content-type')?.includes('text/event-stream')) {
    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  }

  // 普通 JSON 响应
  const data = await response.json();
  return Response.json(data);
}
```

**环境变量** (`.env.local`):
```bash
PYTHON_BACKEND_URL=http://localhost:8000  # 开发环境
# PYTHON_BACKEND_URL=https://api-python.insightai.hk  # 生产环境
```

### 1.2 核心端点映射

| 前端调用 | 代理到 Python | 用途 | 响应类型 |
|---------|--------------|------|---------|
| `POST /api/ai/conversation` | `POST /api/conversation` | 统一会话入口 | JSON |
| `POST /api/ai/workflow/generate` | `POST /api/workflow/generate` | 直调生成 Blueprint | JSON |
| `POST /api/ai/page/generate` | `POST /api/page/generate` | 执行 Blueprint → Page | SSE |
| `POST /api/ai/page/patch` | `POST /api/page/patch` | 增量修改 (Patch) | SSE |
| `GET /api/ai/health` | `GET /api/health` | 健康检查 | JSON |

### 1.3 Request/Response 契约

#### 1.3.1 统一会话 — `POST /api/conversation`

**Request** (TypeScript):
```typescript
interface ConversationRequest {
  message: string;                      // 用户消息
  language?: string;                    // "en" | "zh-CN"
  teacherId?: string;                   // 教师 ID (可选，从 session 获取)
  context?: Record<string, any> | null; // clarify 选择结果
  blueprint?: Blueprint | null;         // 追问模式时传入
  pageContext?: {                       // 追问模式时传入
    meta: { pageTitle: string };
    dataSummary: string;
  } | null;
  conversationId?: string | null;       // 会话 ID
}
```

**Response** (TypeScript):
```typescript
interface ConversationResponse {
  // 结构化字段 (Phase 4.5.3 新增)
  mode: 'entry' | 'followup';
  action: 'chat' | 'build' | 'clarify' | 'refine' | 'rebuild';
  chatKind: 'smalltalk' | 'qa' | 'page' | null;

  // 向下兼容字段
  legacyAction: 'chat_smalltalk' | 'chat_qa' | 'build_workflow' | 'clarify' | 'chat' | 'refine' | 'rebuild';

  // 核心字段
  chatResponse: string | null;          // 文本回复 (Markdown)
  blueprint: Blueprint | null;          // build/refine/rebuild 时有值
  patchPlan: PatchPlan | null;          // refine 时可能有值 (Phase 6)
  clarifyOptions: ClarifyOptions | null; // clarify 时有值
  conversationId: string | null;
  resolvedEntities: ResolvedEntity[] | null; // 已解析实体 (Phase 4.5)
}
```

**前端处理逻辑** (TypeScript):
```typescript
const response = await fetch('/api/ai/conversation', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    message: userInput,
    teacherId: session.user.teacherId,
    language: 'zh-CN',
  }),
});

const data: ConversationResponse = await response.json();

switch (data.action) {
  case 'chat':
    // 显示 chatResponse (Markdown)
    setMessages([...messages, { role: 'assistant', content: data.chatResponse }]);
    break;

  case 'build':
    // 拿到 Blueprint，调用 /api/ai/page/generate
    setBlueprint(data.blueprint);
    // 如果 dataContract.inputs 不为空，先渲染数据选择 UI
    // 否则直接调用 page/generate
    break;

  case 'clarify':
    // 渲染交互式选项 UI
    setClarifyOptions(data.clarifyOptions);
    break;

  case 'refine':
    // 检查 patchPlan
    if (data.patchPlan) {
      // 调用 /api/ai/page/patch (Patch 模式)
      await fetchPagePatch(data.blueprint, currentPage, data.patchPlan);
    } else {
      // 调用 /api/ai/page/generate (Full Rebuild 模式)
      await fetchPageGenerate(data.blueprint);
    }
    break;

  case 'rebuild':
    // 显示 chatResponse 说明变更，用户确认后调用 page/generate
    setRebuildConfirmation({ message: data.chatResponse, blueprint: data.blueprint });
    break;
}
```

#### 1.3.2 生成页面 — `POST /api/page/generate` (SSE)

**Request** (TypeScript):
```typescript
interface PageGenerateRequest {
  blueprint: Blueprint;                 // 从 conversation 获得
  context?: Record<string, any> | null; // { teacherId, classId, assignmentId, ... }
  teacherId?: string;
}
```

**Response**: SSE 事件流

**前端 SSE 消费代码** (TypeScript):
```typescript
const eventSource = new EventSource('/api/ai/page/generate', {
  method: 'POST', // 注意: EventSource 原生不支持 POST，需使用 fetch + ReadableStream
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ blueprint, context: { teacherId: 't-001' } }),
});

// 实际实现 (使用 fetch + ReadableStream)
const response = await fetch('/api/ai/page/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ blueprint, context }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n');
  buffer = lines.pop() || '';

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));

    handleSSEEvent(event); // 见 1.3.3
  }
}
```

#### 1.3.3 SSE 事件处理

**事件类型** (TypeScript):
```typescript
type SSEEvent =
  | { type: 'PHASE'; phase: 'data' | 'compute' | 'compose'; message: string }
  | { type: 'TOOL_CALL'; tool: string; args: Record<string, any> }
  | { type: 'TOOL_RESULT'; tool: string; status: 'success' | 'error' }
  | { type: 'BLOCK_START'; blockId: string; componentType: string }
  | { type: 'SLOT_DELTA'; blockId: string; slotKey: string; deltaText: string }
  | { type: 'BLOCK_COMPLETE'; blockId: string }
  | { type: 'COMPLETE'; message: string; progress: 100; result: PageResult }
  | { type: 'ERROR'; message: string; code: string; details?: any }
  | { type: 'DATA_ERROR'; entity: string; entityType: string; message: string; suggestions: Array<{ label: string; value: string }> };
```

**事件处理器** (React 示例):
```typescript
function handleSSEEvent(event: SSEEvent) {
  switch (event.type) {
    case 'PHASE':
      setProgress({ phase: event.phase, message: event.message });
      break;

    case 'BLOCK_START':
      // 显示 block loading 状态
      setBlockStates((prev) => ({
        ...prev,
        [event.blockId]: { status: 'loading', componentType: event.componentType },
      }));
      break;

    case 'SLOT_DELTA':
      // 逐字符拼接 AI 内容 (打字机效果)
      setBlocks((prev) => {
        const block = prev.find((b) => b.id === event.blockId);
        if (!block) return prev;
        return prev.map((b) =>
          b.id === event.blockId
            ? { ...b, [event.slotKey]: (b[event.slotKey] || '') + event.deltaText }
            : b
        );
      });
      break;

    case 'BLOCK_COMPLETE':
      // 结束 block loading 状态
      setBlockStates((prev) => ({
        ...prev,
        [event.blockId]: { status: 'completed' },
      }));
      break;

    case 'COMPLETE':
      // 解析最终页面
      setPage(event.result.page);
      setCachedDataContext(event.result.dataContext); // 缓存 Data Context (用于 Patch)
      setCachedComputeResults(event.result.computeResults); // 缓存 Compute Results
      break;

    case 'ERROR':
      // 显示错误信息
      showErrorToast(event.message, event.code);
      break;

    case 'DATA_ERROR':
      // 显示实体不存在错误 + suggestions
      showDataErrorDialog({
        entity: event.entity,
        message: event.message,
        suggestions: event.suggestions,
      });
      break;

    case 'TOOL_CALL':
    case 'TOOL_RESULT':
      // 可选: 显示工具调用日志 (调试用)
      console.log(`[${event.type}]`, event);
      break;
  }
}
```

### 1.4 TypeScript 类型定义

**完整类型定义文件** (`frontend/types/api.ts`):

参考 [frontend-integration.md TypeScript 类型定义](frontend-integration.md#typescript-类型定义)

**自动生成策略** (推荐):
```bash
# Python 后端执行
pydantic2ts --module models.blueprint --output frontend/types/blueprint.ts
pydantic2ts --module models.conversation --output frontend/types/conversation.ts
pydantic2ts --module models.data --output frontend/types/data.ts
pydantic2ts --module models.patch --output frontend/types/patch.ts

# 集成到 CI/CD
# .github/workflows/generate-types.yml
```

### 1.5 前端缓存策略

| 数据 | 存储位置 | 生命周期 | 用途 |
|------|---------|---------|------|
| **Blueprint** | React State / Zustand | 会话期间 | 传递给 page/generate 和 page/patch |
| **Page** | React State | 会话期间 | 当前渲染的页面 |
| **Data Context** | React State | 会话期间 | Patch 时复用，避免重新调用 Java API |
| **Compute Results** | React State | 会话期间 | Patch 时复用，避免重新计算 |
| **Conversation ID** | Session Storage | 跨页面会话 | 多轮对话追踪 |
| **Teacher ID** | Session / Cookie | 登录期间 | 自动注入所有请求 |

**State 管理示例** (Zustand):
```typescript
import create from 'zustand';

interface AIState {
  blueprint: Blueprint | null;
  page: Page | null;
  dataContext: Record<string, any> | null;
  computeResults: Record<string, any> | null;

  setBlueprint: (blueprint: Blueprint) => void;
  setPage: (page: Page) => void;
  setDataContext: (context: Record<string, any>) => void;
  setComputeResults: (results: Record<string, any>) => void;
}

export const useAIStore = create<AIState>((set) => ({
  blueprint: null,
  page: null,
  dataContext: null,
  computeResults: null,

  setBlueprint: (blueprint) => set({ blueprint }),
  setPage: (page) => set({ page }),
  setDataContext: (dataContext) => set({ dataContext }),
  setComputeResults: (computeResults) => set({ computeResults }),
}));
```

---

## 2. Python 后端 ↔ Java 后端集成

### 2.1 认证机制

**Bearer Token 认证**:
```python
# Python 后端配置 (config/settings.py)
class Settings(BaseSettings):
    spring_boot_base_url: str = "https://api.insightai.hk"
    spring_boot_api_prefix: str = "/api"
    spring_boot_access_token: str = Field(..., env="SPRING_BOOT_ACCESS_TOKEN")
    spring_boot_refresh_token: str = Field(..., env="SPRING_BOOT_REFRESH_TOKEN")
    spring_boot_timeout: int = 15

# Java 客户端 (services/java_client.py)
class JavaClient:
    def __init__(self, settings: Settings):
        self.base_url = f"{settings.spring_boot_base_url}{settings.spring_boot_api_prefix}"
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=settings.spring_boot_timeout,
            headers={"Authorization": f"Bearer {settings.spring_boot_access_token}"},
        )
```

### 2.2 Java API 端点清单

| Method | Path | 功能 | Adapter | 对应 Tool |
|--------|------|------|---------|----------|
| `GET` | `/dify/teacher/{id}/classes/me` | 教师班级列表 | `class_adapter.list_classes()` | `get_teacher_classes` |
| `GET` | `/dify/teacher/{id}/classes/{classId}` | 班级详情 | `class_adapter.get_detail()` | `get_class_detail` |
| `GET` | `/dify/teacher/{id}/classes/{classId}/assignments` | 班级作业列表 | `class_adapter.list_assignments()` | `get_class_detail` (assignments) |
| `GET` | `/dify/teacher/{id}/submissions/assignments/{assignmentId}` | 作业提交记录 | `submission_adapter.get_submissions()` | `get_assignment_submissions` |
| `GET` | `/dify/teacher/{id}/submissions/students/{studentId}` | 学生成绩 | `grade_adapter.get_student_submissions()` | `get_student_grades` |

### 2.3 Java 响应格式

**标准响应包装** (`Result<T>`):
```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "timestamp": "2026-02-04T10:00:00"
}
```

**错误响应**:
```json
{
  "code": 404,
  "message": "Class not found",
  "data": null,
  "timestamp": "2026-02-04T10:00:00"
}
```

**Adapter 解包逻辑** (Python):
```python
def _unwrap_data(response_json: dict) -> dict:
    """
    解包 Java Result<T> 包装格式
    """
    if response_json.get("code") != 200:
        raise JavaClientError(f"Java API error: {response_json.get('message')}")
    return response_json.get("data")
```

### 2.4 数据模型映射

#### 2.4.1 班级数据

**Java DTO** (`ClassroomDTO`):
```json
{
  "uid": "class-hk-f1a",
  "id": "123",
  "name": "Form 1A",
  "grade": "Form 1",
  "subject": "English",
  "student_count": 35,
  "teacher_id": "t-001",
  "academic_year": "2025-2026"
}
```

**Python Internal Model** (`models/data.py`):
```python
class ClassInfo(CamelModel):
    class_id: str               # uid > id
    name: str
    grade: str
    subject: str
    student_count: int
    teacher_id: str
    academic_year: str | None = None
```

**Adapter 转换** (`adapters/class_adapter.py`):
```python
def _parse_class_info(dto: dict) -> ClassInfo:
    return ClassInfo(
        class_id=dto.get("uid") or dto.get("id"),  # 优先 uid
        name=dto["name"],
        grade=dto["grade"],
        subject=dto["subject"],
        student_count=dto["student_count"],
        teacher_id=dto["teacher_id"],
        academic_year=dto.get("academic_year"),
    )
```

**Frontend TypeScript** (自动生成):
```typescript
interface ClassInfo {
  classId: string;  // camelCase
  name: string;
  grade: string;
  subject: string;
  studentCount: number;
  teacherId: string;
  academicYear?: string;
}
```

#### 2.4.2 作业提交数据

**Java DTO** (`SubmissionDTO`):
```json
{
  "student_id": "s-001",
  "student_name": "Wong Ka Ho",
  "score": 58.0,
  "max_score": 100.0,
  "submitted_at": "2026-01-15T14:30:00",
  "status": "graded",
  "feedback": "Need improvement in grammar"
}
```

**Python Internal Model**:
```python
class SubmissionRecord(CamelModel):
    student_id: str
    student_name: str
    score: float
    max_score: float
    submitted_at: str
    status: str
    feedback: str | None = None
```

**Frontend TypeScript**:
```typescript
interface SubmissionRecord {
  studentId: string;
  studentName: string;
  score: number;
  maxScore: number;
  submittedAt: string;
  status: string;
  feedback?: string;
}
```

### 2.5 错误处理和重试机制

#### 2.5.1 重试策略

**配置** (`services/java_client.py`):
```python
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # 秒
RETRY_BACKOFF_FACTOR = 2  # 指数退避

async def get(self, path: str) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            response = await self.client.get(path)
            response.raise_for_status()
            return response.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500:
                # 4xx 客户端错误，不重试
                raise
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_FACTOR ** attempt)
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES} after {delay}s: {e}")
                await asyncio.sleep(delay)
            else:
                raise
```

#### 2.5.2 熔断器 (Circuit Breaker)

**状态机**:
```
CLOSED (正常) ──5 连续失败──▶ OPEN (快速失败)
     ▲                             │
     │                             │ 60s 后
     └──── 成功恢复 ◀─── HALF_OPEN (探测)
```

**实现** (`services/java_client.py`):
```python
CIRCUIT_OPEN_THRESHOLD = 5
CIRCUIT_RESET_TIMEOUT = 60  # 秒

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class JavaClient:
    def __init__(self, settings: Settings):
        self.circuit_state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    async def get(self, path: str) -> dict:
        # 检查熔断器状态
        if self.circuit_state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > CIRCUIT_RESET_TIMEOUT:
                self.circuit_state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: HALF_OPEN (探测恢复)")
            else:
                raise CircuitOpenError("Circuit breaker is OPEN")

        try:
            response = await self._do_request(path)
            # 成功，重置计数器
            if self.circuit_state == CircuitState.HALF_OPEN:
                self.circuit_state = CircuitState.CLOSED
                logger.info("Circuit breaker: CLOSED (恢复正常)")
            self.failure_count = 0
            return response
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= CIRCUIT_OPEN_THRESHOLD:
                self.circuit_state = CircuitState.OPEN
                logger.error(f"Circuit breaker: OPEN (连续 {self.failure_count} 次失败)")
            raise
```

#### 2.5.3 降级到 Mock 数据

**优先级**:
1. Java 后端正常 → 返回真实数据
2. Java 后端不可用 + 重试失败 → 降级 Mock
3. 熔断器打开 → 快速失败 → 降级 Mock

**Tools 层降级逻辑** (`tools/data_tools.py`):
```python
async def get_teacher_classes(teacher_id: str) -> dict:
    if _should_use_mock():
        # 强制使用 Mock (USE_MOCK_DATA=true)
        return _mock_teacher_classes(teacher_id)

    try:
        client = get_java_client()
        classes = await class_adapter.list_classes(client, teacher_id)
        return {"teacher_id": teacher_id, "classes": [c.model_dump() for c in classes]}
    except (JavaClientError, CircuitOpenError, httpx.HTTPError):
        # Java 后端不可用，降级 Mock
        logger.exception("get_teacher_classes failed, falling back to mock")
        return _mock_teacher_classes(teacher_id)
```

### 2.6 性能要求

| 指标 | 目标值 | 说明 |
|------|-------|------|
| **单次 API 调用 P50** | < 100ms | 中位数响应时间 |
| **单次 API 调用 P90** | < 300ms | 90 分位响应时间 |
| **单次 API 调用 P99** | < 500ms | 99 分位响应时间 |
| **超时阈值** | 15s (可配置) | 触发 Timeout 错误 |
| **并发连接数** | 50 (可配置) | httpx.AsyncClient 连接池大小 |

**监控埋点** (Python):
```python
import time
import logging

logger = logging.getLogger(__name__)

async def get(self, path: str) -> dict:
    start_time = time.time()
    try:
        response = await self.client.get(path)
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"GET {path} → {response.status_code} ({elapsed_ms:.0f}ms)")
        return response.json()
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"GET {path} → ERROR ({elapsed_ms:.0f}ms): {e}")
        raise
```

---

## 3. 跨团队协调规范

### 3.1 API 变更流程

**原则**: 后向兼容，版本化管理

#### 3.1.1 Java API 变更

**场景**: Java 后端需要修改 `/dify/teacher/{id}/classes/me` 响应字段

**流程**:
1. **Java 团队**: 在 API 文档中标注变更 (CHANGELOG)
2. **Java 团队**: 提供迁移期兼容方案 (同时返回旧字段和新字段)
3. **Python 团队**: 更新 Adapter 层支持新字段，保持对旧字段的兼容
4. **Java 团队**: 在一定迁移期后移除旧字段

**示例**:
```json
// 旧版本 (deprecated)
{
  "class_id": "123",
  "name": "Form 1A"
}

// 新版本 (兼容期同时返回)
{
  "uid": "class-hk-f1a",  // 新增
  "class_id": "123",       // deprecated
  "id": "123",             // deprecated
  "name": "Form 1A"
}

// 最终版本 (移除旧字段)
{
  "uid": "class-hk-f1a",
  "name": "Form 1A"
}
```

**Python Adapter 适配**:
```python
def _parse_class_info(dto: dict) -> ClassInfo:
    # 兼容旧字段 class_id/id 和新字段 uid
    class_id = dto.get("uid") or dto.get("class_id") or dto.get("id")
    if not class_id:
        raise ValueError("Missing class identifier (uid/class_id/id)")
    return ClassInfo(class_id=class_id, ...)
```

#### 3.1.2 Python API 变更

**场景**: Python 后端需要修改 SSE 事件格式

**流程**:
1. **Python 团队**: 在 API 文档中标注变更 (CHANGELOG)
2. **Python 团队**: 引入新事件类型，保留旧事件类型 (兼容期)
3. **前端团队**: 更新事件处理器支持新事件
4. **Python 团队**: 在一定迁移期后移除旧事件类型

**示例**:
```python
# Phase 5: MESSAGE 事件 (deprecated)
yield {"type": "MESSAGE", "content": "分析总结..."}

# Phase 6: 新增 BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE (替代 MESSAGE)
yield {"type": "BLOCK_START", "blockId": "summary", "componentType": "markdown"}
yield {"type": "SLOT_DELTA", "blockId": "summary", "slotKey": "content", "deltaText": "分析总结..."}
yield {"type": "BLOCK_COMPLETE", "blockId": "summary"}

# 兼容期: 同时发送旧事件和新事件 (前端可选择消费)
# 最终: 只发送新事件
```

### 3.2 错误码协调

**统一错误码表** (三方共同维护):

| 错误码 | 来源 | 含义 | 前端处理 |
|--------|------|------|---------|
| `DATA_ERROR` | Python (转换自 Java 5xx) | 数据获取失败 | 显示 "数据获取失败" |
| `AUTH_ERROR` | Python (转换自 Java 403) | 权限不足 | 重定向登录 |
| `SERVICE_UNAVAILABLE` | Python (Circuit Breaker) | 服务不可用 | 显示 "服务暂时不可用" |
| `VALIDATION_ERROR` | Python (Pydantic) / Java (400) | 参数校验失败 | 显示字段错误 |
| `ENTITY_NOT_FOUND` | Python (EntityResolver) | 实体不存在 | 显示建议选项 |
| `AI_ERROR` | Python (LLM) | AI 服务失败 | 显示 "AI 服务暂时不可用" |
| `BLUEPRINT_ERROR` | Python (Planner) | Blueprint 解析失败 | 显示 "任务规划失败" |

### 3.3 测试协调

#### 3.3.1 E2E 测试分工

| 测试场景 | 负责方 | 测试环境 |
|---------|-------|---------|
| **Java API 单元测试** | Java 团队 | Java 测试环境 |
| **Python Tools 集成测试** | Python 团队 | Mock Java API |
| **Python E2E 测试** | Python 团队 | Mock Java API + 真实 LLM |
| **前端组件测试** | 前端团队 | Mock Python API |
| **前端 E2E 测试** | 前端团队 | Staging Python API |
| **全链路 E2E 测试** | 测试团队 (联调) | Staging 环境 (真实三方) |

#### 3.3.2 联调环境

| 环境 | Java 后端 | Python 后端 | 前端 | 数据库 |
|------|-----------|-------------|------|--------|
| **本地开发** | Mock / Local | Local | Local | Mock 数据 |
| **开发环境 (Dev)** | Dev 服务器 | Dev 服务器 | Local / Dev | Dev 数据库 |
| **测试环境 (Staging)** | Staging 服务器 | Staging 服务器 | Staging | Staging 数据库 |
| **生产环境 (Prod)** | Prod 服务器 | Prod 服务器 | Prod | Prod 数据库 |

---

## 4. 部署和监控

### 4.1 服务部署架构

```
┌─────────────────────────────────────────────────┐
│  Nginx / Ingress                                 │
│  - frontend.insightai.hk → Next.js               │
│  - api-python.insightai.hk → Python FastAPI      │
│  - api-java.insightai.hk → Java SpringBoot       │
└─────────────────────────────────────────────────┘
        │               │               │
        ▼               ▼               ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Next.js  │◀───│ Python   │◀───│ Java     │
│ (Node.js)│    │ (FastAPI)│    │ (Spring) │
└──────────┘    └──────────┘    └──────────┘
                       │                 │
                       ▼                 ▼
                ┌──────────┐    ┌──────────┐
                │ Redis    │    │ MySQL    │
                │ (缓存)    │    │ (持久化)  │
                └──────────┘    └──────────┘
```

### 4.2 监控指标

| 指标类型 | 指标名称 | 监控工具 | 告警阈值 |
|---------|---------|---------|---------|
| **可用性** | 服务健康检查 | Kubernetes Liveness Probe | 连续 3 次失败 |
| **响应时间** | API P99 响应时间 | Prometheus + Grafana | > 5s |
| **错误率** | HTTP 5xx 错误率 | Prometheus | > 1% |
| **并发数** | 活跃 SSE 连接数 | Prometheus | > 1000 |
| **Java 后端调用** | JavaClient 成功率 | Prometheus | < 95% |
| **熔断器状态** | Circuit Breaker OPEN 事件 | Prometheus | 发生即告警 |
| **LLM 调用** | LLM API 成功率 | Prometheus | < 90% |
| **LLM 调用** | LLM API 平均延迟 | Prometheus | > 10s |

### 4.3 日志规范

**日志格式** (JSON 结构化日志):
```json
{
  "timestamp": "2026-02-04T10:00:00.123Z",
  "level": "INFO",
  "service": "python-backend",
  "traceId": "abc123",
  "message": "GET /api/conversation completed",
  "context": {
    "teacherId": "t-001",
    "action": "build",
    "duration_ms": 234
  }
}
```

**Trace ID 传递**:
```
前端: X-Trace-ID → Python: X-Trace-ID → Java: X-Trace-ID
                     ↓
              (传递给 LLM metadata)
```

---

## 5. 安全和权限

### 5.1 认证链路

```
用户登录
    ↓
前端: 获取 JWT Token (from Auth Service)
    ↓
前端: 请求携带 JWT → Next.js API Routes
    ↓
Next.js: 验证 JWT → 提取 teacherId
    ↓
Next.js: 转发请求到 Python (携带 teacherId)
    ↓
Python: 转发请求到 Java (携带 teacherId + Bearer Token)
    ↓
Java: 验证 teacherId 权限 → 返回数据
```

### 5.2 数据权限

**原则**: 教师只能访问自己的班级数据

**Java 后端职责**:
- 验证 `teacherId` 与 `classId` 的归属关系
- 返回 403 Forbidden 如果教师无权访问

**Python 后端职责**:
- 传递 `teacherId` 到 Java API
- 处理 403 错误，转换为友好提示

**前端职责**:
- 从 Session 中提取 `teacherId`
- 显示权限错误提示

---

## 附录

### A. 快速参考速查表

#### A.1 前端调用流程

```typescript
// 1. 会话入口
const response = await fetch('/api/ai/conversation', {
  method: 'POST',
  body: JSON.stringify({ message: '分析 1A 班英语成绩', teacherId: 't-001' }),
});
const data: ConversationResponse = await response.json();

// 2. 根据 action 处理
if (data.action === 'build') {
  // 3. 生成页面 (SSE)
  const response = await fetch('/api/ai/page/generate', {
    method: 'POST',
    body: JSON.stringify({ blueprint: data.blueprint, context: { teacherId: 't-001' } }),
  });
  // 4. 消费 SSE 事件流
  const reader = response.body.getReader();
  // ...
}
```

#### A.2 Python 对接 Java 流程

```python
# 1. 通过 Tools 调用
from tools.data_tools import get_teacher_classes
classes = await get_teacher_classes(teacher_id="t-001")

# 2. Tools 内部通过 Adapter 调用 Java
from adapters.class_adapter import list_classes
from services.java_client import get_java_client
client = get_java_client()
classes = await list_classes(client, teacher_id="t-001")

# 3. Adapter 调用 JavaClient
response = await client.get("/dify/teacher/t-001/classes/me")

# 4. JavaClient 执行 HTTP 请求 (retry + circuit breaker)
async with httpx.AsyncClient() as client:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
```

### B. 常见问题 (FAQ)

**Q: 前端可以直接调用 Java API 吗？**
A: ❌ 不可以。必须通过 Python 编排层，由 Python 负责实体解析、权限验证、错误处理。

**Q: Python 后端缓存 Java API 响应吗？**
A: 部分缓存。Teacher Classes 短时缓存 (5 分钟)，其他数据不缓存 (实时性要求高)。

**Q: SSE 连接断开后如何恢复？**
A: 前端重新发起 `/api/page/generate` 请求。Blueprint 和 Context 在前端缓存，可快速重建。

**Q: Phase 8 升级会破坏现有 API 吗？**
A: ❌ 不会。通过 Feature Flag 渐进式升级，现有路径完全兼容。

**Q: Java API 变更需要通知前端吗？**
A: ❌ 不需要。Java → Python Adapter 隔离变化，前端不感知 Java 变更。

**Q: 如何排查 Java 后端调用失败？**
A: 查看 Python 日志，关键字 `JavaClient`、`Circuit Breaker`、`falling back to mock`。

---

**文档维护者**: 架构团队
**最后更新**: 2026-02-04
**版本历史**:
- v1.0 (2026-02-04): 初版发布，基于 Phase 7 完成状态
