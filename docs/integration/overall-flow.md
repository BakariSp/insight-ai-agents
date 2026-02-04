# Insight AI Agent 整体流程设计

## 文档目的

本文档描述 Insight AI Agent 的**端到端完整流程**，说明前端、Python Agent、Java 后端、数据库如何协作完成"从用户输入到可交互页面"的全链路。

**抽象层级**: Middle Level（逻辑流程，不涉及具体代码）

**重要**: 本文档描述基础流程。最新的 **App 层级架构**（App → Blueprint Versions → Page Executions）请参考：
- [Java 后端集成规范](./java-backend-spec.md) - 完整的 App 架构设计
- [App 层级架构快速参考](./app-architecture-quickref.md) - 快速参考指南

---

## 系统架构总览

```
用户浏览器
    ↓ (1) JWT Token + 自然语言请求
Next.js 前端 (验证 JWT, 提取 teacherId)
    ↓ (2) HTTP + SSE
Python AI Agent (FastAPI + PydanticAI)
    ↓ (3) 获取数据                    ↓ (6) 保存结果
Java 后端 (Spring Boot)              Java 后端 (保存到 MySQL)
    ↓ (4) 查询                       ↑
MySQL 数据库 ←─────────────────────┘
```

**核心理念**:
- **统一鉴权**: 用户身份验证由 Java 统一管理，前端和 Python 都信任 Java 的鉴权结果
- **职责分离**: Python 专注 AI 生成，Java 管理数据持久化和权限控制
- **数据流向**: 数据从 Java 读取 → Python 处理 → Java 存储

---

## 完整流程分解

### 阶段 1: 用户发起请求

**参与方**: 用户浏览器 → Next.js 前端

**流程**:
1. 用户在界面输入自然语言需求（如："分析 1A 班的期中考试成绩，找出薄弱知识点"）
2. 前端从本地存储获取 JWT Token（用户登录时由 Java 颁发）
3. 前端调用 Next.js API Route: `POST /api/ai/generate`
   - 请求头: `Authorization: Bearer <JWT>`
   - 请求体: `{ prompt: "...", contextData: {...} }`

**输出**: HTTP 请求发往 Next.js 后端

---

### 阶段 2: Next.js 验证并转发

**参与方**: Next.js API Routes → Python Agent

**流程**:
1. Next.js 接收请求，验证 JWT Token 有效性
   - 方式 1: 调用 Java 的 `/auth/verify` 端点
   - 方式 2: 本地验证（如果有共享密钥）
2. 从 JWT 中提取 `teacherId`（教师唯一标识）
3. 构建发往 Python 的请求:
   ```
   POST http://python-backend/api/page/generate
   Headers: X-Teacher-ID: teacher-001
   Body: {
     "prompt": "分析 1A 班的期中考试成绩...",
     "teacherId": "teacher-001",
     "conversationId": "uuid-1234"
   }
   ```
4. 建立 SSE 连接，将 Python 的流式响应转发给前端

**输出**: Python 开始处理，前端开始接收 SSE 事件

---

### 阶段 3: Python 生成 Blueprint（规划阶段）

**参与方**: Python PlannerAgent

**流程**:
1. PlannerAgent 接收请求，解析自然语言
2. 调用 LLM（如 GPT-4），生成结构化的 **Blueprint**
   - Blueprint 包含三层:
     - **Layout**: 页面布局（Grid/Flex 配置）
     - **Components**: 组件列表（Table/Chart/Card）
     - **DataSources**: 数据绑定关系（哪个组件用哪些数据）
3. 发送 SSE 事件给前端:
   ```
   event: BLUEPRINT
   data: { blueprint: {...}, status: "planning_complete" }
   ```

**关键逻辑**:
- LLM 理解用户意图 → 选择合适的 UI 组件
- 识别需要哪些数据源（如：班级信息、成绩数据、统计计算）
- 生成数据绑定路径（如：`$data.grades[0]`, `$compute.average`）

**输出**: 前端显示"正在规划页面..."，Blueprint 传递给 Executor

---

### 阶段 4: Python 获取数据（执行阶段 - 数据获取）

**参与方**: Python ExecutorAgent → Java 后端

**流程**:
1. ExecutorAgent 分析 Blueprint，识别需要的数据源:
   - 需要 `get_class_info(classId="1A")`（注意：是 `classId`，不是 `className`）
   - 需要 `get_submission_data(classId="1A", assignmentId="midterm")`
2. 通过 Adapter 层调用 Java API（已有接口）:
   ```
   GET /api/dify/teacher/teacher-001/classes/1A
   GET /api/dify/teacher/teacher-001/submissions?classId=1A&assignmentId=midterm
   ```
   **注意**: Java 如何验证权限、如何查询数据库是 Java 内部逻辑，Python 不需要关心
3. Java 返回标准化 JSON:
   ```json
   {
     "code": 200,
     "data": {
       "classId": "1A",
       "students": [...],
       "grades": [...]
     }
   }
   ```
4. Python Adapter 将 Java 响应转换为内部数据模型（`ClassInfo`, `GradeData`）
5. 发送 SSE 事件给前端:
   ```
   event: DATA_FETCH
   data: { status: "fetching", progress: "2/3" }
   ```

**容错机制**:
- 如果 Java API 失败 → 使用 Mock 数据降级
- 如果网络超时 → 重试 3 次 + Circuit Breaker

**输出**: `dataContext` 字典，包含所有获取的数据

---

### 阶段 5: Python 计算与组装（执行阶段 - 计算与渲染）

**参与方**: Python ExecutorAgent

**流程**:
1. 执行 Blueprint 中定义的计算:
   - 调用 `calculate_stats` 工具（如：平均分、及格率）
   - 调用 `calculate_distribution` 工具（如：分数分布）
2. 解析数据绑定路径:
   - 组件 A 的数据源是 `$data.grades` → 从 `dataContext["grades"]` 提取
   - 组件 B 的数据源是 `$compute.average` → 从计算结果提取
3. 组装最终 **Page** 模型:
   - 将 Layout、Components、真实数据合并
   - 生成前端可直接渲染的 JSON
4. 发送 SSE 事件给前端:
   ```
   event: PAGE
   data: { page: {...}, status: "rendering" }
   ```

**输出**: 完整的 Page JSON，前端可渲染的可交互页面

---

### 阶段 6: Python 保存 Blueprint + 执行结果到 Java

**参与方**: Python → Java 后端 → MySQL

**核心理念**:
- **Blueprint（设计图）**: 可复用，只存一次
- **Page（执行结果）**: 每次执行生成一个新的快照
- **历史回溯**: 同一个 Blueprint 可以查看所有历史执行记录

**流程**:
1. 生成完成后，Python 调用 Java 的保存接口:
   ```
   POST /api/studio/teacher/teacher-001/blueprints
   Body: {
     "blueprint": {
       "meta": { "pageTitle": "1A班期中分析", "pageType": "analysis" },
       "layout": { "type": "grid", "columns": 3 },
       "components": [...]
     },
     "pageContent": {
       "layout": {...},
       "components": [{ "id": "table-1", "data": [...] }]
     },
     "conversationId": "conv-uuid-5678",
     "blueprintId": null,         // 首次生成为 null，重新执行时传入已有 blueprint_id
     "classIds": ["1A"],          // 班级 ID 数组（可为空，如教案生成）
     "taskContext": null,         // 非班级场景的上下文（如 {subject: "数学", grade: "初一"}）
     "dataContext": {...},        // 缓存原始数据（可选，用于 Patch）
     "computeResults": {...},     // 缓存计算结果（可选）
     "tags": ["期中", "数学"]
   }
   ```

2. Java 处理逻辑（简化）:
   ```
   if (blueprintId == null) {
       // 首次生成：创建新 Blueprint + 新执行记录
       生成 blueprint_id（如 "bp-uuid-1234"）
       插入 ai_blueprints 表
   } else {
       // 重新执行：只创建新执行记录（Blueprint 复用）
       验证 blueprintId 存在且属于该教师
   }

   生成 execution_id（如 "exec-uuid-9999"）
   插入 ai_page_executions 表
   ```

3. Java 返回结果:
   ```json
   {
     "code": 200,
     "data": {
       "blueprintId": "bp-uuid-1234",
       "executionId": "exec-uuid-9999",
       "createdAt": "2026-02-04T10:30:00Z"
     }
   }
   ```

4. Python 发送最终 SSE 事件:
   ```
   event: COMPLETE
   data: {
     blueprintId: "bp-uuid-1234",
     executionId: "exec-uuid-9999",
     status: "complete",
     canShare: true
   }
   ```

**为什么分离 Blueprint 和 Execution？**
- **Blueprint 复用**: 同一个设计可以多次执行（如每月执行一次"期中分析"）
- **历史回溯**: 可以查看"1A班期中分析"这个 Blueprint 的所有历史执行记录
- **发布为 Studio**: Blueprint 可以固化为可复用的 App，其他教师可以直接使用
- **数据一致性**: 所有数据在 MySQL 统一管理，支持 JOIN 查询

**输出**: 前端收到完成通知，显示"生成完成"+ Blueprint ID

---

### 阶段 7: 用户查看 Studio 列表（我的 Blueprints）

**参与方**: Next.js 前端 → Java 后端

**流程**:
1. 用户点击"我的 Studio"按钮
2. 前端调用 Next.js API:
   ```
   GET /api/studio/blueprints?pageType=analysis&page=1
   ```
3. Next.js 转发请求到 Java:
   ```
   GET /api/studio/teacher/teacher-001/blueprints?pageType=analysis&page=1
   Headers: Authorization: Bearer <JWT>
   ```
4. Java 查询 MySQL（JOIN 获取执行次数）:
   ```sql
   SELECT
     b.blueprint_id,
     b.page_title,
     b.page_type,
     b.class_ids,
     b.tags,
     b.created_at,
     COUNT(e.id) AS execution_count,
     MAX(e.created_at) AS latest_execution_time
   FROM ai_blueprints b
   LEFT JOIN ai_page_executions e ON b.blueprint_id = e.blueprint_id
   WHERE b.teacher_id = 'teacher-001'
     AND b.page_type = 'analysis'
   GROUP BY b.blueprint_id
   ORDER BY b.created_at DESC
   LIMIT 20 OFFSET 0;
   ```
5. Java 返回 Blueprint 列表:
   ```json
   {
     "code": 200,
     "data": {
       "items": [
         {
           "blueprintId": "bp-uuid-1234",
           "pageTitle": "1A班期中分析",
           "pageType": "analysis",
           "classIds": ["1A"],
           "tags": ["期中", "数学"],
           "executionCount": 3,
           "latestExecutionTime": "2026-02-04T10:30:00Z",
           "createdAt": "2026-01-10T09:00:00Z"
         }
       ],
       "total": 10,
       "page": 1,
       "pageSize": 20
     }
   }
   ```
6. 前端渲染列表（卡片形式，显示执行次数）

**输出**: 用户看到所有 Blueprint 列表（每个显示"已执行 3 次"）

---

### 阶段 8: 用户查看某个 Blueprint 的执行历史

**参与方**: Next.js 前端 → Java 后端

**流程**:
1. 用户点击某个 Blueprint 卡片（如："1A班期中分析"）
2. 前端调用:
   ```
   GET /api/studio/blueprints/bp-uuid-1234/executions
   ```
3. Next.js 转发到 Java:
   ```
   GET /api/studio/teacher/teacher-001/blueprints/bp-uuid-1234/executions
   Headers: Authorization: Bearer <JWT>
   ```
4. Java 查询该 Blueprint 的所有执行记录:
   ```sql
   SELECT
     e.execution_id,
     e.class_ids,
     e.created_at,
     e.tags
   FROM ai_page_executions e
   WHERE e.blueprint_id = 'bp-uuid-1234'
     AND e.teacher_id = 'teacher-001'
   ORDER BY e.created_at DESC;
   ```
5. Java 返回执行历史:
   ```json
   {
     "code": 200,
     "data": {
       "blueprint": {
         "blueprintId": "bp-uuid-1234",
         "pageTitle": "1A班期中分析",
         "blueprintContent": {...}
       },
       "executions": [
         {
           "executionId": "exec-uuid-9999",
           "classIds": ["1A"],
           "tags": ["2月"],
           "createdAt": "2026-02-04T10:30:00Z"
         },
         {
           "executionId": "exec-uuid-8888",
           "classIds": ["1A", "1B"],
           "tags": ["1月"],
           "createdAt": "2026-01-15T14:20:00Z"
         }
       ]
     }
   }
   ```
6. 前端渲染执行历史时间线（类似图中的历史记录）

**输出**: 用户看到"1A班期中分析"的所有历史执行（2月执行、1月执行等）

---

### 阶段 9: 用户打开某次执行的详情

**参与方**: Next.js 前端 → Java 后端

**流程**:
1. 用户点击某次执行记录（如："2026-02-04 的执行"）
2. 前端调用:
   ```
   GET /api/studio/executions/exec-uuid-9999
   ```
3. Next.js 转发到 Java:
   ```
   GET /api/studio/teacher/teacher-001/executions/exec-uuid-9999
   Headers: Authorization: Bearer <JWT>
   ```
4. Java 验证权限并返回完整数据:
   ```json
   {
     "code": 200,
     "data": {
       "executionId": "exec-uuid-9999",
       "blueprintId": "bp-uuid-1234",
       "pageContent": {
         "layout": {...},
         "components": [{ "id": "table-1", "data": [...] }]
       },
       "dataContext": {...},       // 缓存的原始数据
       "computeResults": {...},    // 缓存的计算结果
       "metadata": {
         "pageTitle": "1A班期中分析",
         "classIds": ["1A"],
         "tags": ["2月"],
         "createdAt": "2026-02-04T10:30:00Z"
       }
     }
   }
   ```
5. 前端使用通用的 `PageRenderer` 组件渲染

**输出**: 用户看到 2026-02-04 那次执行的完整可交互页面（快照）

---

## 数据流向图

```
用户输入
    ↓
前端 UI
    ↓ (自然语言 + JWT)
Next.js API Routes (验证鉴权)
    ↓ (teacherId + prompt)
Python PlannerAgent
    ↓ (Blueprint)
Python ExecutorAgent
    ↓ (数据请求)          ↓ (保存请求)
Java 后端                  Java 后端
    ↓ (查询)              ↓ (插入)
MySQL 数据库 ←─────────┘
    ↑
    └─ (历史记录查询) ← Next.js ← 前端
```

---

## 方案选择理由：为什么选 Java MySQL + Adapter？

### 对比其他方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| **方案 1**: Python 独立数据库 | Python 完全自治 | ❌ 鉴权重复实现<br>❌ 数据孤岛<br>❌ 权限控制重复 |
| **方案 2**: 前端 LocalStorage | 无需后端存储 | ❌ 数据易丢失<br>❌ 无法跨设备<br>❌ 无法分享 |
| **✅ 方案 3**: Java MySQL + Adapter | **统一鉴权**<br>**数据一致性**<br>**易扩展** | 需要 Java 团队配合 |

### 方案 3 的核心优势

#### 1. 统一鉴权链路
```
当前鉴权（已有）:
用户登录 → Java 颁发 JWT → 前端携带 JWT → Next.js 验证 → 提取 teacherId

如果 Python 独立数据库:
❌ Python 需要自己验证 JWT？
❌ 如何防止 teacherId 伪造？
❌ 权限控制逻辑重复实现

采用 Java 存储:
✅ Python 只负责生成，不管鉴权
✅ 存储时调 Java API（已验证的 teacherId）
✅ 前端查询历史时直接调 Java（统一鉴权）
```

#### 2. 业务逻辑统一
```
需求: 教师查看"我的历史分析"
- 按班级筛选
- 分享给同年级教师
- 删除时检查权限

Java 已有数据:
- teacher 表: 教师信息、权限
- classroom 表: 班级归属
- share_permission 表: 分享权限

如果 Python 独立存储:
❌ 需要调 Java 获取教师姓名
❌ 按班级筛选需要先获取班级列表
❌ 分享功能需要重复实现

采用 Java 存储:
✅ 一条 SQL JOIN 搞定
✅ 权限检查复用现有逻辑
✅ 数据备份、恢复统一管理
```

#### 3. 开发成本低
```
Java 团队: 6-9 小时
- 数据表设计: 1-2 小时
- API 开发: 4-6 小时
- 联调测试: 1 小时

Python 团队: 3-4 小时
- Adapter 开发: 2-3 小时
- 联调测试: 1 小时

前端团队: 4-5 小时
- 历史记录页面: 3-4 小时
- 联调测试: 1 小时

总计: 13-18 小时（约 2-3 人天）
```

---

## 关键设计决策

### 1. 为什么使用 SSE 而非 WebSocket？

**SSE (Server-Sent Events)** 优势:
- 单向推送（服务器 → 客户端），符合 AI 生成场景
- 浏览器原生支持，无需额外库
- 自动重连机制
- 可以通过 HTTP/2 复用连接

**WebSocket** 劣势:
- 双向通信对本场景是过度设计
- 需要维护长连接状态
- 负载均衡更复杂

### 2. 为什么 Blueprint 和 Page 分离？

**Blueprint** (规划):
- 描述"要做什么"（Layout、Components、DataSources）
- 可以**预览**（无需真实数据）
- 可以**编辑**（用户调整布局）

**Page** (结果):
- 包含"真实数据"（渲染后的完整 JSON）
- 可以直接渲染（无需再次计算）
- 支持**快照**（历史记录固定状态）

**优势**:
- 用户可以先确认布局，再执行数据获取（节省成本）
- 支持 Patch 更新（只重新计算部分数据）
- 历史记录体积更小（只存 Page，不存原始数据）

### 3. 为什么缓存 dataContext 和 computeResults？

**目的**: 支持 **Patch 机制**

**场景**: 用户修改筛选条件（如："只看数学成绩"）

**无缓存方案**:
1. 重新调用 Java API 获取数据
2. 重新计算统计结果
3. 重新生成 Page

**有缓存方案**:
1. 从缓存中提取原始数据
2. 重新执行筛选逻辑
3. 只更新变化的组件

**性能对比**:
- 无缓存: 2-3 秒（网络 + 计算）
- 有缓存: 0.2-0.5 秒（仅计算）

---

## 可扩展性考虑

### 未来功能扩展

#### 1. 多轮对话优化
```
当前: 每次请求独立
未来: 维护 conversationId
- 用户: "分析 1A 班成绩"
- AI: 生成页面 A
- 用户: "再加一个薄弱知识点分析"
- AI: 在页面 A 基础上追加组件（无需重新获取数据）
```

#### 2. 模板市场
```
当前: 每次从零生成 Blueprint
未来: 提供预设模板
- "期中成绩分析模板"
- "知识点薄弱诊断模板"
- 用户一键应用 → Python 只需填充数据
```

#### 3. 协作与分享
```
当前: 历史记录私有
未来: 分享机制
- 教师 A 生成分析 → 分享给同年级教师 B
- 教师 B 可以查看、评论（不可编辑）
- Java 后端的 ai_page_shares 表支持此功能
```

#### 4. 增量更新（Patch）
```
当前: 修改后重新生成整个页面
未来: 部分更新
- 用户修改筛选条件 → 只更新受影响的组件
- 使用缓存的 dataContext → 减少网络请求
- 通过 PATCH /api/pages/{pageId} 更新
```

---

## 总结

### 系统特点

✅ **统一鉴权**: Java 管理所有用户身份和权限
✅ **职责清晰**: Python 专注 AI 生成，Java 管理持久化
✅ **数据一致**: 所有数据在 MySQL 统一管理
✅ **高可用**: Circuit Breaker + Mock 降级
✅ **可扩展**: 支持模板、分享、增量更新

### 实施优先级

**Phase 1** (当前): 基础流程打通
- Python 生成 Blueprint + Page ✅
- SSE 流式响应 ✅
- Java Adapter 获取数据 ✅

**Phase 2** (下一步): 持久化与历史记录
- Java 数据表设计
- Java 保存/查询 API
- 前端历史记录页面

**Phase 3** (未来): 高级功能
- Patch 增量更新
- 模板市场
- 协作分享

---

## 相关文档

- [Java 后端集成规范](./java-backend-spec.md) - Java 团队实施细节（App 层级架构）
- [App 层级架构快速参考](./app-architecture-quickref.md) - App → Blueprint Versions → Executions
- [前端集成规范](./frontend-integration.md) - Python API 契约与前端对接
- [Java 数据 API](./java-data-api.md) - Phase 5 数据获取对接
- [三方集成契约](./three-party-integration-contract.md) - 前端 ↔ Python ↔ Java 完整契约
