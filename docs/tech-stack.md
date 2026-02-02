# 技术栈

> 当前 vs 目标技术栈、框架选型理由。

---

## 当前（Phase 1）

```
# Web framework
fastapi>=0.115          # 异步 Web 框架
uvicorn[standard]>=0.32 # ASGI 服务器
sse-starlette>=2.0      # SSE 响应

# LLM
litellm>=1.0            # 多模型 LLM 抽象层

# Data validation & settings
pydantic>=2.0           # 数据验证
pydantic-settings>=2.0  # 配置管理 (.env 自动加载)

# HTTP client
httpx>=0.27             # 异步 HTTP 客户端
requests>=2.31          # HTTP 客户端 (Brave Search 技能)

# Tools
fastmcp>=2.0            # MCP 工具注册框架
numpy>=1.26             # 统计计算

# Config
python-dotenv>=1.0      # 环境变量

# Testing
pytest>=8.0             # 测试
pytest-asyncio>=0.24    # 异步测试支持
```

---

## 目标（Phase 1+）

```
fastapi>=0.115.0        # 异步 Web 框架
uvicorn[standard]>=0.32 # ASGI 服务器
sse-starlette>=2.0      # SSE 响应
pydantic>=2.10          # 数据验证
pydantic-settings>=2.6  # 配置管理
pydantic-ai[litellm]>=1.40  # Agent 框架 + multi-provider LLM
fastmcp>=2.14           # 内部工具注册框架
httpx>=0.28             # 异步 HTTP 客户端 (调 Java)
numpy>=2.1              # 统计计算
python-dotenv>=1.0      # 环境变量
```

### 简要概览

```
fastapi + uvicorn          # HTTP/SSE server
fastmcp                    # 内部 tool registry（数据获取 + 统计计算）
pydantic-ai[litellm]       # Agent framework + multi-provider LLM
httpx                      # 调 Java backend
numpy                      # 统计计算
pydantic + pydantic-settings  # 数据模型 + 配置
sse-starlette              # SSE response
```

---

## 框架选型理由

### FastAPI

| 维度 | Flask | FastAPI |
|------|-------|---------|
| 异步支持 | 需 gevent/eventlet | 原生 async/await |
| SSE | 手动实现 | sse-starlette 直接支持 |
| 数据验证 | 手动 | Pydantic 自动 |
| API 文档 | Flask-RESTx | 内置 Swagger/ReDoc |
| 性能 | WSGI | ASGI，更高并发 |

### PydanticAI + LiteLLM (Agent 框架)

详见 [多 Agent 设计 — LLM 框架选型](architecture/agents.md)。

核心原因：
- **结构化输出**: `result_type=Blueprint` 直接验证 LLM 输出
- **多 Provider**: LiteLLM 统一 100+ LLM providers
- **类型安全**: 与 Pydantic v2 天然集成
- **MCP 集成**: 原生支持 FastMCP tools

### FastMCP 

详见 [多 Agent 设计 — Why FastMCP](architecture/agents.md)。

核心原因：
- 代码量从 ~40 行/tool 降到 ~10 行/tool
- Schema 自动生成
- Pydantic 参数验证
- 内置交互式测试 (`fastmcp dev`)
