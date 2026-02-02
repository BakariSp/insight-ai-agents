# 前端集成规范

> Next.js Proxy 架构、字段映射、前端改动清单、Mock 策略、Proxy 路由代码、错误处理、测试检查清单。

---

## 三层架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: React Pages & Components (不改)                        │
│                                                                    │
│  build/[id]/page.tsx     apps/[id]/page.tsx                       │
│       │                        │                                   │
│       ▼                        ▼                                   │
│  ┌──────────────────────────────────────────────┐                 │
│  │  studio-agents.ts (客户端调用层)               │                 │
│  │  generateWorkflow()   → fetch /api/ai/...    │                 │
│  │  generateReport()     → fetch /api/ai/...    │                 │
│  │  chatWithReport()     → fetch /api/ai/...    │                 │
│  │  handleSSEStream()    → parse SSE events     │                 │
│  └──────────────┬───────────────────────────────┘                 │
│                 │  fetch('/api/ai/xxx')                            │
│                 ▼                                                  │
│  ┌──────────────────────────────────────────────┐                 │
│  │  Layer 2: Next.js API Routes (改为 Proxy)     │ ← 唯一改动层    │
│  │  /api/ai/workflow-generate  → proxy           │                 │
│  │  /api/ai/report-generate    → proxy + SSE     │                 │
│  │  /api/ai/report-chat        → proxy           │                 │
│  │  /api/ai/classify-intent    → proxy (新增)    │                 │
│  └──────────────┬───────────────────────────────┘                 │
└─────────────────┼────────────────────────────────────────────────┘
                  │  HTTP / SSE
                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3: Python Service (FastAPI + PydanticAI)                   │
└──────────────────────────────────────────────────────────────────┘
```

**核心原则：前端 React 层零改动。** 所有变化封装在 Next.js API Routes 这一层。

---

## Blueprint 概念（面向前端开发者）

详细模型定义见 [Blueprint 数据模型](../architecture/blueprint-model.md)。

**前端只关心两部分：**

1. **`blueprint.dataContract.inputs`** — 渲染数据选择 UI。格式与原来的 `dataInputs` 完全一致。
2. **`blueprint` 整体** — 回传给 `/api/report/generate` 执行。前端不需要理解 `computeGraph` 或 `uiComposition`。

**报告输出格式完全不变。** `COMPLETE.result.report` 仍然是 `{ meta, layout, tabs: [{ id, label, blocks }] }`。

---

## 前端改动清单 (最小化)

### 必须改的文件 (4 个 API routes)

| 文件 | 改动内容 | 行数 |
|------|---------|------|
| `src/app/api/ai/workflow-generate/route.ts` | Dify → Python proxy，response 用 `blueprint` | ~30 行 |
| `src/app/api/ai/report-generate/route.ts` | Dify SSE → Python SSE 透传，request 含 `blueprint` | ~25 行 |
| `src/app/api/ai/report-chat/route.ts` | Dify → Python proxy | ~20 行 |
| `src/lib/env.ts` | 添加 `PYTHON_SERVICE_URL` | ~3 行 |

### 新增的文件 (1 个)

| 文件 | 内容 |
|------|------|
| `src/app/api/ai/classify-intent/route.ts` | 意图分类 proxy (新端点) |

### 需要小改的文件 (1-2 个，可选)

| 文件 | 改动内容 |
|------|---------|
| `src/lib/studio-agents.ts` | `generateWorkflow()` 返回值从 `result.workflow` 改为 `result.blueprint` |
| `src/lib/studio-router.ts` | `getRouteType()` 改为 async，调用 `/api/ai/classify-intent` |

### 完全不改的文件

| 文件 | 原因 |
|------|------|
| `src/lib/studio-agents.ts` (handleSSEStream) | SSE 解析逻辑不变 |
| `src/components/studio/*` | 所有 UI 组件不改 |
| `src/components/studio/report-renderer/*` | 报告渲染组件不改 |
| `src/app/teacher/studio/**` | 所有页面不改 |

---

## Proxy Route 完整代码

### `workflow-generate/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';
import { getDefaultWorkflowTemplate } from '@/config/studio-agent-prompts';

export const runtime = 'nodejs';
export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const { userPrompt } = await request.json();

    if (!userPrompt || typeof userPrompt !== 'string') {
      return NextResponse.json(
        { success: false, error: 'userPrompt is required' },
        { status: 400 }
      );
    }

    const { PYTHON_SERVICE_URL } = getServerConfig();

    if (!PYTHON_SERVICE_URL) {
      const fallback = getDefaultWorkflowTemplate(userPrompt);
      return NextResponse.json({
        success: true,
        chatResponse: `Creating "${fallback.name}" blueprint.`,
        blueprint: {
          ...fallback,
          id: `bp-${Date.now()}`,
          version: 1,
          capabilityLevel: 1,
          createdAt: new Date().toISOString(),
          sourcePrompt: userPrompt,
          dataContract: { inputs: fallback.dataInputs || [], bindings: [] },
          computeGraph: { nodes: [] },
          uiComposition: { layout: 'tabs', tabs: [] },
        },
      });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/workflow/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_prompt: userPrompt }),
    });

    if (!upstream.ok) {
      console.error('Python service error:', upstream.status);
      // Fallback to local template
      const fallback = getDefaultWorkflowTemplate(userPrompt);
      return NextResponse.json({ success: true, chatResponse: '...', blueprint: { ...fallback } });
    }

    const result = await upstream.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error('Workflow generate route error:', error);
    return NextResponse.json({ success: false, error: 'Internal server error' }, { status: 500 });
  }
}
```

### `report-generate/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const { PYTHON_SERVICE_URL } = getServerConfig();
    if (!PYTHON_SERVICE_URL) {
      return createMockStreamResponse(body.data);
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/report/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        blueprint: body.blueprint,
        data: body.data,
        context: body.context,
      }),
    });

    if (!upstream.ok) {
      return createMockStreamResponse(body.data);
    }

    // SSE 直接透传
    return new NextResponse(upstream.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    console.error('Report generate route error:', error);
    return NextResponse.json({ success: false, error: 'Internal server error' }, { status: 500 });
  }
}
```

### `report-chat/route.ts` (重写)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const { userMessage, reportContext, data } = await request.json();

    const { PYTHON_SERVICE_URL } = getServerConfig();
    if (!PYTHON_SERVICE_URL) {
      return NextResponse.json({ success: true, chatResponse: getMockChatResponse(userMessage) });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/report/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_message: userMessage, report_context: reportContext, data }),
    });

    if (!upstream.ok) {
      return NextResponse.json({ success: true, chatResponse: getMockChatResponse(userMessage) });
    }

    const result = await upstream.json();
    return NextResponse.json({ success: result.success, chatResponse: result.chatResponse });
  } catch (error) {
    console.error('Report chat route error:', error);
    return NextResponse.json({ success: false, error: 'Internal server error' }, { status: 500 });
  }
}
```

### `classify-intent/route.ts` (新增)

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerConfig } from '@/lib/env';

export const runtime = 'nodejs';
export const maxDuration = 10;

export async function POST(request: NextRequest) {
  try {
    const { userMessage, workflowName, reportSummary } = await request.json();

    const { PYTHON_SERVICE_URL } = getServerConfig();
    if (!PYTHON_SERVICE_URL) {
      const { shouldRegenerateWorkflow } = await import('@/lib/studio-router');
      return NextResponse.json({
        intent: shouldRegenerateWorkflow(userMessage) ? 'workflow_rebuild' : 'data_chat',
        confidence: 0.5,
      });
    }

    const upstream = await fetch(`${PYTHON_SERVICE_URL}/api/intent/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_message: userMessage, workflow_name: workflowName, report_summary: reportSummary }),
    });

    if (!upstream.ok) {
      return NextResponse.json({ intent: 'data_chat', confidence: 0 });
    }

    return NextResponse.json(await upstream.json());
  } catch (error) {
    console.error('Classify intent error:', error);
    return NextResponse.json({ intent: 'data_chat', confidence: 0 });
  }
}
```

---

## Mock 数据策略

### Phase 1 (保持现状)

Mock 数据仍在前端，前端组装好后通过 `data` 字段传给 Python。

```
前端选择 class + assignment → getMockDataForWorkflow() → data JSON → Python ExecutorAgent
```

### Phase 2 (数据迁移到 Python)

Mock 数据移到 Python 服务的 `services/mock_data.py`。前端只传 ID，ExecutorAgent 通过 Blueprint 的 DataContract 获取数据。

```
前端选择 class + assignment → { context: { teacherId, classId, assignmentId } } → ExecutorAgent → DataContract → tools
```

**Phase 1 不需要改前端任何代码。**

---

## 错误处理协议

### Python 服务 HTTP 错误

| Status | 含义 | Proxy 处理 |
|--------|------|-----------|
| 200 | 成功 | 透传 |
| 400 | 请求参数错误 | 透传错误信息 |
| 422 | Pydantic 验证错误 | 透传或 fallback |
| 500 | 服务内部错误 | Fallback to mock |
| 503 | 服务不可用 | Fallback to mock |
| Timeout | 超时 | Fallback to mock |
| ECONNREFUSED | Python 服务未启动 | Fallback to mock |

### Fallback 策略

每个 Proxy route 都保留现有的 fallback:
- `workflow-generate`: `getDefaultWorkflowTemplate()` → 转为 Blueprint 格式
- `report-generate`: `createMockStreamResponse()`
- `report-chat`: `getMockChatResponse()`

---

## 测试检查清单

| 测试项 | 验证方法 |
|--------|---------|
| Python 服务健康 | `GET /api/health` 返回 200 |
| Blueprint 生成 | 5 个场景各生成一次，检查三层结构完整 |
| Blueprint 三层验证 | 检查 `dataContract.inputs`、`computeGraph.nodes`、`uiComposition.tabs` 非空 |
| ComputeGraph 确定性 | TOOL 节点产出精确统计，AI 节点产出叙事 |
| SSE 流格式 | `curl -N` 检查 PHASE → TOOL_CALL → MESSAGE → COMPLETE |
| Report 渲染 | 6 种 block type 全部渲染正确 |
| camelCase | 检查 report JSON 的 key 全是 camelCase |
| 追问路由 | 测试 "增加一个维度" vs "平均分多少" |
| Fallback | 停掉 Python 服务，验证 mock 正常工作 |
| 流中断恢复 | 网络断开后，前端不崩溃 |
| 大数据量 | 35 学生完整数据，token 不超限 |

### 验证命令

```bash
# Blueprint 生成
curl -X POST http://localhost:8000/api/workflow/generate \
  -H "Content-Type: application/json" \
  -d '{"user_prompt":"Analyze Form 1A English performance"}'

# SSE 流
curl -N -X POST http://localhost:8000/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{"blueprint":{...},"data":{},"context":{"teacherId":"t-001"}}'
```

---

## 开发流程

### Step 1: Python 服务启动

```bash
cd insight-ai-agent
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

### Step 2: 前端配置

```bash
cd insight_ai_frontend
echo "PYTHON_SERVICE_URL=http://localhost:8000" >> .env.local
npm run dev
```

### Step 3: 端对端测试

1. 打开 http://localhost:3000/teacher/studio
2. 输入 "Analyze Form 1A English performance"
3. 验证: PlannerAgent 返回 Blueprint
4. 选择 Class + Assignment
5. 验证: ExecutorAgent 流式执行 Blueprint
6. 验证: 报告正确渲染
