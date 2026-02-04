# App 层级架构快速参考

## 一句话总结

**App (永久身份) → Blueprint Versions (v1, v2...) → Page Executions (执行历史)**

✅ 修改 Blueprint 不会改变 App ID，历史保持连续

---

## 核心概念

### App = Studio = 应用

**用户视角**: "1A班期中分析" 这个应用

**系统视角**: `app_id = "app-uuid-1234"`（永久不变）

**关键**: 即使 Blueprint 改过多次，App ID 不变

---

### Blueprint = 设计图 = 版本

**用户视角**: "调整布局，增加趋势图" 这个修改

**系统视角**:
- v1: `blueprint_id = "bp-uuid-7777"`
- v2: `blueprint_id = "bp-uuid-8888"`

**关键**: 每次修改生成新版本，旧版本保留

---

### Execution = 执行记录 = 快照

**用户视角**: "2026-02-04 那次分析"

**系统视角**: `execution_id = "exec-uuid-9999"`（使用 v2 Blueprint）

**关键**: 记录某个时间点使用某个 Blueprint 版本的结果

---

## 数据表关系

```
ai_apps (App 身份)
  ├─ app_id: "app-uuid-1234" (永久不变)
  ├─ current_blueprint_id: "bp-uuid-8888" (当前版本)
  └─ current_version: 2

ai_blueprints (Blueprint 版本)
  ├─ blueprint_id: "bp-uuid-7777", app_id: "app-uuid-1234", version: 1
  └─ blueprint_id: "bp-uuid-8888", app_id: "app-uuid-1234", version: 2

ai_page_executions (执行历史)
  ├─ execution_id: "exec-uuid-1111", app_id: "app-uuid-1234", blueprint_id: "bp-uuid-7777" (v1)
  ├─ execution_id: "exec-uuid-2222", app_id: "app-uuid-1234", blueprint_id: "bp-uuid-8888" (v2)
  └─ execution_id: "exec-uuid-3333", app_id: "app-uuid-1234", blueprint_id: "bp-uuid-8888" (v2)
```

---

## API 速查

| 操作 | 端点 | 说明 |
|------|------|------|
| **创建 App** | `POST /studio/teacher/{teacherId}/apps` | 首次创建：App + Blueprint v1 + Execution 1 |
| **修改 Blueprint** | `POST /studio/teacher/{teacherId}/apps/{appId}/blueprints` | 生成新版本：Blueprint v2 + Execution 2 |
| **重新执行** | `POST /studio/teacher/{teacherId}/apps/{appId}/executions` | 使用当前版本执行 |
| **查询 App 列表** | `GET /studio/teacher/{teacherId}/apps` | 我的所有 Apps |
| **查询执行历史** | `GET /studio/teacher/{teacherId}/apps/{appId}/executions` | 某 App 的所有执行（跨版本） |
| **查询版本历史** | `GET /studio/teacher/{teacherId}/apps/{appId}/blueprints` | 某 App 的所有 Blueprint 版本 |
| **查询执行详情** | `GET /studio/teacher/{teacherId}/executions/{executionId}` | 某次执行的完整数据 |

---

## 用户场景示例

### 场景 1: 首次创建

**用户操作**: "分析 1A 班的期中考试成绩"

**系统行为**:
```
1. 创建 App: app_id = "app-uuid-1234", app_name = "1A班期中分析"
2. 创建 Blueprint v1: blueprint_id = "bp-uuid-7777"
3. 创建 Execution 1: execution_id = "exec-uuid-1111"
```

**数据库状态**:
```
ai_apps:
  - app_id: "app-uuid-1234", current_version: 1

ai_blueprints:
  - blueprint_id: "bp-uuid-7777", app_id: "app-uuid-1234", version: 1

ai_page_executions:
  - execution_id: "exec-uuid-1111", app_id: "app-uuid-1234", blueprint_id: "bp-uuid-7777"
```

---

### 场景 2: 修改 Blueprint

**用户操作**: 点击"编辑 Blueprint" → 调整布局，增加趋势图 → 保存

**系统行为**:
```
1. 创建 Blueprint v2: blueprint_id = "bp-uuid-8888"
2. 更新 App: current_blueprint_id = "bp-uuid-8888", current_version = 2
3. 创建 Execution 2（使用 v2 首次执行）: execution_id = "exec-uuid-2222"
```

**数据库状态**:
```
ai_apps:
  - app_id: "app-uuid-1234", current_version: 2 (更新)

ai_blueprints:
  - blueprint_id: "bp-uuid-7777", version: 1 (保留)
  - blueprint_id: "bp-uuid-8888", version: 2 (新增)

ai_page_executions:
  - execution_id: "exec-uuid-1111", blueprint_id: "bp-uuid-7777" (v1)
  - execution_id: "exec-uuid-2222", blueprint_id: "bp-uuid-8888" (v2)
```

---

### 场景 3: 重新执行

**用户操作**: 下个月，点击"重新执行"

**系统行为**:
```
1. 获取当前版本: current_blueprint_id = "bp-uuid-8888" (v2)
2. 创建 Execution 3（使用 v2）: execution_id = "exec-uuid-3333"
```

**数据库状态**:
```
ai_apps:
  - app_id: "app-uuid-1234", current_version: 2 (不变)

ai_blueprints:
  - (不变)

ai_page_executions:
  - execution_id: "exec-uuid-1111", blueprint_id: "bp-uuid-7777" (v1)
  - execution_id: "exec-uuid-2222", blueprint_id: "bp-uuid-8888" (v2)
  - execution_id: "exec-uuid-3333", blueprint_id: "bp-uuid-8888" (v2, 新增)
```

---

### 场景 4: 查看历史（连续的时间线）

**用户操作**: 点击"1A班期中分析" → 查看执行历史

**API 调用**:
```
GET /studio/teacher/teacher-001/apps/app-uuid-1234/executions
```

**返回结果**:
```json
{
  "executions": [
    { "executionId": "exec-uuid-3333", "blueprintVersion": 2, "createdAt": "2026-03-01", "tags": ["3月"] },
    { "executionId": "exec-uuid-2222", "blueprintVersion": 2, "createdAt": "2026-02-20", "tags": ["2月"] },
    { "executionId": "exec-uuid-1111", "blueprintVersion": 1, "createdAt": "2026-01-10", "tags": ["1月"] }
  ]
}
```

**前端展示**:
```
1A班期中分析
  ├─ 2026-03-01 (v2) 「3月」
  ├─ 2026-02-20 (v2) 「2月，修改后首次执行」
  └─ 2026-01-10 (v1) 「1月，初始版本」
```

✅ **连续性**: 即使 Blueprint 改过，用户仍看到完整时间线

---

## Python 调用示例

### 首次创建

```python
# Python 生成完成后
POST /api/studio/teacher/teacher-001/apps
Body: {
  "appName": "1A班期中分析",
  "appType": "analysis",
  "blueprint": {...},       # Blueprint JSON
  "pageContent": {...},     # Page JSON
  "conversationId": "conv-uuid-5678",
  "classIds": ["1A"],
  "tags": ["期中", "数学"]
}

Response: {
  "appId": "app-uuid-1234",
  "blueprintId": "bp-uuid-7777",
  "version": 1,
  "executionId": "exec-uuid-1111"
}
```

### 重新执行（用户点击"重新执行"）

```python
# Python 重新生成后
POST /api/studio/teacher/teacher-001/apps/app-uuid-1234/executions
Body: {
  "pageContent": {...},     # 新的 Page JSON
  "classIds": ["1A"],
  "tags": ["3月"]
}

Response: {
  "appId": "app-uuid-1234",
  "blueprintId": "bp-uuid-8888",  # 使用当前版本 v2
  "version": 2,
  "executionId": "exec-uuid-3333"
}
```

### 修改 Blueprint（用户编辑后）

```python
# Python 使用新 Blueprint 生成后
POST /api/studio/teacher/teacher-001/apps/app-uuid-1234/blueprints
Body: {
  "blueprint": {...},           # 新的 Blueprint JSON
  "pageContent": {...},         # 使用新 Blueprint 的首次执行
  "changeSummary": "调整了布局，增加了趋势图",
  "classIds": ["1A"],
  "tags": ["2月"]
}

Response: {
  "appId": "app-uuid-1234",
  "blueprintId": "bp-uuid-8888",  # 新版本 ID
  "version": 2,                    # 版本号递增
  "executionId": "exec-uuid-2222"
}
```

---

## 前端展示示例

### App 列表页

```
我的 Studio
  ┌─────────────────────────────┐
  │ 1A班期中分析                │
  │ v2 · 已执行 3 次            │
  │ 最近: 2026-03-01            │
  │ 标签: 期中 数学             │
  └─────────────────────────────┘
  ┌─────────────────────────────┐
  │ 1B班薄弱知识点诊断          │
  │ v1 · 已执行 1 次            │
  │ 最近: 2026-02-03            │
  │ 标签: 数学                  │
  └─────────────────────────────┘
```

### 执行历史页（点击某个 App）

```
1A班期中分析 (当前版本: v2)

执行历史
  ├─ 2026-03-01 (v2) 「3月」 [查看]
  ├─ 2026-02-20 (v2) 「2月，修改后首次执行」 [查看]
  └─ 2026-01-10 (v1) 「1月，初始版本」 [查看]

版本历史
  ├─ v2 (当前): 调整了布局，增加了趋势图 · 已执行 2 次 [查看] [激活]
  └─ v1: 初始版本 · 已执行 1 次 [查看] [激活]

[重新执行] [编辑 Blueprint] [分享]
```

---

## 关键设计决策

### 为什么需要 App 层级？

**问题**: 如果没有 App 层级，修改 Blueprint 会怎样？

**原方案**（无 App 层级）:
```
用户修改 Blueprint
  → 生成新的 blueprint_id
  → 历史记录断开
  → 用户看到两个独立的 Studio
```

**新方案**（有 App 层级）:
```
用户修改 Blueprint
  → app_id 不变
  → 生成 Blueprint v2
  → 历史记录连续
  → 用户看到同一个 App 的完整历史
```

✅ **连续性**: App 身份不变，体验连续

---

### 为什么 execution 表有 app_id 冗余字段？

**目的**: 提升查询性能

**查询场景**: "某 App 的所有执行历史"

**无冗余字段**:
```sql
SELECT e.*
FROM ai_page_executions e
JOIN ai_blueprints b ON e.blueprint_id = b.blueprint_id
WHERE b.app_id = 'app-uuid-1234';
-- 需要 JOIN
```

**有冗余字段**:
```sql
SELECT e.*
FROM ai_page_executions e
WHERE e.app_id = 'app-uuid-1234';
-- 无需 JOIN，性能更好
```

---

## 常见问题

### Q: 如果用户想回退到旧版本怎么办？

**方案**: 添加"激活版本"接口

```
POST /apps/{appId}/blueprints/{blueprintId}/activate

Java 逻辑:
UPDATE ai_apps
SET current_blueprint_id = 'bp-uuid-7777',  -- 回退到 v1
    current_version = 1
WHERE app_id = 'app-uuid-1234';
```

**效果**: 下次"重新执行"时，使用 v1 Blueprint

---

### Q: 如何知道某次执行用的是哪个版本？

**方案**: 查询执行详情时，JOIN Blueprint 表

```sql
SELECT
  e.*,
  b.version AS blueprint_version,
  b.change_summary
FROM ai_page_executions e
JOIN ai_blueprints b ON e.blueprint_id = b.blueprint_id
WHERE e.execution_id = 'exec-uuid-2222';

结果: blueprint_version = 2, change_summary = "调整了布局，增加了趋势图"
```

---

### Q: 删除 App 会删除所有数据吗？

**答案**: 是的，由于外键 CASCADE

```
DELETE FROM ai_apps WHERE app_id = 'app-uuid-1234';

自动删除:
  - ai_blueprints 中所有相关记录（v1, v2...）
  - ai_page_executions 中所有相关记录（所有执行历史）
```

**建议**: 实现软删除（`is_deleted` 字段）+ 定期归档

---

## 总结

### 核心优势

1. **连续性**: 修改 Blueprint 不会断开历史
2. **版本控制**: 可以查看"改过几次"，并回退
3. **清晰度**: 用户知道哪些执行用的是旧版本
4. **可扩展**: 支持 A/B 测试（同时维护多个 Blueprint 版本）

### 实施优先级

**Phase 1** (P0): App + Blueprint + Execution 基础流程

**Phase 2** (P1): 版本控制（修改 Blueprint、查询版本历史）

**Phase 3** (P2): 高级功能（回退版本、分享、发布为 Studio）

---

## 相关文档

- [Java 后端集成规范](./java-backend-spec.md) - 完整的 API 设计
- [整体流程设计](./overall-flow.md) - 端到端流程
- [架构设计总结](./design-summary.md) - 设计决策说明
