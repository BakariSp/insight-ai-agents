# 存储优化方案（App 架构）

> **⚠️ Phase 2+ 规划文档** — 不属于当前 Phase 1 范围。Phase 1 规格见 [docs/studio-v1/phase1/](../../../../docs/studio-v1/phase1/)
>
> **文档目的**: 基于实际测试数据，制定数据库 + OSS 混合存储策略
> **修订日期**: 2026-02-04

---

## 1. 数据大小实测分析

### 实际测试数据（来自 Phase 4-7 测试）

| 字段 | 示例大小 | 复杂场景预估 | 最大预估 | 来源 |
|------|----------|--------------|----------|------|
| **blueprint_content** | 3.3KB | 10-20KB | 50KB | sample-blueprint.json |
| **page_content** | 4.6KB | 50-200KB | 500KB | sample-page.json (含长 AI 文本) |
| **data_context** | - | 100-500KB | 2MB | 50 个学生的完整数据 |
| **compute_results** | - | 20-50KB | 100KB | 统计 + 图表数据 |

### 关键发现

1. ✅ **blueprint_content 不大**: 用户判断正确，即使复杂场景也只有 10-20KB
2. ⚠️ **page_content 可能较大**: AI 生成的 markdown 内容可能很长（如测试中的分析总结）
3. ⚠️ **data_context 会很大**: 50 个学生的作业数据可能达到 1-2MB
4. ✅ **compute_results 相对较小**: 通常 20-50KB

---

## 2. 存储策略（推荐方案）

### 方案对比

| 方案 | 优势 | 劣势 | 适用场景 |
|------|------|------|----------|
| **全 MySQL** | 查询方便、事务一致 | 大字段影响性能、成本高 | 原型阶段 |
| **全 OSS** | 成本低、无大小限制 | 查询复杂、事务难保证 | 归档场景 |
| **混合策略** | 平衡性能与成本 | 实现复杂度中等 | ✅ **推荐** |

### 推荐：混合存储策略

```
ai_apps (MySQL)
  └─ 全部字段存 MySQL（小且频繁查询）

ai_blueprints (MySQL + OSS)
  ├─ blueprint_content → MySQL（3-20KB，频繁读取）
  └─ (未来可选) 超大 Blueprint → OSS

ai_page_executions (MySQL + OSS)
  ├─ execution_id, app_id, blueprint_id, created_at → MySQL（索引字段）
  ├─ page_content_url → OSS（大字段，按需加载）
  ├─ data_context_url → OSS（Patch 更新时才需要）
  └─ compute_results_url → OSS（可选缓存）
```

---

## 3. 数据表设计（优化版）

### 3.1 ai_apps 表（无变化）

保持原设计，所有字段存 MySQL。

---

### 3.2 ai_blueprints 表（优化版）

#### 字段说明

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 数据库记录 ID | 67890 |
| `blueprint_id` | VARCHAR(100) | UNIQUE, NOT NULL | Blueprint 唯一 ID | "bp-uuid-7777" |
| `app_id` | VARCHAR(100) | NOT NULL, INDEX | 关联的 App ID | "app-uuid-1234" |
| `version` | INT | NOT NULL | 版本号（从 1 开始） | 1 |
| `blueprint_content` | JSON | NOT NULL | Blueprint 完整 JSON（3-20KB） | `{meta: {...}, layout: {...}}` |
| `blueprint_content_url` | VARCHAR(500) | NULL | ⭐ OSS URL（超大 Blueprint 时使用） | "https://oss.../bp-uuid-7777.json" |
| `change_summary` | VARCHAR(500) | NULL | 修改说明 | "调整了布局，增加了趋势图" |
| `created_by` | VARCHAR(50) | NOT NULL | 创建者 | "teacher-001" |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 | "2026-02-20 10:00:00" |

#### 存储逻辑

```
IF blueprint_content 大小 <= 50KB:
    存 MySQL (blueprint_content 字段)
ELSE:
    上传到 OSS
    存 URL (blueprint_content_url 字段)
    blueprint_content = NULL
```

**优势**: 99% 场景下直接从 MySQL 读取，只有极少数超大 Blueprint 才走 OSS。

---

### 3.3 ai_page_executions 表（重要优化）

#### 字段说明（新增 OSS URL 字段）

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 数据库记录 ID | 99999 |
| `execution_id` | VARCHAR(100) | UNIQUE, NOT NULL | 执行唯一 ID | "exec-uuid-9999" |
| `app_id` | VARCHAR(100) | NOT NULL, INDEX | 关联的 App ID | "app-uuid-1234" |
| `blueprint_id` | VARCHAR(100) | NOT NULL, INDEX | 使用的 Blueprint 版本 | "bp-uuid-7777" |
| `teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 执行者 ID | "teacher-001" |
| ⭐ `page_content_url` | VARCHAR(500) | NOT NULL | **Page JSON 的 OSS URL** | "https://oss.../exec-9999-page.json" |
| ⭐ `data_context_url` | VARCHAR(500) | NULL | **原始数据的 OSS URL（用于 Patch）** | "https://oss.../exec-9999-data.json" |
| ⭐ `compute_results_url` | VARCHAR(500) | NULL | **计算结果的 OSS URL（用于 Patch）** | "https://oss.../exec-9999-compute.json" |
| `page_thumbnail` | TEXT | NULL | Page 预览摘要（用于列表展示，< 1KB） | `{title: "...", summary: "..."}` |
| `class_ids` | JSON | NULL | 本次执行关联的班级 | `["1A"]` |
| `tags` | JSON | NULL | 本次执行的标签 | `["2月", "期中"]` |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP, INDEX | 执行时间 | "2026-02-04 10:30:00" |

#### 关键变更

1. **删除字段**: `page_content`, `data_context`, `compute_results`（改为 OSS URL）
2. **新增字段**: `page_content_url`, `data_context_url`, `compute_results_url`
3. **新增字段**: `page_thumbnail`（小摘要，用于列表展示，无需下载完整 Page）

#### 查询优化

**查询执行历史列表**（无需下载完整 Page）:
```sql
SELECT
  e.execution_id,
  e.created_at,
  e.page_thumbnail,  -- 轻量级预览
  e.class_ids,
  e.tags,
  b.version
FROM ai_page_executions e
JOIN ai_blueprints b ON e.blueprint_id = b.blueprint_id
WHERE e.app_id = 'app-uuid-1234'
ORDER BY e.created_at DESC;
```

**获取完整 Page**（按需下载）:
```sql
SELECT page_content_url FROM ai_page_executions WHERE execution_id = ?;
-- Java 后端从 OSS 下载完整 JSON
```

---

## 4. API 端点设计（优化版）

### 4.1 创建 App + Blueprint v1 + 首次执行

**端点**: `POST /api/studio/teacher/{teacherId}/apps`

**请求体**:
```json
{
  "appName": "1A班期中分析",
  "appType": "analysis",
  "blueprint": { ... },
  "pageContent": { ... },
  "conversationId": "conv-uuid-5678",
  "classIds": ["1A"],
  "dataContext": { ... },      // 可选
  "computeResults": { ... },   // 可选
  "tags": ["期中", "数学"]
}
```

**业务逻辑（新增 OSS 上传）**:

```
1. 鉴权验证 + 权限检查
2. 生成 app_id, blueprint_id, execution_id
3. 创建 App（存 MySQL）
4. 创建 Blueprint v1:
   - 存 blueprint_content 到 MySQL（3-20KB）
5. 创建首次执行记录:
   - 上传 pageContent 到 OSS → page_content_url
   - 上传 dataContext 到 OSS → data_context_url（可选）
   - 上传 computeResults 到 OSS → compute_results_url（可选）
   - 提取 page_thumbnail（title + 前 500 字符摘要）
   - 存 URL + thumbnail 到 MySQL
6. 返回结果
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "appId": "app-uuid-1234",
    "blueprintId": "bp-uuid-7777",
    "version": 1,
    "executionId": "exec-uuid-1111",
    "pageContentUrl": "https://oss.../exec-1111-page.json",
    "createdAt": "2026-01-10T09:00:00Z"
  }
}
```

---

### 4.2 查询执行历史（优化版）

**端点**: `GET /api/studio/teacher/{teacherId}/apps/{appId}/executions`

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
        "blueprintVersion": 2,
        "thumbnail": {
          "title": "1A班期中分析",
          "summary": "本次考试平均分 75.5，最高分 98..."
        },
        "pageContentUrl": "https://oss.../exec-3333-page.json",
        "classIds": ["1A"],
        "tags": ["3月"],
        "createdAt": "2026-03-01T10:00:00Z"
      }
    ]
  }
}
```

**前端流程**:
1. 列表展示使用 `thumbnail`（无需下载完整 Page）
2. 用户点击"查看" → 从 `pageContentUrl` 下载完整 Page JSON
3. 渲染页面

---

### 4.3 获取某次执行的详情（新增）

**端点**: `GET /api/studio/teacher/{teacherId}/executions/{executionId}`

**查询参数**:
```
?includeData=true    // 是否返回 data_context_url（用于 Patch）
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
    "pageContentUrl": "https://oss.../exec-9999-page.json",
    "dataContextUrl": "https://oss.../exec-9999-data.json",     // 仅当 includeData=true
    "computeResultsUrl": "https://oss.../exec-9999-compute.json",
    "metadata": {
      "classIds": ["1A"],
      "tags": ["2月"],
      "createdAt": "2026-02-04T10:30:00Z"
    }
  }
}
```

**前端使用场景**:
- **查看 Page**: 只下载 `pageContentUrl`
- **Patch 更新**: 下载 `dataContextUrl` + `computeResultsUrl`，修改后重新上传

---

### 4.4 Patch 更新某次执行（优化版）

**端点**: `PATCH /api/studio/teacher/{teacherId}/executions/{executionId}`

**请求体**:
```json
{
  "pageContent": { ... },       // 更新后的 Page JSON
  "computeResults": { ... }     // 更新后的计算结果
}
```

**业务逻辑**:
```
1. 验证权限
2. 上传新的 pageContent 到 OSS → 新 URL
3. 上传新的 computeResults 到 OSS → 新 URL（可选）
4. 更新 MySQL:
   UPDATE ai_page_executions
   SET page_content_url = ?, compute_results_url = ?
   WHERE execution_id = ?
5. （可选）保留旧文件用于版本回滚
```

---

## 5. OSS 存储规范

### 5.1 目录结构

```
insight-ai-executions/
├── blueprints/
│   ├── bp-uuid-7777.json          # 超大 Blueprint（罕见）
│   └── bp-uuid-8888.json
├── executions/
│   ├── exec-uuid-1111/
│   │   ├── page.json              # Page 完整 JSON
│   │   ├── data.json              # 原始数据（用于 Patch）
│   │   └── compute.json           # 计算结果（用于 Patch）
│   └── exec-uuid-2222/
│       ├── page.json
│       ├── data.json
│       └── compute.json
└── archives/                       # 归档（可选）
    └── 2026-01/
        └── exec-uuid-0001/
```

### 5.2 URL 格式

```
Blueprint: https://oss.insightai.hk/blueprints/{blueprint_id}.json
Page:      https://oss.insightai.hk/executions/{execution_id}/page.json
Data:      https://oss.insightai.hk/executions/{execution_id}/data.json
Compute:   https://oss.insightai.hk/executions/{execution_id}/compute.json
```

### 5.3 访问控制

| 资源 | 访问权限 | 说明 |
|------|----------|------|
| Blueprint | Private | 只有 teacher 可访问 |
| Page | Private | 只有 teacher 可访问（分享功能待设计） |
| Data/Compute | Private | 只有 teacher 可访问（用于 Patch） |

**鉴权方式**:
- Java 后端使用 OSS SDK 签名 URL（临时访问，有效期 1 小时）
- 前端从 Java 获取签名 URL 后直接访问 OSS

---

## 6. 性能与成本优化

### 6.1 成本对比

| 存储方式 | 单次执行成本（假设） | 1000 次执行/月 |
|----------|---------------------|----------------|
| **全 MySQL** (500KB/执行) | ¥0.005 | ¥5.0 |
| **MySQL + OSS** (50KB MySQL + 450KB OSS) | ¥0.0005 + ¥0.0002 = ¥0.0007 | ¥0.7 |
| **节省** | 86% | ¥4.3 |

### 6.2 性能优化

1. **列表查询快**: 只查 MySQL（execution_id + thumbnail），无需下载完整 Page
2. **按需加载**: 只有用户点击"查看"时才下载完整 Page
3. **CDN 加速**: OSS 配置 CDN，全球加速（如果需要）
4. **缓存策略**: 前端缓存已下载的 Page（减少重复下载）

### 6.3 归档策略

**自动归档**（降低成本）:
```
1. 执行超过 3 个月且未访问 → 迁移到 OSS 归档存储（成本降低 80%）
2. 执行超过 1 年 → 压缩 + 归档
3. 执行超过 3 年 → 用户确认后删除
```

---

## 7. 实施路径

### Phase 1: 基础功能（P0）
- [ ] 实现 OSS 上传/下载工具类
- [ ] 修改 `ai_page_executions` 表结构（新增 URL 字段）
- [ ] 修改 POST /apps 接口（上传到 OSS）
- [ ] 修改 GET /executions 接口（返回 URL + thumbnail）

### Phase 2: 优化功能（P1）
- [ ] 实现签名 URL 生成（前端直接访问 OSS）
- [ ] 实现 Patch 接口（更新 OSS 文件）
- [ ] 实现 page_thumbnail 提取（列表展示优化）

### Phase 3: 高级功能（P2）
- [ ] 自动归档策略（3 个月后迁移到冷存储）
- [ ] CDN 加速配置
- [ ] 分享功能（生成公开访问的签名 URL）

---

## 8. 常见问题

### Q1: 为什么 Blueprint 不存 OSS？

**答**: Blueprint 通常只有 3-20KB，且每次执行都需要读取，存 MySQL 性能更好。只有极少数超大 Blueprint 才考虑 OSS。

### Q2: OSS URL 失效怎么办？

**答**: 使用签名 URL（临时访问，有效期 1 小时）。Java 后端在前端请求时动态生成签名 URL。

### Q3: 删除 Execution 时如何清理 OSS？

**答**:
```
1. 软删除: 只标记 is_deleted，不删除 OSS 文件（便于恢复）
2. 定期清理: 每月清理 is_deleted=true 且超过 30 天的文件
3. 硬删除: 同步删除 MySQL 记录和 OSS 文件
```

### Q4: 如何防止 OSS 文件被恶意访问？

**答**:
- 所有 OSS Bucket 设置为 Private
- 使用签名 URL（短期有效）
- Java 后端鉴权后才生成签名 URL
- 记录访问日志，监控异常访问

---

## 9. 总结

### 核心优势

1. **成本节省**: OSS 存储成本比 MySQL 低 80%+
2. **性能提升**: 列表查询只访问 MySQL（轻量级）
3. **扩展性**: 支持任意大小的 Page/Data（无限制）
4. **灵活性**: 可按需加载，减少带宽浪费

### 实施建议

**优先级**: P0（基础功能）> P1（优化）> P2（高级）

**快速验证**:
1. 先实现 Phase 1（OSS 上传/下载 + 表结构调整）
2. 用 Phase 4-7 的测试数据验证
3. 对比 MySQL vs OSS 的性能差异
4. 再决定是否全量迁移

---

## 10. 相关文档

- [Java 后端集成规范](./java-backend-spec.md) - API 端点设计
- [App 架构快速参考](./app-architecture-quickref.md) - 核心概念
- [架构设计总结](./design-summary.md) - 设计决策
