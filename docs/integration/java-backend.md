# Java 后端对接

> SpringBoot 后端 HTTP 客户端、适配器层、数据模型映射。Phase 5 已实现。

---

## 架构概览

```
tools/data_tools.py          # FastMCP 工具（对外接口不变）
     ↓
adapters/                    # 适配器层：Java DTO → 内部模型
  ├─ class_adapter.py        # 班级 / 作业
  ├─ submission_adapter.py   # 作业提交
  └─ grade_adapter.py        # 学生成绩
     ↓
services/java_client.py      # httpx AsyncClient + retry + circuit breaker
     ↓
SpringBoot Backend           # https://api.insightai.hk/api
```

---

## Java Backend API

服务地址：`https://api.insightai.hk/api`（通过 `SPRING_BOOT_BASE_URL` + `SPRING_BOOT_API_PREFIX` 拼接）

| Method | Path | 功能 | Adapter |
|--------|------|------|---------|
| `GET` | `/dify/teacher/{id}/classes/me` | 教师的班级列表 | `class_adapter.list_classes()` |
| `GET` | `/dify/teacher/{id}/classes/{classId}` | 班级详情 | `class_adapter.get_detail()` |
| `GET` | `/dify/teacher/{id}/classes/{classId}/assignments` | 班级作业列表 | `class_adapter.list_assignments()` |
| `GET` | `/dify/teacher/{id}/submissions/assignments/{assignmentId}` | 作业提交记录 | `submission_adapter.get_submissions()` |
| `GET` | `/dify/teacher/{id}/submissions/students/{studentId}` | 学生成绩 | `grade_adapter.get_student_submissions()` |
| `GET` | `/dify/student/{id}/courses/{courseId}/mygrades` | 学生课程成绩 | `grade_adapter.get_course_grades()` |

所有 Java 响应遵循 `Result<T>` 包装格式：

```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "timestamp": "2026-01-13T12:00:00"
}
```

适配器通过 `_unwrap_data()` 提取 `data` 字段。

---

## FastMCP Data Tools 映射

| FastMCP Tool | Adapter 函数 | Java API |
|--------------|-------------|----------|
| `get_teacher_classes(teacher_id)` | `class_adapter.list_classes()` | `GET /dify/teacher/{id}/classes/me` |
| `get_class_detail(teacher_id, class_id)` | `class_adapter.get_detail()` | `GET /dify/teacher/{id}/classes/{classId}` |
| `get_class_assignments(teacher_id, class_id)` | `class_adapter.list_assignments()` | `GET .../assignments` |
| `get_assignment_submissions(teacher_id, assignment_id)` | `submission_adapter.get_submissions()` | `GET .../submissions/assignments/{id}` |
| `get_student_grades(teacher_id, student_id)` | `grade_adapter.get_student_submissions()` | `GET .../submissions/students/{id}` |

---

## HTTP 客户端 (JavaClient)

文件: `services/java_client.py`

### 特性

- **httpx.AsyncClient** 连接池，绑定 FastAPI lifespan 生命周期
- **Bearer Token** 认证 (`SPRING_BOOT_ACCESS_TOKEN`)
- **指数退避重试**: 最多 3 次，基础延迟 0.5s 翻倍
  - 重试: 5xx 服务端错误、网络错误
  - 不重试: 4xx 客户端错误（服务器存活）
- **熔断器**: 连续 5 次失败打开，60s 后半开探测
- **请求计时日志**: 每次请求记录 `METHOD PATH → STATUS (elapsed_ms)`
- **Token 热更新**: `update_tokens()` 无需重建客户端

### 使用方式

```python
from services.java_client import get_java_client

client = get_java_client()       # 单例
data = await client.get("/dify/teacher/123/classes/me")
```

### 生命周期

```python
# main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_java_client()
    await client.start()          # 创建连接池
    yield
    await client.close()          # 关闭连接池
```

---

## 适配器层 (adapters/)

每个适配器文件对应一组 Java API：

### class_adapter.py

- `list_classes(client, teacher_id)` → `list[ClassInfo]`
- `get_detail(client, teacher_id, class_id)` → `ClassDetail`
- `list_assignments(client, teacher_id, class_id)` → `list[AssignmentInfo]`

### submission_adapter.py

- `get_submissions(client, teacher_id, assignment_id)` → `SubmissionData`

### grade_adapter.py

- `get_student_submissions(client, teacher_id, student_id)` → `GradeData`
- `get_course_grades(client, student_id, course_id)` → `GradeData`

### 字段映射规则

- **ID 优先级**: `uid` > `id`（Java DTO 两种 ID 字段并存）
- **分页响应**: `list_assignments` 处理 `PageResponseDTO` 的 `{data: [...], pagination: {...}}` 格式
- **分数提取**: `submission_adapter` 从 records 中提取 `scores` 数组
- **均分 / 最高分**: `grade_adapter` 从记录列表中计算

---

## 内部数据模型 (models/data.py)

解耦 Java DTO 与系统内部表示：

| 模型 | 字段 | 来源 |
|------|------|------|
| `ClassInfo` | class_id, name, grade, subject, student_count, ... | Classroom DTO |
| `ClassDetail` | extends ClassInfo + students, assignments | Classroom DTO |
| `AssignmentInfo` | assignment_id, title, type, max_score, status, ... | ClassAssignmentDTO |
| `SubmissionRecord` | student_id, name, score, submitted, status, feedback | SubmissionDTO |
| `SubmissionData` | assignment_id, title, submissions, scores | 聚合 |
| `GradeRecord` | assignment_id, title, score, max_score, percentage | SubmissionDTO / GradeHistoryItem |
| `GradeData` | student_id, name, average_score, highest_score, grades | 聚合 |

---

## Mock / 真实切换

通过环境变量 `USE_MOCK_DATA` 控制：

| USE_MOCK_DATA | 行为 |
|---------------|------|
| `true` | 始终返回 mock 数据，不调用 Java 后端 |
| `false` (默认) | 调用 Java 后端 → 成功则返回真实数据 → 失败则 fallback 到 mock |

Data tools 中的 fallback 逻辑：

```python
async def get_teacher_classes(teacher_id: str) -> dict:
    if _should_use_mock():
        return _mock_teacher_classes(teacher_id)
    try:
        client = _get_client()
        classes = await list_classes(client, teacher_id)
        return {"teacher_id": teacher_id, "classes": [c.model_dump() for c in classes]}
    except Exception:
        logger.exception("get_teacher_classes failed, falling back to mock")
        return _mock_teacher_classes(teacher_id)
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SPRING_BOOT_BASE_URL` | Java 后端基础地址 | `https://api.insightai.hk` |
| `SPRING_BOOT_API_PREFIX` | API 路径前缀 | `/api` |
| `SPRING_BOOT_ACCESS_TOKEN` | Bearer 访问令牌 | - |
| `SPRING_BOOT_REFRESH_TOKEN` | 刷新令牌 | - |
| `SPRING_BOOT_TIMEOUT` | 请求超时 (秒) | `15` |
| `USE_MOCK_DATA` | 强制使用 Mock 数据 | `false` |
