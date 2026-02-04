# Java 后端集成规范（App 层级架构）

## 文档目的

本文档面向 **Java 后端团队**，说明为支持 AI Agent 的历史记录持久化和权限管理，需要实现的数据表、API 端点、业务逻辑。

**核心架构**: App → Blueprint Versions → Page Executions

**抽象层级**: Middle Level（逻辑流程 + 数据结构设计，不含具体 Java 代码）

**修订日期**: 2026-02-04

---

## 核心职责

Java 后端在本方案中承担三个核心职责：

1. **App 管理**: 管理应用身份（永久不变的 app_id），支持 Blueprint 版本迭代
2. **权限管理**: 统一鉴权，验证 teacherId 合法性，检查班级访问权限
3. **历史记录查询**: 支持查询连续的执行历史（跨 Blueprint 版本）

**关键原则**:
- **App 身份不变**: 修改 Blueprint 不会改变 App ID，历史连续
- **版本控制**: Blueprint 可以修改，每次修改生成新版本（v1, v2, v3...）
- **连续历史**: 查询执行历史时，跨版本展示（用户体验连续）

---

## 核心设计理念

### 架构层级

```
App (应用/Studio，身份层)
  ↓ 1:N
Blueprint Versions (v1, v2, v3... 设计版本)
  ↓ 1:N
Page Executions (执行历史)
```

### 用户场景

**场景**: 用户创建"1A班期中分析"

```
1月: 创建 App → Blueprint v1 → 执行 1
2月: 修改 Blueprint → Blueprint v2 → 执行 2
3月: 继续使用 v2 → 执行 3

用户查看历史:
  1A班期中分析 (app_id: app-uuid-1234)
    ├─ 2026-03-01 (v2) 「3月」
    ├─ 2026-02-20 (v2) 「2月，修改后首次执行」
    └─ 2026-01-10 (v1) 「1月，初始版本」
```

✅ **连续性**: 即使 Blueprint 改过，用户仍看到完整时间线

---

## 数据表设计

### 1. ai_apps 表（应用/Studio）

**用途**: 代表一个"应用"的永久身份

#### 字段说明（逻辑层级）

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 数据库记录 ID | 12345 |
| `app_id` | VARCHAR(100) | UNIQUE, NOT NULL | App 唯一 ID（永久不变） | "app-uuid-1234" |
| `teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 创建者 ID | "teacher-001" |
| `conversation_id` | VARCHAR(100) | NULL | 首次对话 ID（追溯来源） | "conv-uuid-5678" |
| `app_name` | VARCHAR(200) | NOT NULL | App 名称 | "1A班期中分析" |
| `app_type` | VARCHAR(50) | NOT NULL, INDEX | 类型 | "analysis", "question_generation", "grading", "lesson" |
| `current_blueprint_id` | VARCHAR(100) | NOT NULL | 当前使用的 Blueprint 版本 | "bp-uuid-9999" |
| `current_version` | INT | NOT NULL | 当前版本号 | 2 |
| `class_ids` | JSON | NULL | 关联班级 ID 数组（可为空） | `["1A", "1B"]` |
| `task_context` | JSON | NULL | 任务上下文（非班级场景） | `{subject: "数学", grade: "初一"}` |
| `is_published` | BOOLEAN | DEFAULT FALSE | 是否发布为 Studio | FALSE |
| `studio_name` | VARCHAR(200) | NULL | 发布后的名称 | "期中成绩分析模板" |
| `tags` | JSON | NULL | 标签数组 | `["期中", "数学"]` |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 | "2026-01-10 09:00:00" |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 | "2026-02-20 10:00:00" |

#### 关键说明

- **app_id**: 永久不变的身份标识，用户看到的"1A班期中分析"就是这个 App
- **current_blueprint_id**: 指向当前使用的 Blueprint 版本
- **current_version**: 当前版本号（每次修改 Blueprint 递增）
- **class_ids 可为空**: 支持教案生成等非班级场景

#### 索引设计

| 索引名 | 字段 | 类型 | 目的 |
|--------|------|------|------|
| `PRIMARY` | `id` | PRIMARY KEY | 主键 |
| `idx_app_id` | `app_id` | UNIQUE INDEX | 唯一标识 App |
| `idx_teacher_created` | `teacher_id`, `created_at` | COMPOSITE INDEX | 查询"我的 Apps" |
| `idx_app_type` | `app_type` | INDEX | 按类型筛选 |

---

### 2. ai_blueprints 表（Blueprint 版本）

**用途**: 存储 App 的每个版本的设计

#### 字段说明（逻辑层级）

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 数据库记录 ID | 67890 |
| `blueprint_id` | VARCHAR(100) | UNIQUE, NOT NULL | Blueprint 唯一 ID | "bp-uuid-7777" |
| `app_id` | VARCHAR(100) | NOT NULL, INDEX | 关联的 App ID（外键） | "app-uuid-1234" |
| `version` | INT | NOT NULL | 版本号（从 1 开始） | 1 |
| `blueprint_content` | JSON | NOT NULL | Blueprint 完整 JSON | `{meta: {...}, layout: {...}, components: [...]}` |
| `change_summary` | VARCHAR(500) | NULL | 修改说明（v2+ 需要） | "调整了布局，增加了趋势图" |
| `created_by` | VARCHAR(50) | NOT NULL | 创建者（通常是 teacher_id） | "teacher-001" |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 | "2026-02-20 10:00:00" |

#### 关键说明

- **app_id + version**: 唯一标识一个 Blueprint 版本
- **change_summary**: 记录每次修改的原因（用于版本历史展示）
- **blueprint_content**: 存储完整的 Blueprint JSON

#### 索引设计

| 索引名 | 字段 | 类型 | 目的 |
|--------|------|------|------|
| `PRIMARY` | `id` | PRIMARY KEY | 主键 |
| `idx_blueprint_id` | `blueprint_id` | UNIQUE INDEX | 唯一标识 Blueprint |
| `idx_app_version` | `app_id`, `version` | COMPOSITE UNIQUE INDEX | 查询某 App 的某版本 |

#### 外键约束

```
FOREIGN KEY (app_id)
  REFERENCES ai_apps(app_id)
  ON DELETE CASCADE
```
**含义**: 删除 App 时，自动删除所有 Blueprint 版本

---

### 3. ai_page_executions 表（执行历史）

**用途**: 存储 Blueprint 的每次执行结果

#### 字段说明（逻辑层级）

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 数据库记录 ID | 99999 |
| `execution_id` | VARCHAR(100) | UNIQUE, NOT NULL | 执行唯一 ID | "exec-uuid-9999" |
| `app_id` | VARCHAR(100) | NOT NULL, INDEX | 关联的 App ID（冗余字段，便于查询） | "app-uuid-1234" |
| `blueprint_id` | VARCHAR(100) | NOT NULL, INDEX | 本次执行使用的 Blueprint 版本 | "bp-uuid-7777" |
| `teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 执行者 ID | "teacher-001" |
| `page_content` | JSON | NOT NULL | 本次执行的 Page 完整 JSON（含真实数据） | `{layout: {...}, components: [{data: [...]}]}` |
| `data_context` | JSON | NULL | 缓存的原始数据（用于 Patch 更新） | `{grades: [...], classInfo: {...}}` |
| `compute_results` | JSON | NULL | 缓存的计算结果（用于 Patch 更新） | `{average: 75.5, distribution: [...]}` |
| `class_ids` | JSON | NULL | 本次执行关联的班级（可能与 App 不同） | `["1A"]` |
| `tags` | JSON | NULL | 本次执行的标签 | `["2月", "期中"]` |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP, INDEX | 执行时间 | "2026-02-04 10:30:00" |

#### 关键说明

- **app_id**: 冗余字段，便于查询"某 App 的所有执行历史"（无需 JOIN Blueprint 表）
- **blueprint_id**: 记录本次执行用的是哪个版本
- **class_ids 可变**: 某次执行可能只针对部分班级

#### 索引设计

| 索引名 | 字段 | 类型 | 目的 |
|--------|------|------|------|
| `PRIMARY` | `id` | PRIMARY KEY | 主键 |
| `idx_execution_id` | `execution_id` | UNIQUE INDEX | 唯一标识执行记录 |
| `idx_app_created` | `app_id`, `created_at` | COMPOSITE INDEX | 查询"某 App 的执行历史"（高频） |
| `idx_blueprint_id` | `blueprint_id` | INDEX | 查询"某 Blueprint 版本的执行历史" |

#### 外键约束

```
FOREIGN KEY (app_id)
  REFERENCES ai_apps(app_id)
  ON DELETE CASCADE

FOREIGN KEY (blueprint_id)
  REFERENCES ai_blueprints(blueprint_id)
  ON DELETE CASCADE
```

---

### 4. ai_app_shares 表（分享）(可选)

**用途**: 支持 App 或执行记录的分享

#### 字段说明

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 分享记录 ID |
| `resource_type` | VARCHAR(20) | NOT NULL | 'app' 或 'execution' |
| `resource_id` | VARCHAR(100) | NOT NULL | app_id 或 execution_id |
| `shared_by_teacher_id` | VARCHAR(50) | NOT NULL | 分享者 ID |
| `shared_to_teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 接收者 ID |
| `permission` | VARCHAR(20) | DEFAULT 'view' | 'view', 'comment', 'edit' |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 分享时间 |

---

## API 端点设计

### 基础路径
```
/api/studio/teacher/{teacherId}/apps
```

---

### 1. 创建 App + Blueprint v1 + 首次执行

**端点**: `POST /api/studio/teacher/{teacherId}/apps`

**请求体**:
```json
{
  "appName": "1A班期中分析",
  "appType": "analysis",
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
  "classIds": ["1A"],          // 可选
  "taskContext": null,         // 可选
  "dataContext": {...},        // 可选
  "computeResults": {...},     // 可选
  "tags": ["期中", "数学"]
}
```

**业务逻辑**:

1. **鉴权验证**:
   ```
   - 验证 JWT Token，提取 teacherId
   - 确保路径中的 {teacherId} 与 Token 中的一致
   ```

2. **权限检查（仅当 classIds 非空时）**:
   ```
   if (classIds != null && classIds.length > 0) {
       查询: SELECT class_id FROM teacher_class WHERE teacher_id = ?
       检查: classIds 中的每个 ID 都在查询结果中
       如果不在 → 返回 403 Forbidden
   }
   ```

3. **创建 App**:
   ```
   生成 app_id（如 "app-uuid-1234"）
   生成 blueprint_id（如 "bp-uuid-7777"）

   INSERT INTO ai_apps (
     app_id, teacher_id, conversation_id, app_name, app_type,
     current_blueprint_id, current_version, class_ids, tags
   ) VALUES (
     'app-uuid-1234', 'teacher-001', 'conv-uuid-5678', '1A班期中分析', 'analysis',
     'bp-uuid-7777', 1, '["1A"]', '["期中", "数学"]'
   );
   ```

4. **创建 Blueprint v1**:
   ```
   INSERT INTO ai_blueprints (
     blueprint_id, app_id, version, blueprint_content, created_by
   ) VALUES (
     'bp-uuid-7777', 'app-uuid-1234', 1, {...}, 'teacher-001'
   );
   ```

5. **创建首次执行记录**:
   ```
   生成 execution_id（如 "exec-uuid-1111"）

   INSERT INTO ai_page_executions (
     execution_id, app_id, blueprint_id, teacher_id,
     page_content, data_context, compute_results, class_ids, tags
   ) VALUES (
     'exec-uuid-1111', 'app-uuid-1234', 'bp-uuid-7777', 'teacher-001',
     {...}, {...}, {...}, '["1A"]', '["期中", "数学"]'
   );
   ```

6. **返回结果**:
   ```json
   {
     "code": 200,
     "data": {
       "appId": "app-uuid-1234",
       "blueprintId": "bp-uuid-7777",
       "version": 1,
       "executionId": "exec-uuid-1111",
       "createdAt": "2026-01-10T09:00:00Z"
     }
   }
   ```

**关键点**:
- 首次创建同时生成 App、Blueprint v1、Execution 1
- `app_id` 永久不变，作为应用的身份标识

---

### 2. 修改 Blueprint（生成新版本）

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/blueprints`

**请求体**:
```json
{
  "blueprint": {
    "meta": { "pageTitle": "1A班期中分析（优化版）", "pageType": "analysis" },
    "layout": { "type": "grid", "columns": 4 },  // 修改：从 3 列改为 4 列
    "components": [...]  // 修改：增加了趋势图
  },
  "pageContent": {
    "layout": {...},
    "components": [...]  // 使用新 Blueprint 的首次执行结果
  },
  "changeSummary": "调整了布局，增加了趋势图",
  "classIds": ["1A"],
  "tags": ["2月"]
}
```

**业务逻辑**:

1. **鉴权验证**:
   ```
   验证 JWT Token
   查询 App: WHERE app_id = 'app-uuid-1234'
   检查: teacher_id == 当前用户
   如果不是 → 返回 403
   ```

2. **生成新 Blueprint 版本**:
   ```
   查询当前最大版本号:
     SELECT MAX(version) FROM ai_blueprints WHERE app_id = 'app-uuid-1234'
     结果: 1

   新版本号 = 1 + 1 = 2
   生成新 blueprint_id（如 "bp-uuid-8888"）

   INSERT INTO ai_blueprints (
     blueprint_id, app_id, version, blueprint_content, change_summary, created_by
   ) VALUES (
     'bp-uuid-8888', 'app-uuid-1234', 2, {...}, '调整了布局，增加了趋势图', 'teacher-001'
   );
   ```

3. **更新 App**:
   ```
   UPDATE ai_apps
   SET current_blueprint_id = 'bp-uuid-8888',
       current_version = 2,
       updated_at = CURRENT_TIMESTAMP
   WHERE app_id = 'app-uuid-1234';
   ```

4. **创建首次执行记录（使用新版本）**:
   ```
   生成 execution_id（如 "exec-uuid-2222"）

   INSERT INTO ai_page_executions (
     execution_id, app_id, blueprint_id, teacher_id,
     page_content, class_ids, tags
   ) VALUES (
     'exec-uuid-2222', 'app-uuid-1234', 'bp-uuid-8888', 'teacher-001',
     {...}, '["1A"]', '["2月"]'
   );
   ```

5. **返回结果**:
   ```json
   {
     "code": 200,
     "data": {
       "appId": "app-uuid-1234",
       "blueprintId": "bp-uuid-8888",
       "version": 2,
       "executionId": "exec-uuid-2222",
       "createdAt": "2026-02-20T10:00:00Z"
     }
   }
   ```

---

### 3. 重新执行（使用当前版本）

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/executions`

**请求体**:
```json
{
  "pageContent": {...},      // 新的执行结果
  "classIds": ["1A"],
  "tags": ["3月"]
}
```

**业务逻辑**:

1. **鉴权验证** + **获取当前版本**:
   ```
   查询 App: WHERE app_id = 'app-uuid-1234'
   检查权限: teacher_id == 当前用户
   获取: current_blueprint_id = 'bp-uuid-8888'（v2）
   ```

2. **创建执行记录**:
   ```
   生成 execution_id（如 "exec-uuid-3333"）

   INSERT INTO ai_page_executions (
     execution_id, app_id, blueprint_id, teacher_id,
     page_content, class_ids, tags
   ) VALUES (
     'exec-uuid-3333', 'app-uuid-1234', 'bp-uuid-8888', 'teacher-001',
     {...}, '["1A"]', '["3月"]'
   );
   ```

3. **返回结果**:
   ```json
   {
     "code": 200,
     "data": {
       "appId": "app-uuid-1234",
       "blueprintId": "bp-uuid-8888",
       "version": 2,
       "executionId": "exec-uuid-3333",
       "createdAt": "2026-03-01T10:00:00Z"
     }
   }
   ```

**关键点**: 使用当前版本（v2）执行，不创建新 Blueprint

---

### 4. 查询我的 Apps（应用列表）

**端点**: `GET /api/studio/teacher/{teacherId}/apps`

**请求参数**:
```
?appType=analysis       // 可选：按类型筛选
&tags=期中,数学         // 可选：按标签筛选
&page=1                 // 页码
&pageSize=20            // 每页条数
```

**查询逻辑**:
```sql
SELECT
  a.app_id,
  a.app_name,
  a.app_type,
  a.current_version,
  a.class_ids,
  a.tags,
  a.created_at,
  a.updated_at,
  COUNT(e.id) AS execution_count,
  MAX(e.created_at) AS latest_execution_time
FROM ai_apps a
LEFT JOIN ai_page_executions e ON a.app_id = e.app_id
WHERE a.teacher_id = 'teacher-001'
  AND (? IS NULL OR a.app_type = ?)
GROUP BY a.app_id
ORDER BY a.updated_at DESC
LIMIT 20 OFFSET 0;
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "appId": "app-uuid-1234",
        "appName": "1A班期中分析",
        "appType": "analysis",
        "currentVersion": 2,
        "classIds": ["1A"],
        "tags": ["期中", "数学"],
        "executionCount": 3,
        "latestExecutionTime": "2026-03-01T10:00:00Z",
        "createdAt": "2026-01-10T09:00:00Z",
        "updatedAt": "2026-02-20T10:00:00Z"
      }
    ],
    "pagination": {
      "total": 10,
      "page": 1,
      "pageSize": 20,
      "totalPages": 1
    }
  }
}
```

---

### 5. 查询某个 App 的执行历史（连续的，跨版本）

**端点**: `GET /api/studio/teacher/{teacherId}/apps/{appId}/executions`

**查询逻辑**:
```sql
SELECT
  e.execution_id,
  e.created_at,
  e.class_ids,
  e.tags,
  b.blueprint_id,
  b.version AS blueprint_version,
  b.change_summary
FROM ai_page_executions e
JOIN ai_blueprints b ON e.blueprint_id = b.blueprint_id
WHERE e.app_id = 'app-uuid-1234'
  AND e.teacher_id = 'teacher-001'
ORDER BY e.created_at DESC;
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "app": {
      "appId": "app-uuid-1234",
      "appName": "1A班期中分析",
      "currentVersion": 2
    },
    "executions": [
      {
        "executionId": "exec-uuid-3333",
        "blueprintId": "bp-uuid-8888",
        "blueprintVersion": 2,
        "changeSummary": "调整了布局，增加了趋势图",
        "classIds": ["1A"],
        "tags": ["3月"],
        "createdAt": "2026-03-01T10:00:00Z"
      },
      {
        "executionId": "exec-uuid-2222",
        "blueprintId": "bp-uuid-8888",
        "blueprintVersion": 2,
        "changeSummary": "调整了布局，增加了趋势图",
        "classIds": ["1A"],
        "tags": ["2月"],
        "createdAt": "2026-02-20T10:00:00Z"
      },
      {
        "executionId": "exec-uuid-1111",
        "blueprintId": "bp-uuid-7777",
        "blueprintVersion": 1,
        "changeSummary": null,
        "classIds": ["1A"],
        "tags": ["1月"],
        "createdAt": "2026-01-10T09:00:00Z"
      }
    ]
  }
}
```

**关键点**:
- ✅ 连续的历史（跨 Blueprint 版本）
- ✅ 显示每次执行用的是哪个版本
- ✅ 用户体验连续（即使 Blueprint 改过）

---

### 6. 查询某个 App 的 Blueprint 版本历史

**端点**: `GET /api/studio/teacher/{teacherId}/apps/{appId}/blueprints`

**查询逻辑**:
```sql
SELECT
  b.blueprint_id,
  b.version,
  b.change_summary,
  b.created_at,
  a.current_blueprint_id,
  COUNT(e.id) AS execution_count
FROM ai_blueprints b
JOIN ai_apps a ON b.app_id = a.app_id
LEFT JOIN ai_page_executions e ON b.blueprint_id = e.blueprint_id
WHERE b.app_id = 'app-uuid-1234'
  AND a.teacher_id = 'teacher-001'
GROUP BY b.blueprint_id
ORDER BY b.version DESC;
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "blueprints": [
      {
        "blueprintId": "bp-uuid-8888",
        "version": 2,
        "changeSummary": "调整了布局，增加了趋势图",
        "executionCount": 2,
        "createdAt": "2026-02-20T10:00:00Z",
        "isCurrent": true
      },
      {
        "blueprintId": "bp-uuid-7777",
        "version": 1,
        "changeSummary": null,
        "executionCount": 1,
        "createdAt": "2026-01-10T09:00:00Z",
        "isCurrent": false
      }
    ]
  }
}
```

**用途**: 用户可以查看"这个 App 改过几次"，并回退到旧版本

---

### 7. 获取某次执行的详情

**端点**: `GET /api/studio/teacher/{teacherId}/executions/{executionId}`

**查询逻辑**:
```sql
SELECT
  e.*,
  a.app_name,
  b.version AS blueprint_version
FROM ai_page_executions e
JOIN ai_apps a ON e.app_id = a.app_id
JOIN ai_blueprints b ON e.blueprint_id = b.blueprint_id
WHERE e.execution_id = 'exec-uuid-9999'
  AND e.teacher_id = 'teacher-001';
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "executionId": "exec-uuid-9999",
    "appId": "app-uuid-1234",
    "appName": "1A班期中分析",
    "blueprintId": "bp-uuid-8888",
    "blueprintVersion": 2,
    "pageContent": {...},
    "dataContext": {...},
    "computeResults": {...},
    "metadata": {
      "classIds": ["1A"],
      "tags": ["2月"],
      "createdAt": "2026-02-04T10:30:00Z"
    }
  }
}
```

---

### 8. 删除 App（及所有 Blueprint 和执行记录）

**端点**: `DELETE /api/studio/teacher/{teacherId}/apps/{appId}`

**业务逻辑**:
```
1. 验证 JWT Token
2. 查询 App: WHERE app_id = 'app-uuid-1234'
3. 检查: teacher_id == 当前用户
4. 如果不是 → 返回 403
5. 删除: DELETE FROM ai_apps WHERE app_id = 'app-uuid-1234'
   （由于外键 CASCADE，所有 Blueprint 和 Execution 会自动删除）
```

---

### 9. Patch 更新某次执行

**端点**: `PATCH /api/studio/teacher/{teacherId}/executions/{executionId}`

**请求体**:
```json
{
  "pageContent": {...},       // 更新后的 Page JSON
  "computeResults": {...}     // 更新后的计算结果
}
```

**业务逻辑**:
```
1. 验证权限
2. 更新:
   UPDATE ai_page_executions
   SET page_content = ?, compute_results = ?
   WHERE execution_id = ?
```

---

## 鉴权流程详解

### JWT Token 验证

**关键前提**: Java 已有完善的鉴权系统，Python 不需要关心细节

**Java 内部逻辑**（Python 无需关心）:
```
1. 提取 Token: 从请求头 Authorization 中提取
2. 解析 Token: 使用密钥解析 JWT，提取 Payload
3. 验证签名: 确保 Token 未被篡改
4. 检查有效期: 确保未过期
5. 提取 teacherId: 从 Payload 中获取
6. 对比路径参数: 确保路径中的 {teacherId} 与 Token 中的一致
```

### 班级权限检查（仅当 classIds 非空时）

**场景 1: 成绩分析（有 classIds）**
```
请求: POST /apps
Body: { classIds: ["1A", "1B"] }

Java 内部逻辑:
1. 查询: SELECT class_id FROM teacher_class WHERE teacher_id = 'teacher-001'
2. 结果: ["1A", "2A", "3A"]
3. 检查: "1A" ✅, "1B" ❌（不在结果中）
4. 返回: 403 Forbidden "No access to class 1B"
```

**场景 2: 教案生成（无 classIds）**
```
请求: POST /apps
Body: {
  classIds: null,
  taskContext: { subject: "数学", grade: "初一", topic: "二次函数" }
}

Java 内部逻辑:
1. 检测 classIds == null
2. 跳过班级权限检查
3. 直接保存
```

---

## 实施检查清单

### Phase 1: 基础功能
- [ ] 创建 `ai_apps` 表
- [ ] 创建 `ai_blueprints` 表
- [ ] 创建 `ai_page_executions` 表
- [ ] 实现 POST /apps（创建 App + Blueprint v1 + 首次执行）
- [ ] 实现 GET /apps（查询 App 列表）
- [ ] 实现 GET /apps/{appId}/executions（查询执行历史）
- [ ] 实现 GET /executions/{executionId}（获取执行详情）
- [ ] 单元测试 + 集成测试

### Phase 2: 版本控制
- [ ] 实现 POST /apps/{appId}/blueprints（修改 Blueprint，生成新版本）
- [ ] 实现 POST /apps/{appId}/executions（重新执行，使用当前版本）
- [ ] 实现 GET /apps/{appId}/blueprints（查询版本历史）

### Phase 3: 高级功能
- [ ] 创建 `ai_app_shares` 表
- [ ] 实现分享功能
- [ ] 实现 PATCH /executions/{executionId}（Patch 更新）
- [ ] 实现 App 发布为 Studio

---

## 常见问题

### Q1: 如何防止 app_id 冲突？

**方案**:
- 使用 UUID: `app-{uuid}`（如 `app-550e8400-e29b-41d4-a716-446655440000`）
- 数据库唯一索引: `UNIQUE INDEX idx_app_id (app_id)`

### Q2: execution_count 怎么高效计算？

**问题**: 每次查询都 COUNT 性能差

**方案 1**: 冗余字段
```
ALTER TABLE ai_apps ADD COLUMN execution_count INT DEFAULT 0;
-- 每次插入执行记录时，UPDATE apps SET execution_count = execution_count + 1
```

**方案 2**: 缓存
```
Redis: app:{appId}:count -> 3
```

### Q3: 如果用户想回退到旧版本怎么办？

**方案**:
```
POST /apps/{appId}/blueprints/{blueprintId}/activate
Body: {}

Java 逻辑:
UPDATE ai_apps
SET current_blueprint_id = ?,
    current_version = (SELECT version FROM ai_blueprints WHERE blueprint_id = ?)
WHERE app_id = ?;
```

---

## 相关文档

- [整体流程设计](./overall-flow.md) - 端到端完整流程
- [前端集成规范](./frontend-spec.md) - 前端对接细节
- [数据库设计文档](./database-design.md) - MySQL 表结构详解
- [架构设计总结](./design-summary.md) - App 层级架构说明
