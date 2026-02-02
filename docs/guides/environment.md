# 环境变量

> Python 服务 + 前端的完整环境变量说明。

---

## Python 服务

### 当前变量（Phase 1）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEBUG` | 调试模式 | `false` |
| `SERVICE_PORT` | 服务端口 | `5000` |
| `CORS_ORIGINS` | 允许的 CORS 源 | `["*"]` |
| `DEFAULT_MODEL` | 默认 LLM (含 provider 前缀) | `dashscope/qwen-max` |
| `EXECUTOR_MODEL` | ExecutorAgent 使用的模型 | `dashscope/qwen-max` |
| `MAX_TOKENS` | 最大 token 数 | `4096` |
| `DASHSCOPE_API_KEY` | 阿里通义千问 API Key | - |
| `ZAI_API_KEY` | 智谱 AI API Key | - |
| `ZAI_API_BASE` | 智谱 AI API Base URL | `https://open.bigmodel.cn/api/paas/v4/` |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `BRAVE_API_KEY` | Brave Search API Key | - |
| `MCP_SERVER_NAME` | MCP 服务名称 | `insight-ai-agent` |
| `MEMORY_DIR` | 持久化记忆文件目录 | `data` |

### 目标变量（Phase 2+）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PLANNER_MODEL` | PlannerAgent 使用的模型 | `openai/gpt-4o-mini` |
| `ROUTER_MODEL` | RouterAgent 使用的模型 | `openai/gpt-4o-mini` |
| `JAVA_BACKEND_URL` | Java 后端地址 | `http://localhost:8080` |
| `USE_MOCK_DATA` | 使用 Mock 数据 | `true` |
| `TOOL_TIMEOUT` | 工具调用超时 (秒) | `10.0` |

### `.env` 示例

```env
# ── Service ──────────────────────────────────────────────
DEBUG=true
SERVICE_PORT=5000

# ── LLM ─────────────────────────────────────────────────
DEFAULT_MODEL=dashscope/qwen-max
EXECUTOR_MODEL=dashscope/qwen-max
MAX_TOKENS=4096

# Provider API keys
DASHSCOPE_API_KEY=sk-xxxxx
ZAI_API_KEY=xxxxx
ZAI_API_BASE=https://open.bigmodel.cn/api/paas/v4/
OPENAI_API_KEY=sk-xxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxx

# ── MCP ─────────────────────────────────────────────────
MCP_SERVER_NAME=insight-ai-agent

# ── Skills / Tools ──────────────────────────────────────
BRAVE_API_KEY=
MEMORY_DIR=data
```

### Pydantic Settings 配置

配置文件: `config/settings.py`

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_port: int = 5000
    cors_origins: list[str] = ["*"]
    debug: bool = False
    default_model: str = "dashscope/qwen-max"
    executor_model: str = "dashscope/qwen-max"
    max_tokens: int = 4096
    # ... (see config/settings.py for full list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## 前端（Next.js）

### `.env.local` (开发环境)

```env
# Python Agent Service
PYTHON_SERVICE_URL=http://localhost:5000

# Legacy Dify (移除或留空)
# DIFY_AI_BASE=
# STUDIO_API_KEY=
# STUDIO_WORKFLOW_API_KEY=
```

### `.env.production` (生产环境)

```env
# Python Agent Service (Docker 网络内)
PYTHON_SERVICE_URL=http://agent-service:5000
```
