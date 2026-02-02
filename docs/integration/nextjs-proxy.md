# Next.js Proxy 对接契约

> Next.js 前端通过 API Routes 代理所有 AI 请求，避免跨域和密钥暴露。

---

## Proxy 路由映射

| Next.js Route | Python 服务端点 | 传输方式 |
|---------------|----------------|----------|
| `POST /api/ai/conversation` | `POST /api/conversation` | JSON pass-through |
| `POST /api/ai/page-generate` | `POST /api/page/generate` | SSE pass-through |
| `POST /api/ai/page-patch` | `POST /api/page/patch` | SSE pass-through |
| `POST /api/ai/workflow-generate` | `POST /api/workflow/generate` | JSON pass-through |

---

## SSE Proxy 要求

SSE 端点（`/api/page/generate`、`/api/page/patch`）返回 `text/event-stream`，前端 proxy 必须流式透传：

```typescript
// app/api/ai/page-generate/route.ts
import { NextRequest } from 'next/server';

const AI_BASE_URL = process.env.AI_SERVICE_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
  const body = await req.json();

  const response = await fetch(`${AI_BASE_URL}/api/page/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // 从 Next.js session 获取 token 并转发
      'Authorization': req.headers.get('Authorization') || '',
    },
    body: JSON.stringify(body),
  });

  // 流式透传 — 不缓冲整个响应
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  });
}
```

**关键约束：**

- 使用 `ReadableStream` 透传（不缓冲整个响应）
- 转发 `Content-Type: text/event-stream`
- 不添加 `Transfer-Encoding: chunked` 重编码
- 不做字段转换 — 所有字段已是 camelCase

---

## CamelCase 字段映射

Python 服务内部使用 `snake_case`，所有 API 输出自动转为 `camelCase`（由 `CamelModel` 基类处理）。

**前端直接收发 camelCase，proxy 零转换。**

示例：
```
Python 内部: chat_response → JSON 输出: chatResponse
Python 内部: source_prompt → JSON 输出: sourcePrompt
Python 内部: block_id → JSON 输出: blockId
```

---

## 认证流程

```
Browser → Next.js Proxy → Python Service → Java Backend
                ↓                ↓
         添加 Bearer token    透传或验证
```

- Next.js proxy 从 session/cookie 获取用户 token
- 添加 `Authorization: Bearer <token>` header
- Python 服务透传给 Java 后端（或自行验证）

---

## SSE 事件类型总览

前端需处理的 SSE 事件（`POST /api/page/generate` 和 `POST /api/page/patch`）：

### 必须处理

| 事件 | 说明 | 前端行为 |
|------|------|---------|
| `MESSAGE` | AI 生成文本（向下兼容） | 累积拼接，打字机效果 |
| `COMPLETE` | 流结束，含完整页面 | 解析 `result.page` 渲染 |

### 推荐处理（Phase 6 新增）

| 事件 | 说明 | 前端行为 |
|------|------|---------|
| `BLOCK_START` | AI 开始填充某个 block | 显示 block 加载态 |
| `SLOT_DELTA` | block 内增量文本 | 按 `blockId + slotKey` 定位追加 |
| `BLOCK_COMPLETE` | block 填充完成 | 移除加载态 |

### 可选处理

| 事件 | 说明 | 前端行为 |
|------|------|---------|
| `PHASE` | 执行阶段通知 | 进度条/状态提示 |
| `TOOL_CALL` | 工具调用开始 | "正在获取数据..." |
| `TOOL_RESULT` | 工具调用结果 | 可忽略 |
| `DATA_ERROR` | 数据获取失败 | 友好错误提示 + 建议 |

### 事件顺序

```
PHASE(data) → TOOL_CALL/TOOL_RESULT × N →
PHASE(compute) → TOOL_CALL/TOOL_RESULT × N →
PHASE(compose) →
  BLOCK_START → SLOT_DELTA × N → BLOCK_COMPLETE  (per AI block)
  MESSAGE (backward-compat, all AI text concatenated)
→ COMPLETE
```

---

## SSE 前端消费参考（Phase 6 增强版）

```typescript
type SSEEvent =
  | { type: 'PHASE'; phase: string; message: string }
  | { type: 'TOOL_CALL'; tool: string; args: Record<string, any> }
  | { type: 'TOOL_RESULT'; tool: string; status: string }
  | { type: 'BLOCK_START'; blockId: string; componentType: string }
  | { type: 'SLOT_DELTA'; blockId: string; slotKey: string; deltaText: string }
  | { type: 'BLOCK_COMPLETE'; blockId: string }
  | { type: 'MESSAGE'; content: string }
  | { type: 'DATA_ERROR'; entity: string; message: string; suggestions: string[] }
  | { type: 'COMPLETE'; message: string; progress: number; result: PageResult };

async function handleSSEStream(
  response: Response,
  callbacks: {
    onBlockStart?: (blockId: string, componentType: string) => void;
    onSlotDelta?: (blockId: string, slotKey: string, delta: string) => void;
    onBlockComplete?: (blockId: string) => void;
    onMessage?: (content: string) => void;
    onComplete?: (result: PageResult) => void;
    onError?: (error: string) => void;
  }
) {
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
      const event: SSEEvent = JSON.parse(line.slice(6));

      switch (event.type) {
        case 'BLOCK_START':
          callbacks.onBlockStart?.(event.blockId, event.componentType);
          break;
        case 'SLOT_DELTA':
          callbacks.onSlotDelta?.(event.blockId, event.slotKey, event.deltaText);
          break;
        case 'BLOCK_COMPLETE':
          callbacks.onBlockComplete?.(event.blockId);
          break;
        case 'MESSAGE':
          callbacks.onMessage?.(event.content);
          break;
        case 'COMPLETE':
          callbacks.onComplete?.(event.result);
          break;
        case 'DATA_ERROR':
          callbacks.onError?.(event.message);
          break;
      }
    }
  }
}
```

---

## ConversationResponse 结构（Phase 4.5+）

```typescript
interface ConversationResponse {
  // Phase 4.5 结构化字段（推荐使用）
  mode: 'entry' | 'followup';
  action: 'chat' | 'build' | 'clarify' | 'refine' | 'rebuild';
  chatKind: 'smalltalk' | 'qa' | 'page' | null;

  // 向下兼容字段
  legacyAction: string;  // 'chat_smalltalk' | 'chat_qa' | 'build_workflow' | ...

  // 数据字段
  chatResponse: string | null;
  blueprint: Blueprint | null;
  clarifyOptions: ClarifyOptions | null;
  conversationId: string | null;
  resolvedEntities: ResolvedEntity[] | null;

  // Phase 6 新增
  patchPlan: PatchPlan | null;  // 仅 refine + patch scope 时有值
}

interface PatchPlan {
  scope: 'patch_layout' | 'patch_compose' | 'full_rebuild';
  instructions: PatchInstruction[];
  affectedBlockIds: string[];
}

interface PatchInstruction {
  type: 'update_props' | 'reorder' | 'add_block' | 'remove_block' | 'recompose';
  targetBlockId: string | null;
  changes: Record<string, any>;
}
```

---

## 错误处理

| HTTP Status | 场景 | 处理 |
|-------------|------|------|
| 200 | 正常 | 解析响应 |
| 422 | 参数校验失败 | 显示校验错误 |
| 502 | LLM 调用失败 | 重试或降级提示 |
| SSE `DATA_ERROR` | 实体不存在 | 显示建议选项 |
| SSE `COMPLETE(error)` | 执行异常 | 显示错误信息 |

Proxy 层不做错误转换，直接透传 HTTP status 和 SSE 事件给前端处理。
