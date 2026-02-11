# D9 Tool Calling QA — 测试运行指南

## 快速开始

### 1. 启动监控面板（独立进程，保持常开）

```bash
cd insight-ai-agent
python tests/test_tool_calling_qa/serve_monitor.py
```

打开浏览器 http://localhost:8888 — 页面每 1.5s 自动刷新。

> 这是**独立于 pytest 的 HTTP 服务**。pytest 写 JSON，这个服务负责展示。
> 测试跑完后面板保持可用，不会像 pytest 内置 daemon 线程那样退出。

### 2. 跑测试（另一个终端）

```bash
cd insight-ai-agent

# 全部 D9 单模型测试（默认模型）
python -m pytest tests/test_tool_calling_qa/test_d9_execution_fidelity.py -v -s

# 仅跑多模型对比（9 模型 × 15 cases = 135 runs）
python -m pytest tests/test_tool_calling_qa/test_d9_execution_fidelity.py::test_d9_model_comparison -v -s
```

测试结果实时写入 `tests/test_tool_calling_qa/_live_output/results.json`，
监控面板自动拉取并渲染。

---

## 模型列表

所有模型配置在 `conftest.py` → `_CANDIDATE_MODELS`，按 API key 自动过滤。

| 平台 | 模型 | Label | 备注 |
|------|------|-------|------|
| DashScope 百炼 | glm-4.7 | `glm-4.7` | 智谱 GLM |
| DashScope 百炼 | qwen3-max | `qwen3-max` | 通义千问（生产默认） |
| DashScope 百炼 | qwen3-coder-plus | `qwen3-coder` | 代码专长 |
| DashScope 百炼 | deepseek-v3.2 | `deepseek-v3.2` | DeepSeek 最新 |
| DashScope 百炼 | kimi-k2.5 | `kimi-k2.5` | Moonshot Kimi |
| OpenAI | gpt-5.2 | `gpt-5.2` | |
| OpenAI | gpt-5-mini | `gpt-5-mini` | |
| Google | gemini-3-pro-preview | `gemini-3-pro` | |
| Google | gemini-3-flash-preview | `gemini-3-flash` | |

### 百炼限流（实际 RPM / RPS）

各模型**独立限流**，不互相影响。限流维度：主账号下所有 RAM 子账号 + API-KEY 总和。

| 模型 | RPM | 约 RPS | 测试策略 |
|------|-----|--------|---------|
| glm-4.7 | 60 | ~1 | **串行** batch=1, delay=1.2s |
| kimi-k2.5 | 60 | ~1 | **串行** batch=1, delay=1.2s |
| deepseek-v3.2 | 15,000 | ~250 | 并行 batch=5 |
| qwen3-max | 高 | 高 | 并行 batch=5 |
| qwen3-coder-plus | 高 | 高 | 并行 batch=5 |

> 限流策略可能按秒级 RPS (RPM/60) 限制，短时间爆发也会触发。
> 触发限流后通常 **1 分钟内恢复**。
> 参考：https://www.alibabacloud.com/help/zh/model-studio/models

### 已知问题

- **kimi-k2.5**: LiteLLM 解析 DashScope 返回的 tool_call 格式失败 (`UnexpectedModelBehavior`)，待修复
- **gemini-3-pro / flash**: 需要代理访问 Google API，国内直连会 `ConnectError`

---

## 目录结构

```
tests/test_tool_calling_qa/
├── conftest.py                  # 共享 fixtures、模型列表、mock 工具
├── test_d9_execution_fidelity.py # D9 测试用例 + 多模型对比
├── live_monitor.py              # LiveMonitor 单例（写 JSON + 内置 HTTP）
├── monitor_dashboard.html       # 前端面板（暗色主题，自动轮询）
├── serve_monitor.py             # 独立 HTTP 服务（推荐用这个）
├── _live_output/                # 运行时生成（git-ignored）
│   ├── index.html               # 面板副本
│   └── results.json             # 实时测试数据
└── README.md                    # ← 你在看的这个文件
```

## D9 子维度

| Sub | 名称 | 检测什么 |
|-----|------|---------|
| D9a | Promise Without Execution | AI 说"让我来生成"但没调任何工具 |
| D9b | Clarification Loop | 用户已回答，AI 仍反复追问 |
| D9c | Intent Lost After Clarify | 追问后 AI 调了错误工具 |

## 评判标准

```
passed = has_tool          # 调了任何工具
       and has_expected    # 调了正确工具
       and promise_ok      # 没有"说了不做"
```

- `~reclarify`：软警告 — 模型附带调了 ask_clarification 但也调了正确工具（不扣分）
- `RE_CLARIFY_ONLY`：硬失败 — 只调了 ask_clarification，没调正确工具
- `NO_TOOL`：硬失败 — 完全没调工具
- `WRONG:[...]`：硬失败 — 调了错误工具
- `PROMISE_NO_ACT`：硬失败 — 承诺执行但没调工具
