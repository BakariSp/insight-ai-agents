# App 层级架构快速参考（v2.0）

> **⚠️ Phase 2+ 规划文档** — 不属于当前 Phase 1 范围。Phase 1 规格见 [docs/studio-v1/phase1/](../../../../docs/studio-v1/phase1/)
>
> **修订日期**: 2026-02-04 (v2.0 - 整合 OSS 存储、版本分离、权限管理)

## 一句话总结

**App (永久身份) → Blueprint Versions (v1, v2...) → Page Executions (执行历史)**

✅ 修改 Blueprint 不会改变 App ID，历史保持连续
✅ **v2.0 新增**: 创建版本 ≠ 执行，大数据存 OSS，支持分享与权限

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

## API 速查（v2.0 扩展）

| 操作 | 端点 | v2.0 变更 |
|------|------|----------|
| **创建 App** | `POST /studio/teacher/{teacherId}/apps` | 支持 `skipInitialExecution`（可选不执行） |
| ⭐ **创建 Blueprint 版本** | `POST /apps/{appId}/blueprints` | **不再自动执行**，支持 `activateImmediately` |
| ⭐ **激活版本** | `POST /apps/{appId}/blueprints/{blueprintId}/activate` | 新增：切换到指定版本 |
| ⭐ **执行 Blueprint** | `POST /apps/{appId}/executions` | 独立接口，使用当前版本 |
| **查询 App 列表** | `GET /apps` | 我的所有 Apps |
| **查询执行历史** | `GET /apps/{appId}/executions` | 返回 thumbnail + OSS URL |
| **查询版本历史** | `GET /apps/{appId}/blueprints` | 某 App 的所有 Blueprint 版本 |
| **查询执行详情** | `GET /executions/{executionId}` | 返回签名 OSS URL |
| ⭐ **分享 App** | `POST /apps/{appId}/shares` | 新增：分享给其他老师 |
| ⭐ **查询分享** | `GET /teacher/{teacherId}/shared-apps` | 新增：查询"分享给我的" |

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

## v2.0 核心优化

### 1. 版本创建与执行分离

**问题**: 原设计中，创建 Blueprint 版本时必须立即执行

**解决**:
- 创建版本：`POST /blueprints` → 只保存设计
- 激活版本：`POST /blueprints/{blueprintId}/activate` → 设置为当前版本
- 执行：`POST /executions` → 独立接口

**优势**:
- 用户可以先保存多个版本，再选择一个执行
- 支持 A/B 测试（对比不同版本的效果）
- 设计阶段不需要真实数据

---

### 2. OSS 混合存储

**问题**: 大字段（page_content, data_context）存 MySQL 影响性能

**解决**:
| 字段 | 大小 | 存储方式 | 原因 |
|------|------|----------|------|
| `blueprint_content` | 3-20KB | MySQL | 小且频繁查询 |
| `page_content` | 50-500KB | OSS | 大，只在查看时加载 |
| `data_context` | 100KB-2MB | OSS | 很大，只在 Patch 时需要 |
| `page_thumbnail` | < 1KB | MySQL | 轻量级预览（列表展示） |

**优势**:
- 列表查询速度提升 10x+（只查 MySQL）
- 存储成本降低 80%+（OSS 比 MySQL 便宜）
- 支持任意大小的 Page（无限制）

---

### 3. 权限与分享

**问题**: 只有拥有者可以访问 App

**解决**:
| 权限 | 说明 | 可执行操作 |
|------|------|------------|
| **owner** | 拥有者 | 全部操作 |
| **edit** | 编辑权限 | 查看、编辑、执行 |
| **execute** | 执行权限 | 查看、执行（不能编辑） |
| **view** | 只读权限 | 只能查看 |

**优势**:
- 支持教师间协作（如科组共享 App）
- 权限分层（不会泄露敏感数据）
- 临时分享（支持过期时间）

---

## 关键设计决策（原架构）

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

## v2.0 新增场景示例

### 场景 5: 先保存设计，稍后执行

**用户操作**: 修改 Blueprint，但先不执行（明天再用真实数据测试）

**API 调用**:
```
1. 创建新版本（不激活）
   POST /apps/{appId}/blueprints
   Body: {
     "blueprint": {...},
     "changeSummary": "增加了趋势图",
     "activateImmediately": false  // 不激活
   }
   Response: { blueprintId: "bp-v2", version: 2, isActive: false }

2. （用户明天来）激活 v2
   POST /apps/{appId}/blueprints/bp-v2/activate
   Response: { version: 2, activatedAt: "..." }

3. 执行 v2
   POST /apps/{appId}/executions
   Body: { pageContent: {...}, classIds: ["1A"] }
   Response: { executionId: "exec-3", blueprintId: "bp-v2" }
```

**数据库状态**:
```
ai_apps:
  - current_version: 2（激活后更新）

ai_blueprints:
  - blueprint_id: "bp-v1", version: 1
  - blueprint_id: "bp-v2", version: 2（新增，初始未激活）

ai_page_executions:
  - execution_id: "exec-1", blueprint_id: "bp-v1"（旧执行）
  - execution_id: "exec-3", blueprint_id: "bp-v2"（新执行）
```

---

### 场景 6: 分享 App 给其他老师

**用户操作**: 老师 A 分享 App 给老师 B（只读权限）

**API 调用**:
```
1. 老师 A 创建分享
   POST /apps/app-uuid-1234/shares
   Body: {
     "sharedToTeacherId": "teacher-B",
     "permission": "view",
     "expiresInDays": 7
   }
   Response: { shareId, shareUrl, expiresAt: "2026-02-11" }

2. 老师 B 查看"分享给我的" Apps
   GET /teacher/teacher-B/shared-apps
   Response: {
     items: [{
       appId: "app-uuid-1234",
       appName: "1A班期中分析",
       permission: "view",
       sharedBy: { teacherId: "teacher-A", teacherName: "张老师" }
     }]
   }

3. 老师 B 查看 App 详情（成功）
   GET /apps/app-uuid-1234
   Response: { appName: "1A班期中分析", ... }

4. 老师 B 尝试修改 Blueprint（失败）
   POST /apps/app-uuid-1234/blueprints
   Response: 403 Forbidden（只有 view 权限）
```

**关键点**:
- ✅ 分享不会泄露班级数据（老师 B 仍需有班级访问权限才能执行）
- ✅ 权限分层（view < execute < edit < owner）
- ✅ 临时分享（7 天后自动失效）

---

### 场景 7: OSS 按需加载

**用户操作**: 查看执行历史列表 → 点击某次执行查看详情

**API 调用**:
```
1. 查询执行历史列表（快速，只查 MySQL）
   GET /apps/app-uuid-1234/executions
   Response: {
     executions: [
       {
         executionId: "exec-uuid-3333",
         thumbnail: {  // 轻量级预览（< 1KB）
           title: "1A班期中分析",
           summary: "平均分 75.5，最高分 98..."
         },
         pageContentUrl: "https://oss.../exec-3333-page.json",
         createdAt: "2026-03-01"
       }
     ]
   }
   // 前端展示列表（无需下载完整 Page）

2. 用户点击"查看" → 下载完整 Page
   - 前端从 pageContentUrl 下载完整 Page JSON
   - 前端渲染页面
```

**性能对比**:
| 操作 | MySQL | OSS | 节省 |
|------|-------|-----|------|
| 查询 100 次执行历史 | 50MB | 100KB | 99.8% |
| 单次加载时间 | 5s | 0.1s | 98% |

---

## 总结

### v2.0 核心优势

1. **版本分离**: 设计 ≠ 执行，灵活性提升
2. **存储优化**: OSS 混合存储，成本降低 80%+，性能提升 10x+
3. **权限管理**: 支持分享与协作，权限分层
4. **按需加载**: 列表查询无需下载完整数据

### 原架构核心优势

1. **连续性**: 修改 Blueprint 不会断开历史
2. **版本控制**: 可以查看"改过几次"，并回退
3. **清晰度**: 用户知道哪些执行用的是旧版本
4. **可扩展**: 支持 A/B 测试（同时维护多个 Blueprint 版本）

### 实施优先级（v2.0 更新）

**Phase 1** (P0): 基础功能 + OSS 存储
- App + Blueprint + Execution 基础流程
- OSS 上传/下载工具类
- 表结构调整（新增 OSS URL 字段）

**Phase 2** (P0): 版本分离⭐ 重要
- 修改 API（创建版本 ≠ 执行）
- 新增激活版本接口
- 独立执行接口

**Phase 3** (P1): 权限管理
- 分享功能（创建、查询、撤销）
- 通用鉴权逻辑
- 权限分层

**Phase 4** (P2): 高级功能
- 自动归档（OSS 冷存储）
- Fork 功能（复制别人的 App）
- 批量分享

---

## 相关文档

- [Java 后端集成规范](./java-backend-spec.md) - 完整的 API 设计（v2.0）
- [存储优化方案](./storage-optimization-plan.md) - OSS 存储策略（v2.0 新增）
- [API 分离 + 权限管理](./api-separation-and-permissions.md) - 版本分离与权限设计（v2.0 新增）
- [整体流程设计](./overall-flow.md) - 端到端流程
- [架构设计总结](./design-summary.md) - 设计决策说明
