# Java 后端对接

> Java Backend API 端点、数据工具映射、对接计划。

---

## Java Backend API

服务地址：`http://localhost:8080`（开发环境）

| Method | Path | 功能 |
|--------|------|------|
| `GET` | `/dify/teacher/{id}/classes/me` | 获取教师的班级列表 |
| `GET` | `/dify/teacher/{id}/classes/{classId}` | 获取班级详情（含学生列表） |
| `GET` | `/dify/teacher/{id}/classes/{classId}/assignments` | 获取班级作业列表 |
| `GET` | `/dify/teacher/{id}/submissions/assignments/{assignmentId}` | 获取作业提交记录 |
| `GET` | `/dify/teacher/{id}/submissions/students/{studentId}` | 获取学生成绩详情 |

---

## FastMCP Data Tools 映射

每个 `@mcp.tool` 对应一个 Java API endpoint：

| FastMCP Tool | Java API | 说明 |
|--------------|----------|------|
| `get_teacher_classes(teacher_id)` | `GET /dify/teacher/{id}/classes/me` | 班级列表 |
| `get_class_detail(teacher_id, class_id)` | `GET /dify/teacher/{id}/classes/{classId}` | 班级详情 |
| `get_class_assignments(teacher_id, class_id)` | `GET /dify/teacher/{id}/classes/{classId}/assignments` | 作业列表 |
| `get_assignment_submissions(teacher_id, assignment_id)` | `GET /dify/teacher/{id}/submissions/assignments/{id}` | 作业提交 |
| `get_student_grades(teacher_id, student_id)` | `GET /dify/teacher/{id}/submissions/students/{id}` | 学生成绩 |

### 实现模式

```python
@mcp.tool
async def get_class_detail(
    teacher_id: Annotated[str, Field(description="教师 ID")],
    class_id: Annotated[str, Field(description="班级 ID")],
) -> dict:
    """获取班级详情，包括学生列表、班级元信息。"""
    settings = get_settings()
    if settings.use_mock_data:
        from services.mock_data import mock_class_detail
        return mock_class_detail(teacher_id, class_id)

    async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
        resp = await client.get(
            f"/dify/teacher/{teacher_id}/classes/{class_id}",
            timeout=settings.tool_timeout,
        )
        resp.raise_for_status()
        return resp.json()
```

### Mock / 真实切换

通过环境变量 `USE_MOCK_DATA=true/false` 切换：
- `true`: 调用 `services/mock_data.py` 中的 mock 函数
- `false`: 通过 `httpx` 调用真实 Java API

---

## 对接计划

### Phase 1-3: Mock 数据

- `USE_MOCK_DATA=true`
- 所有 data tools 返回 `services/mock_data.py` 中的硬编码数据
- 无需启动 Java 后端

### Phase 4: 真实对接

- [ ] `USE_MOCK_DATA=false`
- [ ] 配置 `JAVA_BACKEND_URL`
- [ ] 实现 httpx 调用（已在 data_tools.py 中预留）
- [ ] 错误处理 + 重试机制
- [ ] 数据格式映射（Java 返回格式 → 统一内部格式）
- [ ] 超时处理（`TOOL_TIMEOUT` 控制）

### 错误处理策略

```python
async with httpx.AsyncClient(base_url=settings.java_backend_url) as client:
    try:
        resp = await client.get(url, timeout=settings.tool_timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Backend timeout", "fallback": True}
    except httpx.HTTPStatusError as e:
        return {"error": f"Backend error: {e.response.status_code}"}
```
