# 环境变量

> Python 服务 + 前端的完整环境变量说明。

---

## Python 服务

### 当前变量（Phase 0）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FLASK_DEBUG` | 调试模式 | `false` |
| `SECRET_KEY` | Flask 密钥 | `dev-secret-key` |
| `LLM_MODEL` | 默认 LLM (含 provider 前缀) | `dashscope/qwen-max` |
| `MAX_TOKENS` | 最大 token 数 | `4096` |
| `DASHSCOPE_API_KEY` | 阿里通义千问 API Key | - |
| `ZAI_API_KEY` | 智谱 AI API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `BRAVE_API_KEY` | Brave Search API Key | - |
| `MCP_SERVER_NAME` | MCP 服务名称 | `insight-ai-agent` |

### 目标变量（Phase 1+）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PLANNER_MODEL` | PlannerAgent 使用的模型 | `openai/gpt-4o-mini` |
| `EXECUTOR_MODEL` | ExecutorAgent 使用的模型 | `openai/gpt-4o` |
| `ROUTER_MODEL` | RouterAgent 使用的模型 | `openai/gpt-4o-mini` |
| `JAVA_BACKEND_URL` | Java 后端地址 | `http://localhost:8080` |
| `USE_MOCK_DATA` | 使用 Mock 数据 | `true` |
| `TOOL_TIMEOUT` | 工具调用超时 (秒) | `10.0` |
| `SERVICE_PORT` | 服务端口 | `8000` |
| `CORS_ORIGINS` | 允许的 CORS 源 | `["http://localhost:3000"]` |

### `.env` 示例

```env
# LLM Models (LiteLLM provider/model format)
PLANNER_MODEL=openai/gpt-4o-mini
EXECUTOR_MODEL=openai/gpt-4o
ROUTER_MODEL=openai/gpt-4o-mini

# Provider API Keys (LiteLLM reads these automatically)
OPENAI_API_KEY=sk-xxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxx
DASHSCOPE_API_KEY=sk-xxxxx

# Java Backend
JAVA_BACKEND_URL=http://localhost:8080
USE_MOCK_DATA=true

# Service
SERVICE_PORT=8000
CORS_ORIGINS=["http://localhost:3000"]
```

### Pydantic Settings 配置

```python
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    planner_model: str = "openai/gpt-4o-mini"
    executor_model: str = "openai/gpt-4o"
    router_model: str = "openai/gpt-4o-mini"

    java_backend_url: str = "http://localhost:8080"
    use_mock_data: bool = True
    tool_timeout: float = 10.0

    service_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## 前端（Next.js）

### `.env.local` (开发环境)

```env
# Python Agent Service
PYTHON_SERVICE_URL=http://localhost:8000

# Legacy Dify (移除或留空)
# DIFY_AI_BASE=
# STUDIO_API_KEY=
# STUDIO_WORKFLOW_API_KEY=
```

### `.env.production` (生产环境)

```env
# Python Agent Service (Docker 网络内)
PYTHON_SERVICE_URL=http://agent-service:8000
```
