# Insight AI Agent — 文档中心

> **最后更新**: 2026-02-07
> **当前阶段**: Phase 9 进行中 (Studio 教师知识库 RAG Pipeline)
> **一句话概述**: 面向教育场景的 AI Agent 服务，教师用自然语言即可构建结构化的数据分析页面并进行对话式交互。

---

## 项目愿景

构建一个 **AI 驱动的教育数据分析平台**，教师只需用自然语言描述需求（如"分析我班级的期中考试成绩"），系统自动：
1. 理解意图并规划分析流程
2. 从后端获取数据并执行统计计算
3. 构建结构化的应用页面（PageSpec）
4. 支持对页面的调整/追问和深度对话

自然语言 → Blueprint（可复用、可替换数据） → 执行 → **PageSpec（可渲染页面）**
数据分析报告、题目生成、互动练习都只是 PageSpec 里的不同 block/component

### 面向用户

- **教师**: 通过对话构建班级数据分析页面，互动页面，题目练习页面
- **教务管理**: 跨班级/跨学科数据对比
- **前端开发者**: 消费标准化 API 和 SSE 事件流

### 核心目标

| 目标 | 说明 | 状态 |
|------|------|------|
| 多模型支持 | 通过 LiteLLM 支持 Anthropic/OpenAI/Qwen/GLM 等 | ✅ 已实现 |
| Agent 工具循环 | LLM 可调用工具获取数据、执行计算 | ✅ 已实现 |
| 可扩展技能框架 | BaseSkill 抽象基类，新增工具只需实现接口 | ✅ 已实现 |
| SSE 流式页面构建 | 页面构建过程实时推送给前端 | ✅ 已实现 |
| 多 Agent 协作 | Planner → Executor → Router → Chat → PageChat | ✅ 已实现 |
| 统一会话网关 | 意图路由 + 置信度控制 + 交互式反问 | ✅ 已实现 |
| FastMCP 工具注册 | 用 FastMCP 替代手写 JSON Schema | ✅ 已实现 |
| Java 后端对接 | 从 Java 后端获取教育真实数据 | ✅ 已实现 |
| SSE Block 事件流 | BLOCK_START/SLOT_DELTA/BLOCK_COMPLETE 逐 block 推送 | ✅ 已实现 |
| Per-Block AI 生成 | 每个 ai_content_slot 独立生成，支持多种 output_format | ✅ 已实现 |
| Patch 机制 | refine 支持 patch_layout/patch_compose/full_rebuild | ✅ 已实现 |
| RAG 知识库 | HKDSE 课纲、评分标准、知识点检索 | ✅ 已实现 |
| 智能题目生成 | Draft→Judge→Repair 流水线 | ✅ 已实现 |
| 教师知识库 | RAG-Anything + LightRAG + pgvector 文档解析与检索 | ✅ AI+Java 就绪 |
| 前端集成 | Next.js 通过 API Routes 代理 | 🔲 待实现 |

---

## 文档导航

### 架构设计

| 文档 | 内容 |
|------|------|
| [架构总览](architecture/overview.md) | 系统全景、当前架构 vs 目标架构、项目结构、核心模块 |
| [后端流程图](architecture/backend-flow.md) | 从用户 Prompt 到输出的完整数据流、意图路由、RAG 按需调取 |
| [架构优化方案](architecture/architecture-optimization.md) | **NEW** 三方协调优化设计、职责划分、数据契约、Phase 8 升级路径 |
| [多 Agent 设计](architecture/agents.md) | PlannerAgent / ExecutorAgent / RouterAgent / ChatAgent 分工与实现 |
| [Blueprint 数据模型](architecture/blueprint-model.md) | 可执行蓝图三层模型、Pydantic 定义、路径引用、完整示例 |

### API 文档

| 文档 | 内容 |
|------|------|
| [当前 API](api/current-api.md) | Phase 5 的 7 个 FastAPI 端点（含统一会话网关 + Java 后端对接） |
| [目标 API](api/target-api.md) | 目标 API 端点，详细请求/响应 Schema |
| [SSE 协议与 Block 格式](api/sse-protocol.md) | SSE 事件协议、6 种页面 Block 类型、CamelCase 映射 |

### 开发指南

| 文档 | 内容 |
|------|------|
| [快速开始](guides/getting-started.md) | 克隆、安装、启动、验证 |
| [添加新技能](guides/adding-skills.md) | 如何新增 BaseSkill / FastMCP 工具 |
| [环境变量](guides/environment.md) | 完整环境变量说明（Python + 前端） |

### 集成规范

> **注意**: 跨端集成规范已统一维护在 `docs/studio-v1/`。以下为指针或本 repo 独有文档。

| 文档 | 内容 | 备注 |
|------|------|------|
| [三方集成契约规范](integration/three-party-integration-contract.md) | → 指向 `docs/studio-v1/integration/` | 已合并到 root |
| [整体流程设计](integration/overall-flow.md) | → 指向 `docs/studio-v1/architecture/` | 已合并到 root |
| [系统架构全览](integration/system-architecture-overview.md) | → 指向 `docs/studio-v1/architecture/` | 已合并到 root |
| [Java 后端集成规范](integration/java-backend-spec.md) | → 指向 root + Backend repo | 已合并 |
| [前端集成](integration/frontend-integration.md) | Next.js Proxy、字段映射、前端改动清单 | 本 repo 独有 |
| [Next.js Proxy 契约](integration/nextjs-proxy.md) | 前端 proxy 路由契约、SSE 透传 | 本 repo 独有 |
| [App 架构速查](integration/app-architecture-quickref.md) | App/Blueprint/Execution 速查卡 | ⚠️ Phase 2+ |
| [API 分离与权限](integration/api-separation-and-permissions.md) | 版本分离 + 权限管理 | ⚠️ Phase 2+ |
| [存储优化方案](integration/storage-optimization-plan.md) | OSS 混合存储策略 | ⚠️ Phase 2+ |
| [AI-MCP Java 集成](integration/ai-mcp-java-integration.md) | 无状态计算 + JWT 透传 | ⚠️ Phase 2+ |
| [RAG 向量数据库架构](integration/rag-vectordb-architecture.md) | RAG-Anything + LightRAG + pgvector 完整方案 | Phase 9 |

### Agent 收敛（Convergence）

| 文档 | 内容 |
|------|------|
| [收敛工作区](convergence/README.md) | 对话生成统一、Phase 1/2 测试报告索引、关键配置 |
| [收敛总方案](../../docs/studio-v1/architecture/07-agent-convergence-plan.md) | 架构设计、分阶段迁移、验收指标、回退策略 |

### Build Runtime

| 文档 | 内容 |
|------|------|
| [Build Runtime](build-runtime/README.md) | Compile / Execute / Save as App — 按钮触发的独立流水线 |

### 测试与用例

| 文档 | 内容 |
|------|------|
| [测试文档导航](testing/README.md) | 各阶段测试概览、Use Case 索引、文档规范 |
| [Phase 4 测试报告](testing/phase4-test-report.md) | 统一会话网关 — 151 项测试 + 7 种 action 场景 |
| [Phase 4 Live 日志](testing/phase4-conversation-log.md) | 7 场景真实 LLM 对话记录 |
| [Phase 4.5 测试报告](testing/phase4.5-test-report.md) | 健壮性增强 — 230 项测试 + 12 种 Use Case |
| [Phase 4.5 Live 日志](testing/phase4.5-conversation-log.md) | 15 场景实体解析对话记录 |

### 项目管理

| 文档 | 内容 |
|------|------|
| [技术栈](tech-stack.md) | 当前 vs 目标技术栈、框架选型理由 |
| [实施路线图](roadmap.md) | Phase 0–9 分阶段任务与进度 |
| [变更日志](changelog.md) | 按日期记录所有变更 |
