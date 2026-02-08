# Insight AI Agent — 上线前压力测试报告

> 目标服务器: 4 核 CPU / 8GB RAM
> 服务: FastAPI + PydanticAI + LiteLLM + LightRAG
> 日期: 2026-02-08

---

## 一、服务架构分析

### 1.1 端点清单与负载等级

| 端点 | 方法 | SSE | 负载等级 | 预估延迟 | LLM 调用次数 |
|------|------|-----|----------|----------|-------------|
| `/api/health` | GET | - | 极轻 | <10ms | 0 |
| `/models`, `/skills` | GET | - | 极轻 | <10ms | 0 |
| `/api/conversation` | POST | - | 轻-中 | 2-15s | 1-2 (Router + Chat/Planner) |
| `/api/conversation/stream` | POST | **是** | **重** | 5-120s | 2-15+ (Router + Planner + Executor) |
| `/api/workflow/generate` | POST | - | 中 | 5-15s | 1 (PlannerAgent) |
| `/api/page/generate` | POST | **是** | **重** | 30-120s | 5-15 (ExecutorAgent 三阶段) |
| `/api/page/patch` | POST | **是** | 中 | 10-30s | 2-5 (PatchAgent) |
| `/api/internal/documents/parse` | POST | - | **内存密集** | 10-60s | 1+ (嵌入向量) |
| `/api/internal/documents/search` | POST | - | 中 | 1-5s | 1 (嵌入查询) |

### 1.2 请求生命周期（最重路径: Build Pipeline）

```
用户请求 → RouterAgent (qwen-turbo, ~0.5s)
         → EntityResolver (Java API, ~1s)
         → PlannerAgent (qwen-max, ~5-15s)
         → ExecutorAgent Phase A: Data (Java API x N, ~3-10s)
         → ExecutorAgent Phase B: Compute (本地计算, ~0.5s)
         → ExecutorAgent Phase C: Compose (qwen-max x M slots, ~10-60s)
         → SSE 完成

总耗时: 20-90 秒 / 请求
LLM 调用: 3-15 次 / 请求
```

### 1.3 外部依赖

| 依赖 | 协议 | 超时 | 影响 |
|------|------|------|------|
| DashScope (qwen-max) | HTTPS | 无显式限制 | **关键路径** — 所有 AI 功能 |
| DashScope (qwen-turbo) | HTTPS | 无显式限制 | Router 意图分类 |
| Java 后端 (Spring Boot) | HTTP | 15s | 数据获取、鉴权 |
| PostgreSQL (pgvector) | TCP | 无显式限制 | RAG 向量检索 |
| DashScope 嵌入 API | HTTPS | 60s | RAG 文档入库 |

---

## 二、并发量预测（4 核 8GB）

### 2.1 瓶颈分析

**主要瓶颈不是 CPU 或内存，而是 LLM API 延迟和速率限制。**

| 瓶颈因素 | 限制值 | 影响 |
|----------|--------|------|
| **DashScope qwen-max RPM** | 60-120 RPM (取决于套餐) | 每用户 3-15 次调用，最大 4-40 并发用户 |
| **SSE 长连接** | 每连接 20-90s 占用 | 连接池压力 |
| **内存: 进程** | ~300-500MB / worker | 4 workers ≈ 2GB |
| **内存: RAG 工作区** | ~50-100MB / teacher | LightRAG 实例逐 teacher 创建 |
| **内存: 会话存储** | ~5KB / session | 内存模式，无上限 |
| **httpx 连接池** | 默认 8 连接 / 池 | Java 后端调用瓶颈 |

### 2.2 并发量预测表

| 场景 | 并发用户数 | 说明 | 前提条件 |
|------|-----------|------|----------|
| **保守** | **5-8** | 所有用户同时执行 Build 流程 | DashScope 60 RPM |
| **正常** | **10-15** | 混合负载 (70% Chat + 20% Workflow + 10% Build) | DashScope 120 RPM |
| **乐观** | **15-25** | 混合负载 + 请求错峰 + 缓存命中 | DashScope 200+ RPM + 响应缓存 |
| **纯 Chat** | **20-30** | 仅聊天交互 (单次 LLM 调用) | 无 Build 操作 |

### 2.3 计算过程

```
假设条件:
- DashScope qwen-max: 100 RPM (每分钟请求)
- 混合负载比例: 60% chat(1 LLM 调用) + 25% workflow(1 调用) + 15% build(5 调用)
- 加权平均 LLM 调用/请求 = 0.6×1 + 0.25×1 + 0.15×5 = 1.6
- 平均请求耗时: 0.6×5s + 0.25×10s + 0.15×60s = 14.5s
- 每用户每分钟请求: 60s / (14.5s + 15s think_time) ≈ 2 RPM

可用 LLM 调用 = 100 RPM
每用户消耗 = 2 RPM × 1.6 调用/请求 = 3.2 LLM RPM
最大用户数 = 100 / 3.2 ≈ 31

但考虑到:
- 突发流量 (峰值 2-3x)
- LLM API 偶尔超时需重试
- 安全余量 20%

推荐并发: 31 / 3 × 0.8 ≈ 8-10 并发用户 (保守)
         31 / 2 × 0.8 ≈ 12-15 并发用户 (正常)
```

### 2.4 内存预算

```
组件                      内存占用
──────────────────────────────────────
OS + 系统服务              ~1.0 GB
4 × Uvicorn workers       ~2.0 GB (500MB × 4)
Python 依赖 (共享)         ~0.3 GB
PostgreSQL (pgvector)      ~1.5 GB (HNSW 索引)
会话存储 (内存)            ~0.1 GB (最大 200 会话 × 5KB)
RAG 工作区缓存             ~0.5 GB (5-10 个 teacher 实例)
──────────────────────────────────────
合计                       ~5.4 GB
剩余 (缓冲)               ~2.6 GB
```

---

## 三、测试方案

### 3.1 测试工具

| 工具 | 用途 | 安装 |
|------|------|------|
| **Locust** | 主要负载测试 (Python 原生, SSE 支持) | `pip install locust sseclient-py` |
| **run_baseline.py** | 快速基线验证 (单脚本) | 自带, 仅需 `httpx` |
| **htop / psutil** | 服务器资源监控 | 系统自带 |

### 3.2 测试阶段

#### Phase 1: 基线测试 (Baseline)

**目标**: 确认服务正常运行, 获取单用户延迟基准

```bash
cd insight-ai-agent
python tests/load/run_baseline.py --host http://localhost:5000
```

**验收标准**:
| 指标 | 标准 |
|------|------|
| Health 响应 p99 | < 50ms |
| Chat 响应 p99 | < 15s |
| Workflow 生成 p99 | < 30s |
| SSE 首事件 (TTFE) | < 5s |
| 错误率 | 0% |

#### Phase 2: 递增并发 (Ramp-up)

**目标**: 找到性能拐点, 确定最大安全并发

```bash
# 使用 Locust Web UI
locust -f tests/load/locustfile.py --host http://localhost:5000

# 或 headless 模式 (推荐 CI/CD)
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless \
    -u 15 -r 1 \
    --run-time 10m \
    --html tests/load/report_ramp.html
```

**参数说明**:
- `-u 15`: 最大 15 个虚拟用户
- `-r 1`: 每秒增加 1 个用户
- 持续 10 分钟

**验收标准**:
| 指标 | 标准 |
|------|------|
| Chat p95 | < 10s |
| Build p95 | < 120s |
| 错误率 | < 5% |
| SSE 断连率 | < 2% |
| 内存 (per worker) | < 600MB |

#### Phase 3: 持续稳定性 (Soak)

**目标**: 检测内存泄漏、连接泄漏、会话累积

```bash
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless \
    -u 10 -r 2 \
    --run-time 30m \
    --html tests/load/report_soak.html
```

**监控指标**:
- Worker RSS 内存 (每 5 分钟采样)
- PostgreSQL `pg_stat_activity` 活跃连接数
- 会话存储大小 (通过日志)
- LLM API 429 错误数

**验收标准**:
| 指标 | 标准 |
|------|------|
| 内存增长 (30 min) | < 100MB / worker |
| 连接泄漏 | 0 |
| 累积错误率 | < 3% |

#### Phase 4: 突发测试 (Spike)

**目标**: 验证突发流量下的优雅降级

```bash
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless \
    -u 25 -r 10 \
    --run-time 3m \
    --html tests/load/report_spike.html
```

**验收标准**:
| 指标 | 标准 |
|------|------|
| 服务可用性 | > 95% (允许 429/503) |
| 恢复时间 | < 30s (峰值过后) |
| 数据丢失 | 0 (已完成的请求不应丢失数据) |

### 3.3 各用户类型说明

| Locust 用户类 | 权重 | 模拟行为 | 思考时间 |
|--------------|------|----------|---------|
| `HealthCheckUser` | 1 | 健康检查 | 1-3s |
| `ChatUser` | 5 | 闲聊 / QA 对话 | 10-30s |
| `WorkflowUser` | 3 | Blueprint 生成 | 30-60s |
| `BuildUser` | 2 | 完整 Build 流程 (最重) | 60-120s |
| `QuizUser` | 2 | 测验生成 | 45-90s |
| `MixedUser` | 10 | 真实混合场景 | 5-20s |

---

## 四、当前问题与优化建议

### 4.1 [严重] 生产部署配置缺失

**问题**: `main.py` 只配置了 `uvicorn.run()` 的基本参数, 未设置 workers, 未使用 uvloop.

**当前代码** ([main.py:78-84](../../main.py#L78-L84)):
```python
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug,
    )
```

**影响**: 单 worker 单进程, 无法利用多核, 单个长请求会阻塞所有后续请求.

**建议**: 使用 Gunicorn + UvicornWorker (已创建配置文件):
```bash
# 生产启动命令
gunicorn main:app -c deploy/gunicorn.conf.py
```

或直接修改 uvicorn 参数:
```bash
uvicorn main:app --host 0.0.0.0 --port 5000 \
    --workers 4 --loop uvloop --http httptools
```

**优先级**: P0 — 上线前必须修复

---

### 4.2 [严重] 无请求并发限制

**问题**: 所有端点无并发限制、无速率限制、无请求队列上限.

**影响**: 突发流量会耗尽 LLM API 配额, 造成雪崩.

**建议**: 添加 FastAPI 中间件或依赖注入:

```python
# 方案 A: 使用 asyncio.Semaphore 限制并发 LLM 调用
import asyncio

_llm_semaphore = asyncio.Semaphore(10)  # 最多 10 个并发 LLM 调用

async def rate_limited_llm_call(func, *args, **kwargs):
    async with _llm_semaphore:
        return await func(*args, **kwargs)

# 方案 B: 使用 slowapi 限速中间件
# pip install slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/conversation/stream")
@limiter.limit("5/minute")
async def conversation_stream(req, request: Request):
    ...
```

**优先级**: P0 — 上线前必须修复

---

### 4.3 [严重] httpx 连接池未配置

**问题**: `JavaClient` 创建 `httpx.AsyncClient` 时未设置连接池参数 ([java_client.py:92-97](../../services/java_client.py#L92-L97)).

**当前代码**:
```python
self._http = httpx.AsyncClient(
    base_url=self._base_url,
    timeout=httpx.Timeout(self._timeout),
    headers=self._auth_headers(),
    verify=False,
)
```

**影响**: httpx 默认最大 8 个连接. 4 个 worker 共享一个 JavaClient 单例, 但每个 worker 是独立进程, 实际每 worker 8 连接. 在高并发下 Data Phase 会排队等待连接.

**建议**:
```python
self._http = httpx.AsyncClient(
    base_url=self._base_url,
    timeout=httpx.Timeout(self._timeout),
    headers=self._auth_headers(),
    verify=False,
    limits=httpx.Limits(
        max_connections=30,
        max_keepalive_connections=15,
        keepalive_expiry=30,
    ),
)
```

**优先级**: P1 — 上线前建议修复

---

### 4.4 [中等] 会话存储为内存模式

**问题**: `conversation_store_type: "memory"` 使用进程内字典存储会话 ([settings.py:73](../../config/settings.py#L73)).

**影响**:
1. 多 worker 部署时会话不共享 — 用户请求分配到不同 worker 会丢失上下文
2. Worker 回收时丢失所有会话
3. 无法水平扩展

**建议**: 上线前切换到 Redis:
```python
conversation_store_type: str = "redis"
redis_url: str = "redis://localhost:6379/0"
```

**优先级**: P1 — 多 worker 部署前必须解决

---

### 4.5 [中等] LLM 调用无超时配置

**问题**: PlannerAgent / ExecutorAgent / RouterAgent 通过 LiteLLM 调用 LLM 时未设置显式超时.

**影响**: LLM 供应商故障时请求会无限挂起, 消耗 worker 资源.

**建议**: 在 LiteLLM 调用中添加超时:
```python
# 在 agents/provider.py 中
import litellm
litellm.request_timeout = 60  # 全局 60s 超时

# 或在每次调用时
response = await litellm.acompletion(
    model="dashscope/qwen-max",
    messages=messages,
    timeout=60,
)
```

**优先级**: P1

---

### 4.6 [中等] asyncpg 无连接池

**问题**: RAG Engine 使用单连接验证, 无连接池 ([rag_engine.py:39-55](../../insight_backend/rag_engine.py#L39-L55)).

**影响**: 每个 RAG 查询可能创建新连接, 高并发下 PostgreSQL 连接数会爆炸.

**建议**:
```python
# 在 RAG Engine 初始化时创建连接池
self._pool = await asyncpg.create_pool(
    dsn=self._pg_uri,
    min_size=2,
    max_size=10,  # 每 worker 10 连接, 4 workers = 40 总连接
    max_inactive_connection_lifetime=300,
)
```

**优先级**: P2

---

### 4.7 [低] SSE 无心跳机制

**问题**: SSE 流式端点无定期心跳, 长时间无事件输出时代理/LB 可能超时断连.

**建议**: 在 SSE 生成器中添加心跳:
```python
async def _conversation_stream_generator(req):
    last_event = time.monotonic()
    ...
    # 在长操作前/后检查
    if time.monotonic() - last_event > 15:
        yield ": heartbeat\n\n"  # SSE 注释行, 保持连接
        last_event = time.monotonic()
```

**优先级**: P2

---

### 4.8 [低] 无请求 ID 追踪

**问题**: 请求链路中无 request_id, 难以关联日志排查性能问题.

**建议**: 添加中间件生成并传播 request_id:
```python
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        # 注入到 logger context
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

**优先级**: P3

---

## 五、优化优先级总览

| 级别 | 问题 | 影响范围 | 建议 |
|------|------|----------|------|
| **P0** | 单 worker 部署 | 所有请求 | 使用 Gunicorn 4 workers |
| **P0** | 无并发/速率限制 | LLM API 配额 | 添加 Semaphore + slowapi |
| **P1** | httpx 连接池默认值 | Java API 调用 | 配置 max_connections=30 |
| **P1** | 内存会话存储 | 多 worker 场景 | 迁移到 Redis |
| **P1** | LLM 无超时 | Worker 占用 | 设置 litellm.request_timeout=60 |
| **P2** | asyncpg 无连接池 | RAG 查询 | 创建 asyncpg.create_pool |
| **P2** | SSE 无心跳 | 长流式连接 | 添加 15s 心跳注释 |
| **P3** | 无 Request ID | 排障效率 | 添加 RequestIdMiddleware |

---

## 六、测试执行步骤

### Step 1: 环境准备

```bash
cd insight-ai-agent

# 安装测试依赖
pip install locust sseclient-py

# 确认服务运行
python main.py  # 或 gunicorn main:app -c deploy/gunicorn.conf.py
```

### Step 2: 基线测试

```bash
python tests/load/run_baseline.py --host http://localhost:5000
```

记录所有基线数据到下表:

| 端点 | p50 | p95 | p99 | 错误 |
|------|-----|-----|-----|------|
| GET /api/health | _ms | _ms | _ms | _/10 |
| Health x20 并发 | _ms | _ms | _ms | _/20 |
| POST /conversation (chat) | _ms | _ms | _ms | _/3 |
| POST /workflow/generate | _ms | _ms | _ms | _/2 |
| POST /conversation/stream (SSE) | TTFE: _ms | Duration: _ms | Events: _ | _/1 |

### Step 3: 递增并发

```bash
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless -u 15 -r 1 --run-time 10m \
    --html tests/load/report_ramp.html
```

同时在另一终端监控:
```bash
# Linux
watch -n 5 "ps aux | grep uvicorn | grep -v grep"
watch -n 5 "cat /proc/meminfo | grep -E 'MemFree|MemAvailable'"

# Windows
tasklist /FI "IMAGENAME eq python.exe"
```

### Step 4: 持续稳定性

```bash
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless -u 10 -r 2 --run-time 30m \
    --html tests/load/report_soak.html
```

### Step 5: 突发测试

```bash
locust -f tests/load/locustfile.py MixedUser \
    --host http://localhost:5000 \
    --headless -u 25 -r 10 --run-time 3m \
    --html tests/load/report_spike.html
```

### Step 6: 结果汇总

收集以下 HTML 报告:
- `tests/load/report_ramp.html`
- `tests/load/report_soak.html`
- `tests/load/report_spike.html`

---

## 七、推荐生产配置

### 7.1 启动命令

```bash
# 推荐: Gunicorn + Uvicorn workers
gunicorn main:app -c deploy/gunicorn.conf.py

# 或: 直接 Uvicorn (Windows 兼容)
uvicorn main:app --host 0.0.0.0 --port 5000 \
    --workers 4 --loop uvloop --http httptools \
    --timeout-keep-alive 120
```

### 7.2 Nginx 反向代理配置 (SSE 必需)

```nginx
upstream ai_agent {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    server_name ai-agent.insightai.hk;

    # SSE 端点 — 禁用缓冲
    location ~ ^/api/(conversation/stream|page/(generate|patch)) {
        proxy_pass http://ai_agent;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 180s;
        chunked_transfer_encoding on;
    }

    # 普通 API 端点
    location /api/ {
        proxy_pass http://ai_agent;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
```

### 7.3 环境变量 (.env)

```bash
# Production settings
DEBUG=false
SERVICE_PORT=5000

# LLM — 控制成本和速率
DEFAULT_MODEL=dashscope/qwen-max
ROUTER_MODEL=dashscope/qwen-turbo-latest
AGENT_MAX_ITERATIONS=10    # 降低 (从15), 防止 runaway loop
MAX_TOKENS=4096

# Java Backend
SPRING_BOOT_BASE_URL=http://java-backend:8080
SPRING_BOOT_TIMEOUT=15

# Conversation
CONVERSATION_STORE_TYPE=redis    # 生产必须用 Redis
CONVERSATION_TTL=1800

# RAG
PG_URI=postgresql://insight:xxx@pg-host:5432/insight_agent
```

---

## 八、结论

### 推荐并发数

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| **安全并发 (推荐上线值)** | **10 用户** | 混合负载, 留有余量 |
| **最大并发 (性能边界)** | **15-20 用户** | 需要完成所有 P0/P1 优化 |
| **纯 Chat 场景** | **25-30 用户** | 仅轻量级对话, 无 Build |

### 上线前必做清单

- [x] 切换为 Gunicorn 4 workers 部署 (P0) — `deploy/gunicorn.conf.py` + `main.py` 多 worker 模式
- [x] 添加 LLM 调用并发限制 Semaphore(10) (P0) — `services/concurrency.py` + `ConcurrencyLimitMiddleware`
- [x] 配置 httpx 连接池 max_connections=30 (P1) — `services/java_client.py`
- [x] LiteLLM 设置 request_timeout=60 (P1) — `main.py` 全局设置 + RAG engine per-call timeout
- [ ] 运行基线测试并记录数据 (Phase 1)
- [ ] 运行递增并发测试至 15 用户 (Phase 2)
- [ ] 运行 30 分钟持续稳定性测试 (Phase 3)
- [ ] 配置 Nginx SSE 反向代理 (proxy_buffering off)
- [ ] 监控 DashScope API 速率限制 (RPM 使用率)

### 上线后建议

- [x] 迁移会话存储到 Redis (P1) — 已配置 `CONVERSATION_STORE_TYPE=redis`
- [x] 添加 asyncpg 连接池 (P2) — `insight_backend/rag_engine.py` (min=2, max=10)
- [x] SSE 心跳机制 (P2) — `api/conversation.py` + `api/page.py` (15s 间隔)
- [x] Request ID 追踪 (P3) — `services/middleware.py` (纯 ASGI, SSE 安全)
- [ ] 接入 Prometheus + Grafana 监控
- [ ] 配置 LiteLLM 多模型 fallback (qwen-max → gpt-4o)
