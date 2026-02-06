# API 分离设计 + 权限管理方案

> **⚠️ Phase 2+ 规划文档** — 不属于当前 Phase 1 范围。Phase 1 规格见 [docs/studio-v1/phase1/](../../../../docs/studio-v1/phase1/)
>
> **文档目的**: 设计版本创建与执行分离的 API + 完整的权限与分享机制
> **优先级**: P0（版本分离）+ P1（权限管理）
> **修订日期**: 2026-02-04

---

## 1. 问题背景

### 1.1 当前设计问题

**原设计**: 创建新版本时自动执行

```
POST /apps/{appId}/blueprints
Body: {
  "blueprint": {...},
  "pageContent": {...},    // 必须提供首次执行结果
  "changeSummary": "..."
}

结果:
  1. 创建 Blueprint v2
  2. 更新 App 的 current_blueprint_id
  3. 自动创建 Execution 1（使用 v2）
```

**问题**:
1. 用户可能只想"保存设计"，不想立即执行
2. 执行需要真实数据，但设计阶段可能没有
3. 耦合太紧，不灵活

---

### 1.2 用户场景

#### 场景 1: 设计时不执行

```
用户: 我想先保存这个 Blueprint，明天再用真实数据测试

期望流程:
  1. POST /blueprints → 创建 Blueprint v2
  2. (用户明天来)
  3. POST /executions → 使用 v2 执行
```

#### 场景 2: 设计后立即执行

```
用户: 我修改了 Blueprint，立即用新数据测试

期望流程:
  1. POST /blueprints → 创建 Blueprint v2
  2. POST /executions → 立即使用 v2 执行
```

#### 场景 3: 回滚版本后执行

```
用户: v3 有问题，我想回退到 v2 再执行

期望流程:
  1. POST /blueprints/{v2}/activate → 激活 v2
  2. POST /executions → 使用 v2 执行
```

---

## 2. API 分离设计（P0）

### 2.1 创建 Blueprint 版本（不执行）

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/blueprints`

**请求体**:
```json
{
  "blueprint": {
    "meta": {...},
    "dataContract": {...},
    "computeGraph": {...},
    "uiComposition": {...}
  },
  "changeSummary": "调整了布局，增加了趋势图",
  "activateImmediately": true  // 可选：是否立即激活为当前版本（默认 true）
}
```

**业务逻辑**:
```
1. 鉴权验证
2. 查询当前最大版本号: MAX(version) FROM ai_blueprints WHERE app_id = ?
3. 新版本号 = MAX(version) + 1
4. 生成新 blueprint_id
5. 存储 Blueprint:
   - 如果 blueprint_content <= 50KB → 存 MySQL
   - 否则 → 上传到 OSS，存 URL
6. IF activateImmediately == true:
     UPDATE ai_apps SET current_blueprint_id = ?, current_version = ?
   ELSE:
     不更新 App（保持当前版本）
7. 返回结果
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "appId": "app-uuid-1234",
    "blueprintId": "bp-uuid-8888",
    "version": 2,
    "isActive": true,
    "createdAt": "2026-02-20T10:00:00Z"
  }
}
```

**关键点**:
- ✅ **不创建 Execution**: 只保存设计，不执行
- ✅ **可选激活**: `activateImmediately=false` 时保持旧版本，用户可以稍后激活

---

### 2.2 激活某个 Blueprint 版本

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/blueprints/{blueprintId}/activate`

**请求体**: 无（空 Body）

**业务逻辑**:
```
1. 鉴权验证
2. 查询 Blueprint: WHERE blueprint_id = ? AND app_id = ?
3. 如果不存在 → 返回 404
4. 更新 App:
   UPDATE ai_apps
   SET current_blueprint_id = ?,
       current_version = (SELECT version FROM ai_blueprints WHERE blueprint_id = ?),
       updated_at = CURRENT_TIMESTAMP
   WHERE app_id = ?
5. 返回结果
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "appId": "app-uuid-1234",
    "blueprintId": "bp-uuid-8888",
    "version": 2,
    "activatedAt": "2026-02-20T10:00:00Z"
  }
}
```

**用途**: 回滚版本、A/B 测试

---

### 2.3 执行 Blueprint（使用当前版本）

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/executions`

**请求体**:
```json
{
  "pageContent": {...},         // 执行结果的 Page JSON
  "dataContext": {...},         // 可选：原始数据（用于 Patch）
  "computeResults": {...},      // 可选：计算结果（用于 Patch）
  "classIds": ["1A"],           // 可选：本次执行关联的班级
  "tags": ["3月"]               // 可选：标签
}
```

**业务逻辑**:
```
1. 鉴权验证
2. 查询 App: WHERE app_id = ?
3. 获取当前 Blueprint: current_blueprint_id
4. 生成 execution_id
5. 上传数据到 OSS:
   - pageContent → page_content_url
   - dataContext → data_context_url（可选）
   - computeResults → compute_results_url（可选）
6. 提取 page_thumbnail（title + 前 500 字符）
7. 存储 Execution:
   INSERT INTO ai_page_executions (
     execution_id, app_id, blueprint_id, teacher_id,
     page_content_url, data_context_url, compute_results_url,
     page_thumbnail, class_ids, tags
   )
8. 返回结果
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "executionId": "exec-uuid-3333",
    "appId": "app-uuid-1234",
    "blueprintId": "bp-uuid-8888",
    "version": 2,
    "pageContentUrl": "https://oss.../exec-3333-page.json",
    "createdAt": "2026-03-01T10:00:00Z"
  }
}
```

**关键点**:
- ✅ **解耦**: 创建版本和执行完全分离
- ✅ **使用当前版本**: 总是使用 `current_blueprint_id`
- ✅ **灵活性**: 用户可以先创建多个版本，再选择一个执行

---

### 2.4 使用指定版本执行（可选，P1）

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/blueprints/{blueprintId}/executions`

**用途**: 用旧版本执行（不激活该版本）

**请求体**: 同 2.3

**业务逻辑**:
```
1. 鉴权验证
2. 查询 Blueprint: WHERE blueprint_id = ? AND app_id = ?
3. 如果不存在 → 返回 404
4. 生成 execution_id
5. 上传数据到 OSS
6. 存储 Execution（使用指定的 blueprint_id）
7. 返回结果
```

**用途**: A/B 测试（比较不同版本的效果）

---

## 3. 权限管理方案（P1，重要）

### 3.1 权限模型

#### 核心概念

```
Teacher (用户)
  ├─ 拥有 Apps (owner_id = teacher_id)
  ├─ 可以访问 Classes (teacher_class 表)
  └─ 可以分享给其他 Teachers (ai_app_shares 表)
```

#### 权限类型

| 权限 | 说明 | 可执行操作 |
|------|------|------------|
| **owner** | 拥有者 | 全部操作（创建、编辑、删除、执行、分享） |
| **edit** | 编辑权限 | 查看、编辑 Blueprint、执行、创建新版本 |
| **execute** | 执行权限 | 查看、执行（不能编辑 Blueprint） |
| **view** | 只读权限 | 只能查看 App 和执行历史 |

---

### 3.2 数据表设计

#### ai_app_shares 表（分享）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 分享记录 ID |
| `share_id` | VARCHAR(100) | UNIQUE, NOT NULL | 分享唯一 ID |
| `resource_type` | VARCHAR(20) | NOT NULL | 'app' 或 'execution' |
| `resource_id` | VARCHAR(100) | NOT NULL, INDEX | app_id 或 execution_id |
| `shared_by_teacher_id` | VARCHAR(50) | NOT NULL | 分享者 ID |
| `shared_to_teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 接收者 ID（NULL = 公开分享） |
| `permission` | VARCHAR(20) | NOT NULL | 'view', 'execute', 'edit' |
| `expires_at` | TIMESTAMP | NULL | 过期时间（NULL = 永久） |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 分享时间 |

#### 索引设计

| 索引名 | 字段 | 类型 | 目的 |
|--------|------|------|------|
| `idx_resource` | `resource_type`, `resource_id` | COMPOSITE INDEX | 查询某资源的所有分享 |
| `idx_shared_to` | `shared_to_teacher_id` | INDEX | 查询"分享给我的" |

---

### 3.3 鉴权流程

#### 通用鉴权逻辑（所有 API 端点）

```java
// 伪代码
public boolean checkPermission(String teacherId, String appId, String requiredPermission) {
    // 1. 检查是否是拥有者
    App app = appRepository.findByAppId(appId);
    if (app.getTeacherId().equals(teacherId)) {
        return true;  // 拥有者有全部权限
    }

    // 2. 检查分享权限
    AppShare share = shareRepository.findByResourceIdAndSharedTo(appId, teacherId);
    if (share == null) {
        return false;  // 无权限
    }

    // 3. 检查过期时间
    if (share.getExpiresAt() != null && share.getExpiresAt().isBefore(Instant.now())) {
        return false;  // 已过期
    }

    // 4. 检查权限级别
    return hasRequiredPermission(share.getPermission(), requiredPermission);
}

private boolean hasRequiredPermission(String grantedPermission, String requiredPermission) {
    // 权限层级: owner > edit > execute > view
    Map<String, Integer> permissionLevel = Map.of(
        "view", 1,
        "execute", 2,
        "edit", 3,
        "owner", 4
    );
    return permissionLevel.get(grantedPermission) >= permissionLevel.get(requiredPermission);
}
```

#### 各端点所需权限

| 端点 | 所需权限 | 说明 |
|------|----------|------|
| `GET /apps` | owner | 查询我的 Apps |
| `GET /apps/{appId}` | view | 查看 App 详情 |
| `GET /apps/{appId}/executions` | view | 查看执行历史 |
| `GET /executions/{executionId}` | view | 查看某次执行 |
| `POST /apps/{appId}/blueprints` | edit | 创建新版本 |
| `POST /apps/{appId}/executions` | execute | 执行 Blueprint |
| `PATCH /executions/{executionId}` | execute | Patch 更新 |
| `DELETE /apps/{appId}` | owner | 删除 App |
| `POST /apps/{appId}/share` | owner | 分享 App |

---

### 3.4 分享 API 设计

#### 分享 App

**端点**: `POST /api/studio/teacher/{teacherId}/apps/{appId}/shares`

**请求体**:
```json
{
  "sharedToTeacherId": "teacher-002",  // NULL = 公开分享
  "permission": "view",                 // view, execute, edit
  "expiresInDays": 30                   // NULL = 永久
}
```

**业务逻辑**:
```
1. 鉴权: 检查是否是 owner
2. 生成 share_id
3. 计算过期时间:
   IF expiresInDays != NULL:
     expires_at = NOW() + expiresInDays * 24小时
   ELSE:
     expires_at = NULL
4. 插入记录:
   INSERT INTO ai_app_shares (
     share_id, resource_type, resource_id,
     shared_by_teacher_id, shared_to_teacher_id,
     permission, expires_at
   )
5. 返回分享链接
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "shareId": "share-uuid-9999",
    "shareUrl": "https://insightai.hk/share/share-uuid-9999",
    "permission": "view",
    "expiresAt": "2026-03-06T10:00:00Z"
  }
}
```

---

#### 查询"分享给我的" Apps

**端点**: `GET /api/studio/teacher/{teacherId}/shared-apps`

**查询逻辑**:
```sql
SELECT
  a.app_id,
  a.app_name,
  a.app_type,
  s.permission,
  s.shared_by_teacher_id,
  s.expires_at,
  s.created_at AS shared_at
FROM ai_app_shares s
JOIN ai_apps a ON s.resource_id = a.app_id
WHERE s.shared_to_teacher_id = 'teacher-001'
  AND s.resource_type = 'app'
  AND (s.expires_at IS NULL OR s.expires_at > NOW())
ORDER BY s.created_at DESC;
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
        "permission": "view",
        "sharedBy": {
          "teacherId": "teacher-003",
          "teacherName": "张老师"
        },
        "expiresAt": "2026-03-06T10:00:00Z",
        "sharedAt": "2026-02-04T10:00:00Z"
      }
    ]
  }
}
```

---

#### 撤销分享

**端点**: `DELETE /api/studio/teacher/{teacherId}/apps/{appId}/shares/{shareId}`

**业务逻辑**:
```
1. 鉴权: 检查是否是 owner
2. 删除记录:
   DELETE FROM ai_app_shares WHERE share_id = ?
3. 返回结果
```

---

### 3.5 班级权限检查（已有）

**触发时机**: 当 API 请求体或查询参数包含 `classIds` 时

**检查逻辑**:
```java
public void validateClassAccess(String teacherId, List<String> classIds) {
    if (classIds == null || classIds.isEmpty()) {
        return;  // 无需检查（如教案生成）
    }

    // 查询教师可访问的班级
    List<String> accessibleClasses = teacherClassRepository.findClassIdsByTeacherId(teacherId);

    // 检查每个 classId 是否在可访问列表中
    for (String classId : classIds) {
        if (!accessibleClasses.contains(classId)) {
            throw new ForbiddenException("No access to class " + classId);
        }
    }
}
```

**集成到 API**:
```
POST /apps → validateClassAccess(teacherId, body.classIds)
POST /executions → validateClassAccess(teacherId, body.classIds)
```

---

## 4. 完整 API 流程示例

### 4.1 场景: 创建 App → 修改设计 → 执行

```
1. 创建 App + Blueprint v1（不执行）
   POST /apps
   Body: {
     "appName": "1A班期中分析",
     "blueprint": {...},
     "skipInitialExecution": true  // 不创建首次执行
   }
   Response: { appId, blueprintId, version: 1 }

2. 修改 Blueprint（创建 v2，不激活）
   POST /apps/{appId}/blueprints
   Body: {
     "blueprint": {...},
     "changeSummary": "增加了趋势图",
     "activateImmediately": false  // 不激活
   }
   Response: { blueprintId, version: 2, isActive: false }

3. 激活 v2
   POST /apps/{appId}/blueprints/{v2}/activate
   Response: { version: 2, activatedAt: "..." }

4. 执行 v2
   POST /apps/{appId}/executions
   Body: { pageContent: {...}, classIds: ["1A"] }
   Response: { executionId, blueprintId: v2 }
```

---

### 4.2 场景: 分享 App 给其他老师

```
1. 老师 A 创建 App
   POST /apps
   Response: { appId: "app-uuid-1234" }

2. 老师 A 分享给老师 B（只读权限）
   POST /apps/app-uuid-1234/shares
   Body: {
     "sharedToTeacherId": "teacher-B",
     "permission": "view",
     "expiresInDays": 7
   }
   Response: { shareId, shareUrl }

3. 老师 B 查看"分享给我的" Apps
   GET /teacher/teacher-B/shared-apps
   Response: { items: [{ appId: "app-uuid-1234", permission: "view" }] }

4. 老师 B 查看 App 详情（成功）
   GET /apps/app-uuid-1234
   Response: { appName: "1A班期中分析", ... }

5. 老师 B 尝试修改 Blueprint（失败）
   POST /apps/app-uuid-1234/blueprints
   Response: 403 Forbidden (只有 view 权限)

6. 老师 A 撤销分享
   DELETE /apps/app-uuid-1234/shares/{shareId}
   Response: 200 OK

7. 老师 B 再次查看（失败）
   GET /apps/app-uuid-1234
   Response: 403 Forbidden (分享已撤销)
```

---

## 5. 实施检查清单

### Phase 1: API 分离（P0）
- [ ] 修改 POST /apps（支持 `skipInitialExecution` 参数）
- [ ] 修改 POST /blueprints（去掉 `pageContent` 必填，支持 `activateImmediately`）
- [ ] 新增 POST /blueprints/{blueprintId}/activate
- [ ] 修改 POST /executions（独立接口）
- [ ] 单元测试 + 集成测试

### Phase 2: 权限管理（P1）
- [ ] 创建 `ai_app_shares` 表
- [ ] 实现通用鉴权逻辑（`checkPermission`）
- [ ] 集成到所有 API 端点
- [ ] 实现分享 API（创建、查询、撤销）
- [ ] 单元测试 + 集成测试

### Phase 3: 高级功能（P2）
- [ ] 公开分享链接（shared_to_teacher_id = NULL）
- [ ] 分享权限升级/降级
- [ ] 分享日志（audit log）
- [ ] 批量分享（如分享给整个学科组）

---

## 6. 常见问题

### Q1: 如果创建版本时不执行，`current_version` 会不会不准确？

**答**: 不会。只要设置 `activateImmediately=true`（默认），`current_version` 就会更新。如果设置 `false`，用户需要手动激活。

---

### Q2: 如何防止用户创建大量未使用的版本？

**建议**:
1. 限制每个 App 最多保留 20 个版本
2. 超过后自动删除"未执行过的版本"
3. 提示用户"该版本从未执行，确定要保留吗？"

---

### Q3: 分享权限会不会泄露班级数据？

**答**: 不会。分享只控制 App/Blueprint 访问权限，班级数据访问仍然由 `teacher_class` 表控制。

**示例**:
```
老师 A 有 1A 班的访问权限，分享 App 给老师 B（execute 权限）
老师 B 尝试执行：
  POST /apps/{appId}/executions
  Body: { classIds: ["1A"] }

结果: 403 Forbidden（老师 B 没有 1A 班的访问权限）
```

---

### Q4: 如何支持"复制别人的 App"？

**方案**: 添加"Fork" 功能

```
POST /apps/{appId}/fork
Body: { newAppName: "我的副本" }

业务逻辑:
  1. 检查权限（至少 view）
  2. 复制 Blueprint（当前版本）
  3. 创建新 App（owner = 当前用户）
  4. 不复制执行记录（独立的 App）
```

---

## 7. 总结

### 核心改进

1. **解耦设计与执行**: 用户可以先保存设计，稍后执行
2. **权限分层**: owner > edit > execute > view
3. **分享机制**: 支持有限期分享、权限控制、撤销
4. **班级隔离**: 分享不会泄露班级数据

### 实施优先级

**P0**: API 分离（版本创建 ≠ 执行）
**P1**: 权限管理（鉴权 + 分享）
**P2**: 高级功能（公开分享、Fork）

---

## 8. 相关文档

- [存储优化方案](./storage-optimization-plan.md) - OSS 存储策略
- [Java 后端集成规范](./java-backend-spec.md) - API 端点设计
- [App 架构快速参考](./app-architecture-quickref.md) - 核心概念
