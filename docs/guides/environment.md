# 环境变量

> Python 服务 + 前端的完整环境变量说明。

---

## Python 服务

### 当前变量（Phase 2）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEBUG` | 调试模式 | `false` |
| `SERVICE_PORT` | 服务端口 | `5000` |
| `CORS_ORIGINS` | 允许的 CORS 源 | `["*"]` |
| `DEFAULT_MODEL` | 默认 LLM (含 provider 前缀) | `dashscope/qwen-max` |
| `EXECUTOR_MODEL` | ExecutorAgent 使用的模型 | `dashscope/qwen-max` |
| `MAX_TOKENS` | 最大 token 数 | `4096` |
| `TEMPERATURE` | 全局默认温度 (0.0–2.0) | `None` (模型默认) |
| `TOP_P` | 全局默认 Top P (0.0–1.0) | `None` (模型默认) |
| `TOP_K` | 全局默认 Top K (Qwen 支持, OpenAI 忽略) | `None` (模型默认) |
| `SEED` | 全局默认随机种子 | `None` |
| `FREQUENCY_PENALTY` | 频率惩罚 (OpenAI 系列) | `None` |
| `REPETITION_PENALTY` | 重复惩罚 (Qwen/Dashscope 系列) | `None` |
| `RESPONSE_FORMAT` | 全局响应格式 (`json_object` 或留空) | `None` |
| `STOP` | 全局停止序列 (JSON 数组) | `None` |
| `DASHSCOPE_API_KEY` | 阿里通义千问 API Key | - |
| `ZAI_API_KEY` | 智谱 AI API Key | - |
| `ZAI_API_BASE` | 智谱 AI API Base URL | `https://open.bigmodel.cn/api/paas/v4/` |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - |
| `BRAVE_API_KEY` | Brave Search API Key | - |
| `MCP_SERVER_NAME` | MCP 服务名称 | `insight-ai-agent` |
| `MEMORY_DIR` | 持久化记忆文件目录 | `data` |

> **注意**: LLM 生成参数 (`TEMPERATURE`, `TOP_P` 等) 设为 `None` 表示使用模型供应商默认值。
> 每个 Agent 可通过 `LLMConfig` 声明自己的参数覆盖全局默认（见 `config/llm_config.py`）。

### SpringBoot 后端变量（Phase 5 新增）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SPRING_BOOT_BASE_URL` | Java 后端基础地址 | `https://api.insightai.hk` |
| `SPRING_BOOT_API_PREFIX` | API 路径前缀 | `/api` |
| `SPRING_BOOT_ACCESS_TOKEN` | Bearer 访问令牌 | - |
| `SPRING_BOOT_REFRESH_TOKEN` | 刷新令牌 | - |
| `SPRING_BOOT_TIMEOUT` | HTTP 请求超时 (秒) | `15` |
| `USE_MOCK_DATA` | 强制使用 Mock 数据 | `false` |

> **注意**: `USE_MOCK_DATA=false` 时，如果 Java 后端不可用，data tools 会自动 fallback 到 mock 数据。

### 目标变量（待实现）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PLANNER_MODEL` | PlannerAgent 使用的模型 | `openai/gpt-4o-mini` |
| `ROUTER_MODEL` | RouterAgent 使用的模型 | `openai/gpt-4o-mini` |

### `.env` 示例

```env
# ── Service ──────────────────────────────────────────────
DEBUG=true
SERVICE_PORT=5000

# ── LLM ─────────────────────────────────────────────────
DEFAULT_MODEL=dashscope/qwen-max
EXECUTOR_MODEL=dashscope/qwen-max
MAX_TOKENS=4096

# ── LLM Generation Defaults (可选, 留空=模型默认) ────────
# TEMPERATURE=0.7
# TOP_P=0.8
# TOP_K=
# SEED=1234
# FREQUENCY_PENALTY=
# REPETITION_PENALTY=1.1
# RESPONSE_FORMAT=json_object
# STOP=["<|endoftext|>"]

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

# ── SpringBoot Backend ──────────────────────────────────
SPRING_BOOT_BASE_URL=https://api.insightai.hk
SPRING_BOOT_API_PREFIX=/api
SPRING_BOOT_ACCESS_TOKEN=
SPRING_BOOT_REFRESH_TOKEN=
SPRING_BOOT_TIMEOUT=15
USE_MOCK_DATA=false
```

### Pydantic Settings 配置

配置文件: `config/settings.py`

```python
from config.llm_config import LLMConfig
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_port: int = 5000
    cors_origins: list[str] = ["*"]
    debug: bool = False
    default_model: str = "dashscope/qwen-max"
    executor_model: str = "dashscope/qwen-max"
    max_tokens: int = 4096

    # LLM Generation Defaults (None = 模型默认)
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None
    # ... (see config/settings.py for full list)

    def get_default_llm_config(self) -> LLMConfig:
        """构建全局默认 LLMConfig。"""
        return LLMConfig(
            model=self.default_model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            # ...
        )
```

### LLMConfig 参数优先级

```
.env 全局默认  →  Agent 级 LLMConfig  →  per-call **overrides
   最低                                        最高
```

每个 Agent 声明自己的 `LLMConfig`（见 `config/llm_config.py`），通过 `merge()` 合并全局默认。
例如 PlannerAgent 使用低温度 + JSON 输出，ChatAgent 使用高温度。

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
