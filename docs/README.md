# Insight AI Agent — 文档中心

> **最后更新**: 2026-02-02
> **当前阶段**: Phase 2 完成 → Phase 3 待开始
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
| SSE 流式页面构建 | 页面构建过程实时推送给前端 | 🔲 待实现 |
| 多 Agent 协作 | Planner → Executor → Router 分工协作 | 🔄 PlannerAgent 已实现 |
| FastMCP 工具注册 | 用 FastMCP 替代手写 JSON Schema | ✅ 已实现 |
| Java 后端对接 | 从 Java 后端获取教育真实数据 | 🔲 待实现 |
| 前端集成 | Next.js 通过 API Routes 代理 | 🔲 待实现 |

---

## 文档导航

### 架构设计

| 文档 | 内容 |
|------|------|
| [架构总览](architecture/overview.md) | 系统全景、当前架构 vs 目标架构、项目结构、核心模块 |
| [多 Agent 设计](architecture/agents.md) | PlannerAgent / ExecutorAgent / RouterAgent / ChatAgent 分工与实现 |
| [Blueprint 数据模型](architecture/blueprint-model.md) | 可执行蓝图三层模型、Pydantic 定义、路径引用、完整示例 |

### API 文档

| 文档 | 内容 |
|------|------|
| [当前 API](api/current-api.md) | Phase 2 的 5 个 FastAPI 端点 |
| [目标 API](api/target-api.md) | Phase 1+ 的 5 个 FastAPI 端点，详细请求/响应 Schema |
| [SSE 协议与 Block 格式](api/sse-protocol.md) | SSE 事件协议、6 种页面 Block 类型、CamelCase 映射 |

### 开发指南

| 文档 | 内容 |
|------|------|
| [快速开始](guides/getting-started.md) | 克隆、安装、启动、验证 |
| [添加新技能](guides/adding-skills.md) | 如何新增 BaseSkill / FastMCP 工具 |
| [环境变量](guides/environment.md) | 完整环境变量说明（Python + 前端） |

### 集成规范

| 文档 | 内容 |
|------|------|
| [前端集成](integration/frontend-integration.md) | Next.js Proxy、字段映射、前端改动清单、Mock 策略、错误处理 |
| [Java 后端对接](integration/java-backend.md) | Java API 端点、数据工具映射、对接计划 |

### 项目管理

| 文档 | 内容 |
|------|------|
| [技术栈](tech-stack.md) | 当前 vs 目标技术栈、框架选型理由 |
| [实施路线图](roadmap.md) | Phase 0–6 分阶段任务与进度 |
| [变更日志](changelog.md) | 按日期记录所有变更 |
