# Insight AI Agent — 文档中心

> **最后更新**: 2026-02-09
> **当前阶段**: AI 原生重构 (Convergence Phase 3+4 合并执行)
> **一句话概述**: 面向教育场景的 AI Agent 服务，教师用自然语言即可生成题目、分析数据、创建互动内容，LLM 原生 Tool Calling 自主编排。

---

## 项目愿景

构建一个 **AI 驱动的教育平台**，教师只需用自然语言描述需求，系统自动：
1. LLM 自主判断需要调用哪些工具
2. 从后端获取数据、执行分析、生成内容
3. 通过 SSE 流式返回结构化结果（Artifact）
4. 支持对已生成内容的结构化修改和深度对话

用户消息 → NativeAgent(tools=subset) → LLM 自主编排 → **SSE 流式返回**

### 面向用户

- **教师**: 通过对话生成题目、PPT、文稿、互动内容，分析班级数据
- **教务管理**: 跨班级/跨学科数据对比
- **前端开发者**: 消费标准化 SSE 事件流 (Data Stream Protocol)

### 核心目标

| 目标 | 说明 | 状态 |
|------|------|------|
| AI 原生 Tool Calling | 单 NativeAgent，LLM 自主选 tool 编排 | 🔄 重构中 |
| 单一工具注册 | `tools/registry.py` + 5 个 toolset 分包 | 🔄 重构中 |
| 薄网关 | `conversation.py` ~100 行，不做业务决策 | 🔄 重构中 |
| 多模型支持 | 通过 LiteLLM 支持 Anthropic/OpenAI/Qwen/GLM 等 | ✅ 已实现 |
| SSE 流式 | Data Stream Protocol，前端契约不变 | ✅ 已实现 |
| 统一 Artifact 模型 | 生成用专用 tool，编辑用通用 patch_artifact | 🔄 重构中 |
| Java 后端对接 | 从 Java 后端获取教育真实数据 | ✅ 已实现 |
| RAG 知识库 | LightRAG + pgvector 文档检索 | ✅ 已实现 |
| 智能题目生成 | generate_quiz_questions tool | ✅ 已实现 |

---

## 文档导航

### 架构设计

| 文档 | 内容 |
|------|------|
| [架构总览](architecture/overview.md) | AI 原生架构全景、NativeAgent、Toolset 策略、项目结构 |
| [NativeAgent 设计](architecture/agents.md) | NativeAgent 核心流程、Toolset 选择、Artifact 编辑模型 |
| [Blueprint 数据模型](architecture/blueprint-model.md) | 可执行蓝图三层模型（保留，作为 tool 输出类型） |
| [后端流程图](architecture/backend-flow.md) | 数据流、RAG 按需调取 |
| [架构优化方案](architecture/architecture-optimization.md) | 三方协调优化设计 |

### 重构方案

| 文档 | 内容 |
|------|------|
| [**AI 原生重构完整方案**](plans/2026-02-09-ai-native-rewrite.md) | Step 0.5–4 完整实施计划、技术决策、工程约束 |

### API 文档

| 文档 | 内容 |
|------|------|
| [当前 API](api/current-api.md) | AI 原生架构的 API 端点（conversation/stream + conversation + health） |
| [SSE 协议](api/sse-protocol.md) | Data Stream Protocol SSE 事件格式 |

### 开发指南

| 文档 | 内容 |
|------|------|
| [快速开始](guides/getting-started.md) | 克隆、安装、启动、验证 |
| [添加新工具](guides/adding-skills.md) | 如何用 @register_tool 添加新工具到 registry |
| [环境变量](guides/environment.md) | 完整环境变量说明 |

### 集成规范

> **注意**: 跨端集成规范已统一维护在 `docs/studio-v1/`。以下为指针或本 repo 独有文档。

| 文档 | 内容 | 备注 |
|------|------|------|
| [三方集成契约规范](integration/three-party-integration-contract.md) | → 指向 `docs/studio-v1/integration/` | 已合并到 root |
| [整体流程设计](integration/overall-flow.md) | → 指向 `docs/studio-v1/architecture/` | 已合并到 root |
| [前端集成](integration/frontend-integration.md) | Next.js Proxy、字段映射、前端改动清单 | 本 repo 独有 |
| [Next.js Proxy 契约](integration/nextjs-proxy.md) | 前端 proxy 路由契约、SSE 透传 | 本 repo 独有 |
| [RAG 向量数据库架构](integration/rag-vectordb-architecture.md) | RAG-Anything + LightRAG + pgvector 完整方案 | Phase 9 |

### Agent 收敛（Convergence）

| 文档 | 内容 |
|------|------|
| [收敛工作区](convergence/README.md) | Phase 1-2 完成，Phase 3+4 由 AI 原生重构取代 |
| [收敛总方案](../../docs/studio-v1/architecture/07-agent-convergence-plan.md) | 架构设计、分阶段迁移 |

### Build Runtime

| 文档 | 内容 |
|------|------|
| [Build Runtime](build-runtime/README.md) | Compile / Execute / Save as App — 按钮触发的独立流水线 |

### 测试与用例

| 文档 | 内容 |
|------|------|
| [测试文档导航](testing/README.md) | 各阶段测试概览 |
| [AI Agent 测试计划](testing/ai-agent-test-plan.md) | NativeAgent 测试策略 |

### 项目管理

| 文档 | 内容 |
|------|------|
| [技术栈](tech-stack.md) | 当前技术栈 |
| [实施路线图](roadmap.md) | Phase 0–9 + AI 原生重构 |
| [变更日志](changelog.md) | 按日期记录所有变更 |
