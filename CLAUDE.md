# Insight AI Agent — Claude Code 项目指令

## 项目概览

教育场景 AI Agent 服务。当前: Flask + LiteLLM 基础原型。目标: FastAPI + FastMCP 多 Agent 系统。

文档入口: `docs/README.md`（导航首页，链接到所有子文档）。

主要文档:
- `docs/architecture/` — 架构设计（总览、多 Agent、Blueprint 模型）
- `docs/api/` — API 文档（当前端点、目标端点、SSE 协议）
- `docs/guides/` — 开发指南（快速开始、添加技能、环境变量）
- `docs/integration/` — 集成规范（前端对接、Java 后端）
- `docs/roadmap.md` — 实施路线图
- `docs/changelog.md` — 变更日志
- `docs/tech-stack.md` — 技术栈

## 开发规范

- Python 3.9+，使用 type hints
- 遵循 PEP 8
- 新功能必须有对应测试
- 工具/技能继承 `skills/base.py` 的 `BaseSkill`
- LLM 调用通过 `services/llm_service.py` 的 `LLMService`
- 配置通过 `config.py` 的 `Config` 类 + `.env`

## 文档更新规则

**每次完成功能开发或结构性变更后**，使用 `/update-docs` 命令更新对应的文档文件。

需要更新文档的场景及对应文件:
- 新增或删除文件/模块 → `docs/architecture/overview.md`
- 新增或修改 API 端点 → `docs/api/`
- 新增或修改技能/工具 → `docs/guides/adding-skills.md`
- 完成路线图中的某个任务 → `docs/roadmap.md`
- 依赖变化 (requirements.txt) → `docs/tech-stack.md`
- 架构调整 → `docs/architecture/`
- 所有变更 → `docs/changelog.md`（追加记录）

## 常用命令

```bash
# 启动服务
python app.py

# 运行测试
pytest tests/ -v

# 更新文档
# 使用 /update-docs 命令
```

## 当前关键文件

| 文件 | 职责 |
|------|------|
| `app.py` | Flask 入口，4 个端点 |
| `config.py` | 环境配置 |
| `agents/chat_agent.py` | Agent 工具循环 |
| `services/llm_service.py` | LiteLLM 多模型封装 |
| `skills/base.py` | 技能抽象基类 |
| `skills/web_search.py` | Brave Search |
| `skills/memory.py` | 持久化记忆 |
