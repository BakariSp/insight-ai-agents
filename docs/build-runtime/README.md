# Build Runtime — Compile / Execute / Save as App

> 日期: 2026-02-08
> 状态: 设计阶段
> 定位: 独立于 Agent 对话流的按钮触发流水线

---

## 1. 与 Agent 收敛的关系

| 模块 | 入口 | 触发方式 | 职责 |
|------|------|---------|------|
| Unified Agent | 自然语言对话 | AI 自动工具调用 | Quiz / PPT / Docx / 互动网页生成 |
| **Build Runtime** | **前端按钮** | **独立 API 调用** | **Blueprint 编译 / Pipeline 执行 / Save as App** |

Build Runtime 不属于 Agent 对话收敛范围。
AI Agent 只负责前置对话与参数澄清；真正的 build 运行由 pipeline/executor 执行。

---

## 2. 核心设计原则

1. **入口不变**：教师通过按钮触发 Build / Run / Save，不是对话自动调用
2. **内核解耦**：将"一次性生成"和"重复执行"分开
   - Compile = 将会话上下文编译为可复用 Blueprint（静态资产）
   - Execute = 用 Blueprint + 参数执行 pipeline（可观测、可重试、可控预算）
3. **不依赖 Agent 再次决策**：执行由固定 pipeline 跑，不是让 AI 自由发挥
4. **资产化**：支持 Save as App、预览运行、批量运行、失败重试

---

## 3. 架构总览

```
教师点击 Build 按钮
    ↓
┌─────────────────────────────────────────┐
│  Build Compiler                         │
│  输入: 会话上下文 + 实体解析 + 确认步骤  │
│  输出: Blueprint（流程定义，静态资产）    │
│  API:  POST /api/apps/compile → job_id  │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Workflow Runtime / Executor            │
│  输入: Blueprint + params               │
│  执行: 固定 pipeline（可观测/重试/预算） │
│  API:  POST /api/apps/{id}/run          │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Save as App                            │
│  持久化 Blueprint + 执行配置             │
│  支持: 预览 / 发布 / 批量运行 / 重试     │
│  状态: draft → compiling → ready → published │
└─────────────────────────────────────────┘
```

---

## 4. 产品交互

### 4.1 Build 触发

- 教师在 Studio 对话中完成参数澄清（由 Agent 对话处理）
- 点击 **Build** 按钮 → 触发 Compile
- 前端显示编译状态：`draft → compiling → ready`

### 4.2 Run 触发

- 教师点击 **Run** 按钮（或 Preview）
- 触发 Execute，参数可编辑（班级、时间范围等）
- 前端显示执行进度 + 结果页面

### 4.3 Save as App

- Compile 完成后，教师点击 **Save as App**
- 三步向导：选步骤 → 配参数 → 确认编译
- 保存后可复用：换参数重跑、分享给其他教师

---

## 5. 分层设计

### 5.1 Build Compiler

**输入**：
- 当前会话上下文（conversation history）
- 实体解析结果（classId, assignmentId 等）
- 用户确认的步骤列表

**输出**：
- Blueprint（三层模型：DataContract → ComputeGraph → UIComposition）
- 静态资产，不依赖运行时 AI 决策

**关键行为**：
- 幂等：相同输入 → 相同 Blueprint
- 可缓存：同一会话多次 compile 可复用
- 异步：长编译任务返回 job_id，前端轮询状态

### 5.2 Workflow Runtime (Executor)

**输入**：
- Blueprint + 运行参数

**执行**：
- 按 Blueprint 定义的 pipeline 顺序执行
- 数据获取 → 统计计算 → UI 组装
- 每步可观测（进度事件）

**关键行为**：
- 不依赖 Agent 再次决策每一步
- 支持失败重试（单步或全部）
- 支持预算上限（token/cost cap）
- 支持批量执行（多班级同一 Blueprint）

### 5.3 ExecutionTrace 持久化

- 每次执行记录完整 trace（输入、中间结果、输出、耗时、错误）
- 用于调试、审计、成本统计
- Save as App 时关联 trace 作为执行样例

---

## 6. API 设计（建议）

### 6.1 Compile

```
POST /api/apps/compile
Body: { conversationId, steps[], entityContext }
Response: { jobId }

GET /api/apps/compile/{jobId}
Response: { status, progress, blueprint?, error? }
```

### 6.2 Execute

```
POST /api/apps/{appId}/run
Body: { params: { classId, dateRange, ... }, budgetCap? }
Response: { executionId }

GET /api/apps/{appId}/executions/{executionId}
Response: { status, progress, result?, error? }
```

### 6.3 Cost Estimate

```
POST /api/apps/estimate
Body: { blueprint, params }
Response: { estimatedTokens, estimatedCost, estimatedDuration }
```

### 6.4 App Lifecycle

```
GET    /api/apps                        # 列表
GET    /api/apps/{appId}                # 详情
PUT    /api/apps/{appId}/publish        # 发布
DELETE /api/apps/{appId}                # 删除
```

---

## 7. 前端改造

- Save 弹窗升级为三步向导
- 复用 `toolProgress` 与 `data-*` 事件生成可选步骤列表
- 增加编译中状态与失败重试入口
- `createAppFromBuild` 降级为本地缓存 fallback
- App 状态机：`draft → compiling → ready → published`

---

## 8. AI 端改造

- 新增 `ExecutionTrace` 持久化模型
- 实体解析工具化：`resolve_entities`、`resolve_class_context`（供对话阶段使用）
- Compiler 从现有 `PlannerAgent` 逻辑提取，去除对话依赖
- Executor 沿用现有 `ExecutorAgent` 逻辑，增加预算控制和可观测性
- `execute_blueprint` 仅用于预览或运行，不强绑保存动作

---

## 9. 验收指标

| 指标 | 门槛 |
|------|------|
| Compile 成功率 | >= 98% |
| Execute 成功率 | >= 95% |
| Save as App 成功率 | >= 95% |
| Blueprint 复用成功率 | >= 90% |
| Budget-cap 守护正确性 | 100% |
| 现有 Build 路径不受影响 | 回归通过 |

---

## 10. 与现有代码的关系

| 现有代码 | 改造方向 |
|---------|---------|
| `api/conversation.py :: _stream_build` | 保持独立路径，不合入 Unified Agent |
| `agents/planner.py` | Compile 逻辑来源，提取为独立 Compiler |
| `agents/executor.py` | Execute 逻辑来源，增加预算与可观测 |
| `models/blueprint.py` | Blueprint 模型复用，增加 App 元数据 |
| Entity Resolution (~conversation.py:430-569) | 提取为独立工具，对话阶段和 Compile 均可调用 |
