# 系统架构全览（前端-AI-MCP-Java-OSS）

> **文档目的**: 全面梳理前端、AI-MCP、Java 后端、OSS 的职责边界与数据流
> **涵盖场景**: App 生成、RAG 素材、教案知识库、题库、批改等
> **修订日期**: 2026-02-04

---

## 1. 整体架构图

### 1.1 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端层（React）                        │
│  - 用户交互（对话、上传、查看）                                 │
│  - JWT 管理（从登录获取，所有请求携带）                         │
│  - 路由分发（根据功能调用不同服务）                             │
└─────────────────────────────────────────────────────────────┘
                            │ JWT
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    AI-MCP 层（Python FastAPI）                 │
│  - 无状态计算服务（透传 JWT，不持久化用户数据）                  │
│  - PlannerAgent（自然语言 → Blueprint）                        │
│  - ExecutorAgent（Blueprint → Page）                          │
│  - RAG 引擎（向量检索 + 知识库查询）                            │
│  - 工具调用（数据获取、统计计算）                               │
└─────────────────────────────────────────────────────────────┘
                            │ JWT
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Java 后端层（Spring Boot）                  │
│  - 鉴权中心（JWT 验证 + teacherId 解析）                        │
│  - 数据持久化（MySQL：元数据、关系、权限）                       │
│  - OSS 管理（上传、下载、签名 URL 生成）                         │
│  - 业务逻辑（权限检查、版本管理、分享）                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    存储层（MySQL + OSS + 向量库）               │
│  - MySQL: 元数据、关系、权限                                   │
│  - OSS: 大文件（图片、文档、Page JSON）                         │
│  - 向量库: RAG 知识库（Milvus/Qdrant）                         │
└─────────────────────────────────────────────────────────────┘
```

---

### 1.2 职责边界

#### 前端职责

| 职责 | 说明 | 示例 |
|------|------|------|
| **用户交互** | 对话输入、文件上传、结果展示 | 输入 prompt、选择班级、上传教案 |
| **JWT 管理** | 从登录获取 JWT，所有请求携带 | Authorization: Bearer <JWT> |
| **路由分发** | 根据功能调用不同服务 | App 生成 → AI-MCP；查询历史 → Java |
| **文件直传 OSS** | 大文件直接上传到 Java（Java 管理 OSS） | 上传图片 → Java 后端 |

#### AI-MCP 职责

| 职责 | 说明 | 示例 |
|------|------|------|
| **自然语言处理** | Prompt → Blueprint/Page | "分析 1A 班成绩" → Blueprint JSON |
| **RAG 检索** | 从知识库检索相关素材 | 检索教案模板、题目示例 |
| **工具调用** | 获取数据、统计计算 | get_class_students、calculate_statistics |
| **透传 JWT** | 调用 Java API 时携带 JWT | java_client.create_app(jwt_token=...) |
| **不持久化** | 不存储任何用户数据 | 只返回生成结果给 Java |

#### Java 后端职责

| 职责 | 说明 | 示例 |
|------|------|------|
| **鉴权** | JWT 验证 + teacherId 解析 | jwtService.extractTeacherId(jwt) |
| **权限管理** | 检查资源访问权限 | checkPermission(teacherId, appId, "edit") |
| **数据持久化** | 存储到 MySQL | INSERT INTO ai_apps, ai_blueprints |
| **OSS 管理** | 上传、下载、签名 URL | ossService.upload(...), generateSignedUrl(...) |
| **业务逻辑** | 版本管理、分享、归档 | 创建 Blueprint v2、分享 App |

#### 存储层职责

| 存储 | 用途 | 数据类型 | 生命周期 |
|------|------|----------|----------|
| **MySQL** | 元数据、关系、权限 | App、Blueprint、Execution、分享记录 | 永久 |
| **OSS** | 大文件 | 图片、PDF、Page JSON、dataContext | 永久（可归档） |
| **向量库** | RAG 知识库 | 教案、题目、教学资源的向量表示 | 永久 |

---

## 2. 核心场景与数据流

### 2.1 场景分类

| 场景 | 用户操作 | 涉及模块 | 数据归属 | 权限模型 |
|------|----------|----------|----------|----------|
| **App 生成** | "分析 1A 班成绩" | 前端 → AI-MCP → Java | teacherId | owner/分享 |
| **RAG 素材管理** | 上传教学资料 | 前端 → Java | teacherId | 私有/分享 |
| **教案知识库** | 系统预置教案 | 管理员 → Java | 系统级 | 全员可见 |
| **题库管理** | 上传题目素材 | 前端 → Java | teacherId | 私有/分享 |
| **作业批改** | 上传学生答卷 | 前端 → Java → AI-MCP | 学生/teacherId | 班级权限 |
| **历史查询** | 查看执行历史 | 前端 → Java | teacherId | owner/分享 |

---

### 2.2 场景 1: App 生成（已有设计）

**数据流**:
```
前端 → AI-MCP → Java → MySQL/OSS
```

**详见**: [ai-mcp-java-integration.md](./ai-mcp-java-integration.md)

---

### 2.3 场景 2: RAG 素材管理 ⭐ 新设计

#### 用户故事

```
用户: 我想上传我的教学 PPT，以后生成教案时可以参考
系统: 前端 → Java 后端上传 PPT → 提取内容 → 向量化 → 存入知识库
AI 生成时: PlannerAgent → RAG 检索 → 获取相关 PPT 内容 → 生成 Blueprint
```

#### 数据流

```
步骤 1: 上传素材
  前端
    ↓ POST /api/rag/materials/upload
  Java 后端
    ↓ 1. 验证 JWT（teacherId）
    ↓ 2. 上传到 OSS
    ↓ 3. 提取内容（文本、图片）
    ↓ 4. 调用 AI-MCP 向量化
  AI-MCP（RAG 引擎）
    ↓ 5. 生成向量 Embedding
    ↓ 6. 存入向量库（Milvus/Qdrant）
  Java 后端
    ↓ 7. 存储元数据到 MySQL
    ↓ 8. 返回 material_id

步骤 2: AI 生成时检索
  AI-MCP（PlannerAgent）
    ↓ 1. 根据 prompt 生成查询向量
    ↓ 2. 向量检索（相似度 Top-K）
  RAG 引擎
    ↓ 3. 从向量库获取相关素材
    ↓ 4. 调用 Java 获取完整内容
  Java 后端
    ↓ 5. 检查权限（只返回用户自己的 + 公开的）
    ↓ 6. 返回素材内容
  AI-MCP（PlannerAgent）
    ↓ 7. 结合素材生成 Blueprint
```

#### 数据表设计

**rag_materials 表**

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY | 记录 ID | 12345 |
| `material_id` | VARCHAR(100) | UNIQUE, NOT NULL | 素材唯一 ID | "material-uuid-9999" |
| `teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 上传者 ID | "teacher-001" |
| `material_type` | VARCHAR(50) | NOT NULL | 类型 | "lesson_plan", "teaching_ppt", "reference_doc" |
| `file_id` | VARCHAR(100) | NOT NULL | 关联的文件 ID（ai_files 表） | "file-uuid-8888" |
| `title` | VARCHAR(500) | NOT NULL | 标题 | "二次函数教案" |
| `description` | TEXT | NULL | 描述 | "适用于初二数学..." |
| `content_preview` | TEXT | NULL | 内容预览（前 1000 字） | "本节课主要讲解..." |
| `vector_id` | VARCHAR(100) | NULL | 向量库中的 ID | "vec-uuid-7777" |
| `tags` | JSON | NULL | 标签 | ["数学", "初二", "函数"] |
| `is_public` | BOOLEAN | DEFAULT FALSE | 是否公开分享 | FALSE |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 上传时间 | "2026-02-04 10:00:00" |

#### API 设计

**上传 RAG 素材**

```http
POST /api/rag/materials/upload
Headers:
  Authorization: Bearer <JWT>
Content-Type: multipart/form-data

Body:
  file: <file>
  materialType: "lesson_plan"
  title: "二次函数教案"
  description: "适用于初二数学..."
  tags: ["数学", "初二"]
  isPublic: false
```

**返回**:
```json
{
  "code": 200,
  "data": {
    "materialId": "material-uuid-9999",
    "fileId": "file-uuid-8888",
    "title": "二次函数教案",
    "vectorId": "vec-uuid-7777",
    "createdAt": "2026-02-04T10:00:00Z"
  }
}
```

**查询我的素材**

```http
GET /api/rag/materials
Headers:
  Authorization: Bearer <JWT>

Query:
  ?type=lesson_plan&page=1&pageSize=20
```

**AI-MCP 检索素材**

```python
# AI-MCP 内部调用
async def search_materials(query: str, jwt_token: str, top_k: int = 5):
    # 1. 生成查询向量
    query_vector = await embedding_service.embed(query)

    # 2. 向量检索
    results = await vector_db.search(
        collection="rag_materials",
        vector=query_vector,
        top_k=top_k
    )

    # 3. 从 Java 后端获取完整内容（带权限检查）
    materials = []
    for result in results:
        material = await java_client.get_material(
            jwt_token=jwt_token,
            material_id=result.material_id
        )
        materials.append(material)

    return materials
```

---

### 2.4 场景 3: 教案知识库 ⭐ 系统级资源

#### 用户故事

```
管理员: 预置 100 个优质教案模板
教师: 生成教案时，AI 自动参考系统知识库
```

#### 数据流

```
管理员端:
  管理后台
    ↓ POST /api/admin/knowledge-base/lessons/upload
  Java 后端
    ↓ 1. 验证管理员权限
    ↓ 2. 上传到 OSS
    ↓ 3. 调用 AI-MCP 向量化
    ↓ 4. 存入系统级知识库
    ↓ 5. 标记为 is_system=true

教师端:
  AI-MCP（PlannerAgent）
    ↓ 1. 检索教案（系统级 + 用户私有）
    ↓ 2. 优先返回系统级（高质量）
    ↓ 3. 结合用户私有素材
```

#### 数据表设计

**knowledge_base_lessons 表**（系统级）

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY | 记录 ID | 12345 |
| `lesson_id` | VARCHAR(100) | UNIQUE, NOT NULL | 教案唯一 ID | "lesson-uuid-9999" |
| `subject` | VARCHAR(50) | NOT NULL | 学科 | "数学", "语文" |
| `grade` | VARCHAR(50) | NOT NULL | 年级 | "初一", "高二" |
| `topic` | VARCHAR(200) | NOT NULL | 主题 | "二次函数" |
| `content` | TEXT | NOT NULL | 教案内容 | "教学目标：..." |
| `file_id` | VARCHAR(100) | NULL | 关联文件（如 PPT） | "file-uuid-8888" |
| `vector_id` | VARCHAR(100) | NOT NULL | 向量 ID | "vec-uuid-7777" |
| `tags` | JSON | NULL | 标签 | ["数学", "初二"] |
| `quality_score` | INT | DEFAULT 0 | 质量评分（0-100） | 95 |
| `is_system` | BOOLEAN | DEFAULT TRUE | 系统级（全员可见） | TRUE |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 | "2026-01-01 10:00:00" |

#### 检索策略

**优先级**:
1. 系统级高质量教案（quality_score > 80）
2. 用户私有素材
3. 系统级其他教案

```python
async def search_lessons(query: str, jwt_token: str):
    # 1. 向量检索（系统级 + 用户私有）
    results = await vector_db.search(
        collection="lessons",
        vector=await embedding_service.embed(query),
        top_k=10
    )

    # 2. 按优先级排序
    sorted_results = sorted(results, key=lambda x: (
        x.is_system and x.quality_score > 80,  # 系统级高质量优先
        x.teacher_id == current_teacher_id,     # 用户私有次之
        x.quality_score                         # 最后按质量分
    ), reverse=True)

    return sorted_results[:5]
```

---

### 2.5 场景 4: 题库管理

#### 用户故事

```
教师: 上传历年试卷、题目素材
AI: 生成题目时，参考用户题库 + 系统题库
```

#### 数据流

```
上传题目:
  前端 → Java 后端
    ↓ 1. 上传文件（图片/PDF）
    ↓ 2. OCR 提取题目文本
    ↓ 3. AI 解析题目结构（题干、选项、答案）
    ↓ 4. 向量化存入题库

AI 生成题目:
  AI-MCP
    ↓ 1. 检索相似题目（向量检索）
    ↓ 2. 分析题目模式
    ↓ 3. 生成新题目
```

#### 数据表设计

**question_bank 表**

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY | 记录 ID | 12345 |
| `question_id` | VARCHAR(100) | UNIQUE, NOT NULL | 题目唯一 ID | "q-uuid-9999" |
| `teacher_id` | VARCHAR(50) | NULL | 上传者（NULL=系统级） | "teacher-001" |
| `subject` | VARCHAR(50) | NOT NULL | 学科 | "数学" |
| `grade` | VARCHAR(50) | NOT NULL | 年级 | "初二" |
| `difficulty` | VARCHAR(20) | NOT NULL | 难度 | "easy", "medium", "hard" |
| `question_text` | TEXT | NOT NULL | 题目文本 | "下列关于二次函数的说法..." |
| `question_type` | VARCHAR(50) | NOT NULL | 题型 | "choice", "fill_blank", "essay" |
| `options` | JSON | NULL | 选项（选择题） | `["A. ...", "B. ..."]` |
| `answer` | TEXT | NULL | 答案 | "A" |
| `explanation` | TEXT | NULL | 解析 | "本题考查..." |
| `file_id` | VARCHAR(100) | NULL | 原始文件 ID | "file-uuid-8888" |
| `vector_id` | VARCHAR(100) | NOT NULL | 向量 ID | "vec-uuid-7777" |
| `tags` | JSON | NULL | 知识点标签 | ["函数", "图像"] |
| `is_public` | BOOLEAN | DEFAULT FALSE | 是否公开 | FALSE |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 | "2026-02-04 10:00:00" |

---

### 2.6 场景 5: 作业批改

#### 用户故事

```
教师: 上传学生答卷（图片/PDF）
AI: OCR 识别 → 自动批改 → 生成反馈
```

#### 数据流

```
上传答卷:
  前端 → Java 后端
    ↓ 1. 验证权限（classId 访问权限）
    ↓ 2. 上传到 OSS
    ↓ 3. 调用 AI-MCP 批改

AI 批改:
  AI-MCP
    ↓ 1. OCR 识别答卷
    ↓ 2. 从题库获取标准答案
    ↓ 3. LLM 批改（给分、评语）
    ↓ 4. 生成批改报告

Java 后端:
    ↓ 5. 存储批改结果
    ↓ 6. 返回给前端
```

#### 数据表设计

**homework_submissions 表**

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY | 记录 ID | 12345 |
| `submission_id` | VARCHAR(100) | UNIQUE, NOT NULL | 提交唯一 ID | "sub-uuid-9999" |
| `student_id` | VARCHAR(50) | NOT NULL | 学生 ID | "student-001" |
| `class_id` | VARCHAR(50) | NOT NULL | 班级 ID | "1A" |
| `assignment_id` | VARCHAR(100) | NOT NULL | 作业 ID | "assign-uuid-8888" |
| `file_id` | VARCHAR(100) | NOT NULL | 答卷文件 ID | "file-uuid-7777" |
| `ocr_result` | TEXT | NULL | OCR 识别结果 | "1. A\n2. B\n..." |
| `grading_result` | JSON | NULL | 批改结果 | `{score: 95, feedback: "..."}` |
| `graded_by` | VARCHAR(50) | NULL | 批改者（AI/教师） | "AI", "teacher-001" |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 提交时间 | "2026-02-04 10:00:00" |
| `graded_at` | TIMESTAMP | NULL | 批改时间 | "2026-02-04 10:05:00" |

---

## 3. 权限模型整合

### 3.1 资源权限矩阵

| 资源类型 | 归属 | 权限类型 | 检查逻辑 |
|----------|------|----------|----------|
| **App** | teacherId | owner/edit/execute/view | ai_app_shares 表 + owner 检查 |
| **RAG 素材** | teacherId | 私有/公开 | rag_materials.is_public + teacher_id |
| **教案知识库** | 系统级 | 全员可见 | knowledge_base_lessons.is_system=true |
| **题库** | teacherId/系统级 | 私有/公开/系统 | question_bank.is_public + teacher_id |
| **作业批改** | 学生 + 班级 | 班级权限 | teacher_class 表（教师-班级关系） |
| **文件** | teacherId | 私有 | ai_files.teacher_id |

---

### 3.2 权限检查流程

```java
// Java 后端通用权限检查
public boolean checkResourceAccess(
    String teacherId,
    String resourceType,
    String resourceId,
    String requiredPermission
) {
    switch (resourceType) {
        case "app":
            return checkAppPermission(teacherId, resourceId, requiredPermission);
        case "rag_material":
            return checkMaterialAccess(teacherId, resourceId);
        case "question":
            return checkQuestionAccess(teacherId, resourceId);
        case "submission":
            return checkSubmissionAccess(teacherId, resourceId);
        default:
            throw new IllegalArgumentException("Unknown resource type");
    }
}

// 示例：检查 RAG 素材访问权限
private boolean checkMaterialAccess(String teacherId, String materialId) {
    RagMaterial material = materialRepository.findByMaterialId(materialId)
        .orElseThrow(() -> new NotFoundException("Material not found"));

    // 1. 是否是上传者
    if (material.getTeacherId().equals(teacherId)) {
        return true;
    }

    // 2. 是否公开分享
    if (material.getIsPublic()) {
        return true;
    }

    // 3. 无权限
    return false;
}
```

---

## 4. 向量库架构

### 4.1 向量库设计

**Collection 结构**:

```
┌─────────────────────────────────────────────────────────────┐
│                      向量库（Milvus/Qdrant）                   │
├─────────────────────────────────────────────────────────────┤
│  Collection: rag_materials                                  │
│    - vector_id: VARCHAR                                     │
│    - embedding: VECTOR(1536)                                │
│    - material_id: VARCHAR                                   │
│    - teacher_id: VARCHAR                                    │
│    - is_public: BOOLEAN                                     │
├─────────────────────────────────────────────────────────────┤
│  Collection: knowledge_base_lessons                         │
│    - vector_id: VARCHAR                                     │
│    - embedding: VECTOR(1536)                                │
│    - lesson_id: VARCHAR                                     │
│    - is_system: BOOLEAN                                     │
│    - quality_score: INT                                     │
├─────────────────────────────────────────────────────────────┤
│  Collection: question_bank                                  │
│    - vector_id: VARCHAR                                     │
│    - embedding: VECTOR(1536)                                │
│    - question_id: VARCHAR                                   │
│    - teacher_id: VARCHAR (NULL=系统级)                       │
│    - is_public: BOOLEAN                                     │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 检索策略

**带权限的向量检索**:

```python
async def search_with_permission(
    collection: str,
    query_vector: List[float],
    teacher_id: str,
    top_k: int = 10
) -> List[dict]:
    # 1. 向量检索（预检索 top_k * 2）
    candidates = await vector_db.search(
        collection=collection,
        vector=query_vector,
        top_k=top_k * 2,
        filter={
            "$or": [
                {"is_public": True},            # 公开的
                {"teacher_id": teacher_id},     # 自己的
                {"is_system": True}             # 系统级的
            ]
        }
    )

    # 2. 二次过滤（Java 后端权限检查）
    results = []
    for candidate in candidates:
        has_access = await java_client.check_resource_access(
            jwt_token=jwt_token,
            resource_type=collection,
            resource_id=candidate.material_id
        )
        if has_access:
            results.append(candidate)

        if len(results) >= top_k:
            break

    return results
```

---

## 5. 完整数据流示例

### 5.1 示例：教师上传教案 → AI 生成新教案

```
步骤 1: 上传教案素材
  前端 → Java 后端
    POST /api/rag/materials/upload
    Body: { file, title: "二次函数教案", type: "lesson_plan" }

  Java 后端处理:
    1. 验证 JWT（teacherId）
    2. 上传文件到 OSS
    3. 提取文本内容
    4. 调用 AI-MCP 向量化

  AI-MCP（RAG 引擎）:
    5. 生成 Embedding
    6. 存入向量库

  Java 后端:
    7. 存储元数据到 MySQL
    8. 返回 material_id

步骤 2: 用户请求生成教案
  前端 → AI-MCP
    POST /api/workflow/generate
    Body: { prompt: "生成一节函数课教案", classIds: ["1A"] }

  AI-MCP（PlannerAgent）:
    1. 向量检索相关素材（系统级 + 用户私有）
       - 系统教案库：5 个相关教案（is_system=true）
       - 用户上传：1 个自己的教案
    2. 结合素材生成 Blueprint
    3. 调用 ExecutorAgent 生成 Page

  AI-MCP → Java 后端:
    4. 回写 Java（创建 App + Execution）

  Java 后端:
    5. 存储到 MySQL
    6. 上传 Page 到 OSS
    7. 返回 appId + executionId

  Java 后端 → 前端:
    8. 返回结果

步骤 3: 前端展示
  前端 → Java 后端
    GET /api/studio/teacher/me/executions/{executionId}

  Java 后端:
    1. 查询 execution 记录
    2. 生成 page_content_url 的签名 URL
    3. 返回签名 URL

  前端:
    4. 从 OSS 下载 Page JSON
    5. 渲染教案页面
```

---

## 6. OSS 目录结构设计

### 6.1 完整目录结构

```
insight-ai-oss/                    # OSS Bucket
├── files/                         # 用户上传的原始文件
│   ├── teacher-001/               # 按教师 ID 分组
│   │   ├── analysis/              # 按用途分类
│   │   │   ├── file-uuid-1.png
│   │   │   └── file-uuid-2.pdf
│   │   ├── lesson/
│   │   │   └── file-uuid-3.pptx
│   │   └── rag_materials/         # RAG 素材
│   │       ├── material-uuid-1.pdf
│   │       └── material-uuid-2.docx
│   └── teacher-002/
│       └── ...
├── executions/                    # App 执行结果
│   ├── exec-uuid-1/
│   │   ├── page.json              # Page 完整 JSON
│   │   ├── data.json              # 原始数据
│   │   └── compute.json           # 计算结果
│   └── exec-uuid-2/
│       └── ...
├── blueprints/                    # 超大 Blueprint（罕见）
│   ├── bp-uuid-1.json
│   └── ...
├── knowledge-base/                # 系统级知识库
│   ├── lessons/
│   │   ├── lesson-uuid-1.pdf      # 系统教案
│   │   └── lesson-uuid-2.docx
│   ├── questions/                 # 系统题库
│   │   ├── question-uuid-1.json
│   │   └── ...
│   └── references/                # 参考资料
│       └── ...
├── submissions/                   # 学生作业
│   ├── class-1A/
│   │   ├── student-001/
│   │   │   ├── submission-uuid-1.pdf
│   │   │   └── submission-uuid-2.jpg
│   │   └── student-002/
│   │       └── ...
│   └── class-1B/
│       └── ...
└── archives/                      # 归档（3 个月后迁移）
    └── 2026-01/
        └── ...
```

---

### 6.2 URL 命名规范

| 资源类型 | URL 格式 | 示例 |
|----------|----------|------|
| **用户文件** | `files/{teacherId}/{purpose}/{fileId}.{ext}` | `files/teacher-001/analysis/file-uuid-1.png` |
| **RAG 素材** | `files/{teacherId}/rag_materials/{materialId}.{ext}` | `files/teacher-001/rag_materials/material-uuid-1.pdf` |
| **执行结果** | `executions/{executionId}/{type}.json` | `executions/exec-uuid-1/page.json` |
| **系统知识库** | `knowledge-base/{type}/{resourceId}.{ext}` | `knowledge-base/lessons/lesson-uuid-1.pdf` |
| **学生作业** | `submissions/{classId}/{studentId}/{submissionId}.{ext}` | `submissions/class-1A/student-001/sub-uuid-1.pdf` |

---

## 7. 实施路线图

### Phase 1: 基础架构（P0）

- [ ] **JavaBackendClient 封装**（AI-MCP 端）
  - [ ] create_app, create_blueprint, create_execution
  - [ ] get_file, get_material, search_materials

- [ ] **Java 后端核心端点**
  - [ ] POST /api/studio/teacher/me/apps
  - [ ] POST /api/studio/teacher/me/apps/{appId}/blueprints
  - [ ] POST /api/studio/teacher/me/apps/{appId}/executions

- [ ] **文件管理**
  - [ ] POST /api/studio/teacher/me/files/upload
  - [ ] GET /api/studio/teacher/me/files/{fileId}
  - [ ] ai_files 表

### Phase 2: RAG 素材管理（P1）

- [ ] **RAG 素材上传**
  - [ ] POST /api/rag/materials/upload
  - [ ] rag_materials 表
  - [ ] 向量化集成（AI-MCP）

- [ ] **RAG 检索**
  - [ ] AI-MCP 端向量检索
  - [ ] 权限过滤

### Phase 3: 知识库管理（P1）

- [ ] **系统级知识库**
  - [ ] knowledge_base_lessons 表
  - [ ] question_bank 表
  - [ ] 管理员上传接口

- [ ] **检索优化**
  - [ ] 优先级排序（系统级 > 用户私有）
  - [ ] 质量评分机制

### Phase 4: 高级功能（P2）

- [ ] **作业批改**
  - [ ] homework_submissions 表
  - [ ] OCR 集成
  - [ ] 自动批改

- [ ] **归档策略**
  - [ ] 3 个月后迁移到冷存储
  - [ ] 自动清理

---

## 8. 常见问题

### Q1: RAG 素材和系统知识库有什么区别？

**答**:

| 维度 | RAG 素材 | 系统知识库 |
|------|----------|------------|
| **归属** | 用户私有（teacherId） | 系统级（全员可见） |
| **上传者** | 教师 | 管理员 |
| **权限** | 私有/可分享 | 全员可见 |
| **质量** | 不保证 | 高质量（经审核） |
| **检索优先级** | 次之 | 优先 |

---

### Q2: 向量库和 MySQL 的数据如何同步？

**答**:

**流程**:
```
1. Java 后端接收文件上传
2. 提取文本内容
3. 调用 AI-MCP 生成向量
4. AI-MCP 返回 vector_id
5. Java 后端同时写入：
   - MySQL: 元数据 + vector_id
   - 向量库: vector + metadata（已在步骤 3 完成）
```

**一致性保证**:
- 使用事务：MySQL 写入失败 → 删除向量
- 定期同步检查（cron job）

---

### Q3: 如何防止向量库泄露数据？

**答**:

**策略 1**: 向量库只存 metadata（不存内容）
```python
# 向量库中只存这些字段
{
    "vector_id": "vec-uuid-1",
    "embedding": [0.1, 0.2, ...],
    "material_id": "material-uuid-1",
    "teacher_id": "teacher-001",
    "is_public": false
}
```

**策略 2**: 检索后二次权限检查
```python
# 从向量库检索后，从 Java 后端获取完整内容
candidates = await vector_db.search(...)
for candidate in candidates:
    # Java 后端检查权限
    material = await java_client.get_material(
        jwt_token=jwt_token,
        material_id=candidate.material_id
    )  # 无权限会抛出 403
```

---

## 9. 下一步

1. 补充各场景的详细 API 设计
2. 绘制完整的时序图（Sequence Diagram）
3. 向量库选型（Milvus vs Qdrant）
4. RAG 引擎实现（Embedding 模型选择）

---

## 10. 相关文档

- [AI-MCP 与 Java 集成](./ai-mcp-java-integration.md) - App 生成数据流
- [存储优化方案](./storage-optimization-plan.md) - OSS 存储策略
- [API 分离与权限管理](./api-separation-and-permissions.md) - 版本分离设计
- [Java 后端集成规范](./java-backend-spec.md) - API 端点设计
