# AI-MCP 与 Java 后端集成方案

> **文档目的**: 定义 AI-MCP 作为无状态计算服务的职责边界与 Java 后端的集成规范
> **核心原则**: AI-MCP 不持久化用户数据，所有数据归属由 Java 后端从 JWT 决定
> **修订日期**: 2026-02-04

---

## 1. 问题背景

### 1.1 当前架构问题

**现状**:
```
用户（前端）→ AI-MCP（使用自己的账号）→ 生成 Blueprint/Page
                ↓
          直接落库？（问题：数据归属到 AI 账号）
```

**问题**:
1. AI-MCP 使用自己的账号运行
2. Blueprint/Execution 等数据应该归属到用户（教师）
3. 如果 AI 端直接落库，会出现"数据归属不明确"的问题

---

### 1.2 设计目标

1. **数据归属明确**: 所有用户数据归属到 teacherId（从 JWT 解析）
2. **职责分离**: AI-MCP 只负责计算，Java 后端负责鉴权 + 落库
3. **无状态设计**: AI-MCP 不持久化任何用户数据
4. **最小改动**: 保持前端"先 call AI"的流程不变

---

## 2. 优化后的架构

### 2.1 核心设计

```
前端（用户 JWT）
  ↓
AI-MCP（透传 JWT，无状态计算服务）
  ↓ 调用 LLM/工具
  ↓ 生成 Blueprint/Page
  ↓
Java 后端（从 JWT 解析 teacherId，鉴权 + 落库）
  ↓
MySQL + OSS（数据持久化）
```

### 2.2 职责划分

#### AI-MCP 的职责

| 职责 | 说明 | 示例 |
|------|------|------|
| **接收前端请求** | 验证 JWT 格式，提取 teacherId | 验证 Authorization header |
| **调用 PlannerAgent** | 根据 prompt 生成 Blueprint | 自然语言 → Blueprint JSON |
| **调用 ExecutorAgent** | 根据 Blueprint 生成 Page | Blueprint + 数据 → Page JSON |
| **调用工具** | 获取班级/成绩/提交数据 | `get_class_students(classId)` |
| **回写 Java 后端** | 生成的 Blueprint/Page 发送给 Java | POST /api/studio/teacher/me/apps |
| **返回结果** | 将 Java 后端的响应返回给前端 | `{ appId, blueprintId, executionId }` |

**⚠️ AI-MCP 不做的事情**:
- ❌ 不持久化任何用户数据（Blueprint/Page/Execution）
- ❌ 不直接操作 MySQL/OSS
- ❌ 不管理用户权限（只透传 JWT）

#### Java 后端的职责

| 职责 | 说明 | 示例 |
|------|------|------|
| **鉴权** | 验证 JWT，解析 teacherId | 从 JWT Payload 提取 teacherId |
| **权限检查** | 检查班级访问权限、App 所有权 | teacherClassRepository.findByTeacherId |
| **数据持久化** | 存储 App/Blueprint/Execution | INSERT INTO ai_apps, ai_blueprints |
| **OSS 管理** | 上传大字段到 OSS，返回 URL | 上传 pageContent → page_content_url |
| **版本管理** | Blueprint 版本控制 | MAX(version) + 1 |
| **分享管理** | App 分享权限控制 | ai_app_shares 表 |

---

## 3. 数据流详解

### 3.1 场景 1: 创建 App + Blueprint v1 + 首次执行

#### 步骤 1: 前端调用 AI-MCP

```http
POST /api/workflow/generate
Headers:
  Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Content-Type: application/json

{
  "prompt": "分析1A班期中考试成绩",
  "classIds": ["1A"],
  "tags": ["期中", "数学"]
}
```

#### 步骤 2: AI-MCP 内部处理

```python
# 1. 验证 JWT（提取 teacherId，但不做鉴权）
teacher_id = extract_teacher_id_from_jwt(request.headers["Authorization"])

# 2. 调用 PlannerAgent 生成 Blueprint
blueprint = await planner_agent.generate_blueprint(
    prompt=request.prompt,
    context={"classIds": request.classIds}
)

# 3. 调用 ExecutorAgent 生成 Page
page_result = await executor_agent.execute_blueprint(
    blueprint=blueprint,
    class_ids=request.classIds
)

# 4. 回写 Java 后端（透传 JWT）
java_response = await java_client.create_app(
    jwt_token=request.headers["Authorization"],  # ⭐ 透传 JWT
    data={
        "appName": extract_app_name(request.prompt),
        "appType": "analysis",
        "blueprint": blueprint.model_dump(),
        "pageContent": page_result.page.model_dump(),
        "dataContext": page_result.data_context,
        "computeResults": page_result.compute_results,
        "classIds": request.classIds,
        "tags": request.tags
    }
)

# 5. 返回 Java 后端的响应
return java_response
```

#### 步骤 3: Java 后端处理

```java
@PostMapping("/api/studio/teacher/me/apps")
public ResponseEntity<CreateAppResponse> createApp(
    @RequestHeader("Authorization") String authHeader,
    @RequestBody CreateAppRequest request
) {
    // 1. 验证 JWT，解析 teacherId
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 2. 检查班级访问权限（如果有 classIds）
    if (request.getClassIds() != null) {
        validateClassAccess(teacherId, request.getClassIds());
    }

    // 3. 生成 ID
    String appId = generateUUID("app");
    String blueprintId = generateUUID("bp");
    String executionId = generateUUID("exec");

    // 4. 上传大字段到 OSS
    String pageContentUrl = ossService.upload(
        "executions/" + executionId + "/page.json",
        toJson(request.getPageContent())
    );

    String dataContextUrl = ossService.upload(
        "executions/" + executionId + "/data.json",
        toJson(request.getDataContext())
    );

    // 5. 存储到 MySQL
    App app = new App(appId, teacherId, request.getAppName(), ...);
    appRepository.save(app);

    Blueprint blueprint = new Blueprint(blueprintId, appId, 1, request.getBlueprint());
    blueprintRepository.save(blueprint);

    Execution execution = new Execution(
        executionId, appId, blueprintId, teacherId,
        pageContentUrl, dataContextUrl, ...
    );
    executionRepository.save(execution);

    // 6. 返回结果
    return ResponseEntity.ok(new CreateAppResponse(
        appId, blueprintId, 1, executionId
    ));
}
```

**关键点**:
- ✅ Java 后端从 JWT 解析 teacherId（**数据归属明确**）
- ✅ Java 后端检查班级访问权限（**防止越权**）
- ✅ Java 后端管理 OSS 上传（**统一管理**）
- ✅ AI-MCP 只负责计算（**无状态**）

---

### 3.2 场景 2: 修改 Blueprint（创建新版本）

#### 步骤 1: 前端调用 AI-MCP

```http
POST /api/workflow/generate
Headers:
  Authorization: Bearer <JWT>
Content-Type: application/json

{
  "prompt": "增加趋势图",
  "appId": "app-uuid-1234"
}
```

#### 步骤 2: AI-MCP 内部处理

```python
# 1. 查询当前 Blueprint（从 Java 后端）
current_blueprint = await java_client.get_current_blueprint(
    jwt_token=request.headers["Authorization"],
    app_id=request.appId
)

# 2. 调用 PlannerAgent 生成新 Blueprint
new_blueprint = await planner_agent.update_blueprint(
    current_blueprint=current_blueprint,
    prompt=request.prompt
)

# 3. 回写 Java 后端（创建新版本）
java_response = await java_client.create_blueprint_version(
    jwt_token=request.headers["Authorization"],
    app_id=request.appId,
    data={
        "blueprint": new_blueprint.model_dump(),
        "changeSummary": request.prompt,
        "activateImmediately": True
    }
)

return java_response
```

#### 步骤 3: Java 后端处理

```java
@PostMapping("/api/studio/teacher/me/apps/{appId}/blueprints")
public ResponseEntity<CreateBlueprintResponse> createBlueprintVersion(
    @RequestHeader("Authorization") String authHeader,
    @PathVariable String appId,
    @RequestBody CreateBlueprintRequest request
) {
    // 1. 验证 JWT，解析 teacherId
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 2. 检查权限（是否是 owner 或有 edit 权限）
    checkPermission(teacherId, appId, "edit");

    // 3. 查询当前最大版本号
    int maxVersion = blueprintRepository.findMaxVersionByAppId(appId);
    int newVersion = maxVersion + 1;

    // 4. 生成新 Blueprint ID
    String blueprintId = generateUUID("bp");

    // 5. 存储新版本
    Blueprint blueprint = new Blueprint(
        blueprintId, appId, newVersion,
        request.getBlueprint(), request.getChangeSummary()
    );
    blueprintRepository.save(blueprint);

    // 6. 更新 App（如果需要激活）
    if (request.getActivateImmediately()) {
        appRepository.updateCurrentBlueprint(appId, blueprintId, newVersion);
    }

    return ResponseEntity.ok(new CreateBlueprintResponse(
        appId, blueprintId, newVersion
    ));
}
```

---

### 3.3 场景 3: 执行 Blueprint（使用当前版本）

#### 步骤 1: 前端调用 AI-MCP

```http
POST /api/page/generate (SSE)
Headers:
  Authorization: Bearer <JWT>
Content-Type: application/json

{
  "appId": "app-uuid-1234",
  "classIds": ["1A"]
}
```

#### 步骤 2: AI-MCP 内部处理

```python
# 1. 查询当前 Blueprint（从 Java 后端）
app_info = await java_client.get_app(
    jwt_token=request.headers["Authorization"],
    app_id=request.appId
)

# 2. 调用 ExecutorAgent 生成 Page（SSE 流式输出）
async for event in executor_agent.execute_blueprint_stream(
    blueprint_id=app_info.current_blueprint_id,
    class_ids=request.classIds
):
    yield event  # 流式返回给前端

# 3. 执行完成后，回写 Java 后端
java_response = await java_client.create_execution(
    jwt_token=request.headers["Authorization"],
    app_id=request.appId,
    data={
        "pageContent": page_result.page.model_dump(),
        "dataContext": page_result.data_context,
        "computeResults": page_result.compute_results,
        "classIds": request.classIds
    }
)
```

---

## 4. JWT 传递机制

### 4.1 前端 → AI-MCP

```http
POST /api/workflow/generate
Headers:
  Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**AI-MCP 处理**:
```python
from fastapi import Header

@app.post("/api/workflow/generate")
async def generate_workflow(
    request: WorkflowRequest,
    authorization: str = Header(...)  # ⭐ 提取 JWT
):
    # 验证 JWT 格式（不做鉴权，只提取 teacherId）
    teacher_id = extract_teacher_id(authorization)

    # ... 生成 Blueprint/Page ...

    # 回写 Java 后端时透传 JWT
    await java_client.create_app(
        jwt_token=authorization,  # ⭐ 透传
        data={...}
    )
```

### 4.2 AI-MCP → Java 后端

```python
import httpx

class JavaBackendClient:
    async def create_app(self, jwt_token: str, data: dict):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/studio/teacher/me/apps",
                headers={
                    "Authorization": jwt_token,  # ⭐ 透传 JWT
                    "Content-Type": "application/json"
                },
                json=data
            )
            return response.json()
```

### 4.3 Java 后端鉴权

```java
@PostMapping("/api/studio/teacher/me/apps")
public ResponseEntity<CreateAppResponse> createApp(
    @RequestHeader("Authorization") String authHeader,
    @RequestBody CreateAppRequest request
) {
    // 1. 验证 JWT
    String jwt = authHeader.replace("Bearer ", "");
    if (!jwtService.validateToken(jwt)) {
        throw new UnauthorizedException("Invalid JWT");
    }

    // 2. 解析 teacherId
    String teacherId = jwtService.extractTeacherId(jwt);

    // 3. 检查权限
    validateClassAccess(teacherId, request.getClassIds());

    // 4. 落库（数据归属到 teacherId）
    ...
}
```

**关键点**:
- ✅ AI-MCP 只提取 teacherId（用于日志/调试）
- ✅ Java 后端从 JWT 解析 teacherId（**数据归属明确**）
- ✅ Java 后端验证 JWT 签名（**防止伪造**）

---

## 5. OSS 存储责任分配

### 方案对比

| 方案 | 优势 | 劣势 | 推荐 |
|------|------|------|------|
| **方案 A**: AI-MCP 上传 OSS，传 URL 给 Java | 减轻 Java 负载 | AI-MCP 需要 OSS 凭证，安全性差 | ❌ 不推荐 |
| **方案 B**: AI-MCP 传原始数据给 Java，Java 上传 OSS | Java 统一管理 OSS，安全性好 | Java 负载稍高 | ✅ **推荐** |

### 推荐方案 B 实现

#### AI-MCP 端

```python
# 生成完整的 Page JSON，不上传 OSS
page_result = await executor_agent.execute_blueprint(...)

# 回写 Java 后端（传原始数据）
await java_client.create_execution(
    jwt_token=authorization,
    app_id=request.appId,
    data={
        "pageContent": page_result.page.model_dump(),        # 原始 JSON
        "dataContext": page_result.data_context,             # 原始 JSON
        "computeResults": page_result.compute_results,       # 原始 JSON
        "classIds": request.classIds
    }
)
```

#### Java 后端

```java
@PostMapping("/api/studio/teacher/me/apps/{appId}/executions")
public ResponseEntity<CreateExecutionResponse> createExecution(
    @RequestHeader("Authorization") String authHeader,
    @PathVariable String appId,
    @RequestBody CreateExecutionRequest request
) {
    String teacherId = jwtService.extractTeacherId(authHeader);
    checkPermission(teacherId, appId, "execute");

    String executionId = generateUUID("exec");

    // ⭐ Java 负责上传到 OSS
    String pageContentUrl = ossService.upload(
        "executions/" + executionId + "/page.json",
        toJson(request.getPageContent())
    );

    String dataContextUrl = ossService.upload(
        "executions/" + executionId + "/data.json",
        toJson(request.getDataContext())
    );

    // 存储到 MySQL（只存 URL）
    Execution execution = new Execution(
        executionId, appId, blueprintId, teacherId,
        pageContentUrl, dataContextUrl, ...
    );
    executionRepository.save(execution);

    return ResponseEntity.ok(new CreateExecutionResponse(executionId));
}
```

**优势**:
- ✅ OSS 凭证只在 Java 后端配置（安全）
- ✅ 统一的 OSS 管理（便于监控/归档）
- ✅ AI-MCP 无状态（不关心存储细节）

---

## 6. Java 后端新增端点

### 6.1 创建 App + Blueprint v1 + 首次执行

**端点**: `POST /api/studio/teacher/me/apps`

**Headers**:
```
Authorization: Bearer <JWT>
Content-Type: application/json
```

**请求体**:
```json
{
  "appName": "1A班期中分析",
  "appType": "analysis",
  "blueprint": {
    "meta": {...},
    "dataContract": {...},
    "computeGraph": {...},
    "uiComposition": {...}
  },
  "pageContent": {...},
  "dataContext": {...},
  "computeResults": {...},
  "classIds": ["1A"],
  "tags": ["期中", "数学"]
}
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
    "createdAt": "2026-02-04T10:00:00Z"
  }
}
```

---

### 6.2 创建 Blueprint 版本（不执行）

**端点**: `POST /api/studio/teacher/me/apps/{appId}/blueprints`

**Headers**:
```
Authorization: Bearer <JWT>
```

**请求体**:
```json
{
  "blueprint": {...},
  "changeSummary": "调整布局，增加趋势图",
  "activateImmediately": true
}
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
    "createdAt": "2026-02-04T10:30:00Z"
  }
}
```

---

### 6.3 创建执行记录（使用当前版本）

**端点**: `POST /api/studio/teacher/me/apps/{appId}/executions`

**Headers**:
```
Authorization: Bearer <JWT>
```

**请求体**:
```json
{
  "pageContent": {...},
  "dataContext": {...},
  "computeResults": {...},
  "classIds": ["1A"],
  "tags": ["3月"]
}
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

---

### 6.4 查询当前 Blueprint

**端点**: `GET /api/studio/teacher/me/apps/{appId}/blueprints/current`

**Headers**:
```
Authorization: Bearer <JWT>
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "appId": "app-uuid-1234",
    "blueprintId": "bp-uuid-8888",
    "version": 2,
    "blueprint": {...},
    "createdAt": "2026-02-20T10:00:00Z"
  }
}
```

---

## 7. AI-MCP 端实施清单

### Phase 1: 基础集成（P0）

- [ ] **JavaBackendClient 封装**
  - [ ] 实现 `create_app(jwt_token, data)`
  - [ ] 实现 `create_blueprint_version(jwt_token, app_id, data)`
  - [ ] 实现 `create_execution(jwt_token, app_id, data)`
  - [ ] 实现 `get_current_blueprint(jwt_token, app_id)`

- [ ] **JWT 透传机制**
  - [ ] 修改 `/api/workflow/generate` 提取 JWT
  - [ ] 修改 `/api/page/generate` 提取 JWT
  - [ ] 所有 Java 后端调用携带 JWT

- [ ] **移除本地持久化**
  - [ ] 移除所有 Blueprint/Page 的本地存储逻辑
  - [ ] 只保留内存缓存（可选，用于性能优化）

### Phase 2: 错误处理（P1）

- [ ] **Java 后端调用失败处理**
  - [ ] 401 Unauthorized → 返回给前端（JWT 失效）
  - [ ] 403 Forbidden → 返回给前端（无权限）
  - [ ] 500 Internal Server Error → 重试 3 次

- [ ] **降级策略**
  - [ ] Java 后端不可用时的降级方案
  - [ ] 返回生成的 Blueprint/Page，但标记"未保存"

### Phase 3: 性能优化（P2）

- [ ] **缓存机制**
  - [ ] 缓存 Blueprint（减少 Java 后端查询）
  - [ ] 缓存 App 信息（TTL 5 分钟）

- [ ] **批量上传**
  - [ ] 支持批量创建执行记录

---

## 8. Java 后端实施清单

### Phase 1: 基础端点（P0）

- [ ] **创建 App**
  - [ ] POST /api/studio/teacher/me/apps
  - [ ] 从 JWT 解析 teacherId
  - [ ] 上传 pageContent/dataContext 到 OSS
  - [ ] 存储到 MySQL

- [ ] **创建 Blueprint 版本**
  - [ ] POST /api/studio/teacher/me/apps/{appId}/blueprints
  - [ ] 检查 edit 权限
  - [ ] 版本号自增
  - [ ] 可选激活

- [ ] **创建执行记录**
  - [ ] POST /api/studio/teacher/me/apps/{appId}/executions
  - [ ] 检查 execute 权限
  - [ ] 上传到 OSS
  - [ ] 提取 thumbnail

- [ ] **查询当前 Blueprint**
  - [ ] GET /api/studio/teacher/me/apps/{appId}/blueprints/current
  - [ ] 检查 view 权限

### Phase 2: 鉴权与权限（P1）

- [ ] **JWT 验证**
  - [ ] 验证签名
  - [ ] 检查过期时间
  - [ ] 提取 teacherId

- [ ] **资源权限检查**
  - [ ] 实现 `checkPermission(teacherId, appId, requiredPermission)`
  - [ ] 检查 owner/分享权限

- [ ] **班级权限检查**
  - [ ] 实现 `validateClassAccess(teacherId, classIds)`

### Phase 3: OSS 管理（P1）

- [ ] **OSS 上传**
  - [ ] 封装 `ossService.upload(path, content)`
  - [ ] 目录结构：executions/{executionId}/page.json

- [ ] **签名 URL 生成**
  - [ ] 封装 `ossService.generateSignedUrl(url, expireSeconds)`
  - [ ] 有效期 1 小时

---

## 9. 常见问题

### Q1: AI-MCP 如何验证 JWT？

**答**: AI-MCP 只做**格式验证 + 提取 teacherId**，不做真正的鉴权。

```python
def extract_teacher_id(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        raise ValueError("Invalid Authorization header")

    jwt_token = authorization[7:]  # 去掉 "Bearer "

    # 解码 JWT（不验证签名，只提取 Payload）
    import base64
    import json
    payload = jwt_token.split(".")[1]
    payload_data = json.loads(base64.b64decode(payload + "=="))

    return payload_data.get("teacherId")
```

**重要**: 真正的鉴权在 Java 后端，AI-MCP 只用于日志记录。

---

### Q2: 如果 Java 后端不可用怎么办？

**方案 A**: 降级到本地存储（临时）
```python
try:
    await java_client.create_app(...)
except JavaBackendUnavailable:
    # 降级：返回生成的 Blueprint/Page，但标记"未保存"
    return {
        "status": "generated_but_not_saved",
        "blueprint": blueprint.model_dump(),
        "message": "数据已生成，但后端服务不可用，请稍后重试"
    }
```

**方案 B**: 返回错误
```python
try:
    await java_client.create_app(...)
except JavaBackendUnavailable:
    raise HTTPException(
        status_code=503,
        detail="Backend service unavailable"
    )
```

推荐**方案 B**（明确告知前端失败，避免数据不一致）。

---

### Q3: 如何防止 AI-MCP 伪造 teacherId？

**答**: Java 后端**只信任 JWT**，不信任 AI-MCP 传的任何 ID。

```java
@PostMapping("/api/studio/teacher/me/apps")
public ResponseEntity<CreateAppResponse> createApp(
    @RequestHeader("Authorization") String authHeader,
    @RequestBody CreateAppRequest request
) {
    // ⭐ 从 JWT 解析 teacherId（不信任请求体）
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 如果请求体包含 teacherId，验证是否一致
    if (request.getTeacherId() != null && !request.getTeacherId().equals(teacherId)) {
        throw new ForbiddenException("teacherId mismatch");
    }

    // 使用从 JWT 解析的 teacherId
    App app = new App(appId, teacherId, ...);
    ...
}
```

---

### Q4: AI-MCP 是否需要存储 JWT？

**答**: 不需要。JWT 只在请求期间透传，不持久化。

```python
@app.post("/api/workflow/generate")
async def generate_workflow(
    request: WorkflowRequest,
    authorization: str = Header(...)
):
    # ❌ 不存储 JWT
    # ✅ 只在本次请求中使用

    blueprint = await planner_agent.generate_blueprint(...)

    # 回写 Java 时透传
    await java_client.create_app(
        jwt_token=authorization,  # 透传
        data={...}
    )

    # 请求结束后，JWT 自动丢弃
```

---

## 10. 总结

### 核心优势

1. **数据归属明确**: 所有数据由 Java 后端从 JWT 解析 teacherId
2. **职责分离**: AI-MCP 只负责计算，Java 后端负责鉴权 + 落库
3. **无状态设计**: AI-MCP 不持久化任何用户数据
4. **最小改动**: 前端流程不变（仍然先 call AI）

### 实施优先级

**P0**: AI-MCP 回写 Java 后端（JavaBackendClient + JWT 透传）
**P1**: Java 后端鉴权与 OSS 管理
**P2**: 错误处理与性能优化

### 下一步

1. 实现 AI-MCP 的 `JavaBackendClient`
2. 实现 Java 后端的 3 个核心端点（create_app, create_blueprint, create_execution）
3. 端到端测试（前端 → AI-MCP → Java → MySQL/OSS）

---

## 10. 大文件处理机制（图片、PPT 等）

### 10.1 设计原则

**问题**: 大文件（图片、PPT、PDF 等）如果在 前端 → AI-MCP → Java 之间传递，会：
- ❌ 浪费带宽（多次传输）
- ❌ 增加延迟（AI-MCP 处理时间）
- ❌ 增加内存占用

**解决方案**: **前端直接上传到 OSS，只传 file_id**

```
前端
  ↓ 1. 上传文件到 OSS
Java 后端 (OSS Upload API)
  ↓ 2. 返回 file_id
前端
  ↓ 3. 传 file_id 给 AI-MCP
AI-MCP
  ↓ 4. 根据 file_id 按需拉取文件（lazy loading）
Java 后端 (File Retrieval API)
```

---

### 10.2 文件上传流程

#### 步骤 1: 前端上传文件

```http
POST /api/studio/teacher/me/files/upload
Headers:
  Authorization: Bearer <JWT>
Content-Type: multipart/form-data

Body:
  file: <binary data>
  fileType: "image/png"
  purpose: "analysis"  // 可选：用途（如 "analysis", "lesson_material"）
```

**Java 后端处理**:
```java
@PostMapping("/api/studio/teacher/me/files/upload")
public ResponseEntity<FileUploadResponse> uploadFile(
    @RequestHeader("Authorization") String authHeader,
    @RequestParam("file") MultipartFile file,
    @RequestParam(required = false) String purpose
) {
    // 1. 验证 JWT
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 2. 验证文件类型和大小
    validateFile(file);  // 最大 50MB，支持 png/jpg/pdf/ppt/pptx

    // 3. 生成 file_id
    String fileId = generateUUID("file");

    // 4. 上传到 OSS
    String ossPath = String.format("files/%s/%s/%s",
        teacherId,
        purpose != null ? purpose : "general",
        fileId + getFileExtension(file.getOriginalFilename())
    );

    String ossUrl = ossService.upload(ossPath, file.getInputStream());

    // 5. 存储到 MySQL（文件元数据）
    FileMetadata metadata = new FileMetadata(
        fileId, teacherId, file.getOriginalFilename(),
        file.getContentType(), file.getSize(),
        ossUrl, purpose
    );
    fileRepository.save(metadata);

    // 6. 返回 file_id
    return ResponseEntity.ok(new FileUploadResponse(
        fileId,
        file.getOriginalFilename(),
        file.getContentType(),
        file.getSize(),
        purpose
    ));
}
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "fileId": "file-uuid-9999",
    "fileName": "exam-data.png",
    "fileType": "image/png",
    "fileSize": 204800,
    "purpose": "analysis",
    "uploadedAt": "2026-02-04T10:00:00Z"
  }
}
```

---

#### 步骤 2: 前端传 file_id 给 AI-MCP

```http
POST /api/workflow/generate
Headers:
  Authorization: Bearer <JWT>
Content-Type: application/json

{
  "prompt": "分析这张成绩表",
  "fileIds": ["file-uuid-9999"],  // ⭐ 只传 file_id
  "classIds": ["1A"]
}
```

---

#### 步骤 3: AI-MCP 按需拉取文件

**场景 A**: AI 需要文件内容（如 OCR、图片分析）

```python
# AI-MCP 内部处理
async def generate_workflow(request: WorkflowRequest, authorization: str):
    # 1. 如果有 fileIds，拉取文件内容
    files_content = []
    if request.fileIds:
        for file_id in request.fileIds:
            file_info = await java_client.get_file(
                jwt_token=authorization,
                file_id=file_id
            )

            # 根据文件类型处理
            if file_info.fileType.startswith("image/"):
                # 下载图片内容（用于 OCR 或视觉分析）
                image_data = await java_client.download_file(
                    jwt_token=authorization,
                    file_id=file_id
                )
                files_content.append({
                    "fileId": file_id,
                    "type": "image",
                    "data": image_data
                })
            elif file_info.fileType == "application/pdf":
                # PDF 可能只需要元数据，不需要下载全文
                files_content.append({
                    "fileId": file_id,
                    "type": "pdf",
                    "fileName": file_info.fileName
                })

    # 2. 调用 PlannerAgent（传入文件内容）
    blueprint = await planner_agent.generate_blueprint(
        prompt=request.prompt,
        files=files_content
    )
```

**场景 B**: AI 不需要文件内容（只在 Page 中引用）

```python
# Blueprint 中只保存 file_id 引用
blueprint = Blueprint(
    meta=BlueprintMeta(
        pageTitle="成绩分析",
        pageType="analysis"
    ),
    uiComposition=UIComposition(
        layout=Layout(type="grid", columns=2),
        components=[
            {
                "id": "image-1",
                "type": "image",
                "props": {
                    "fileId": "file-uuid-9999",  // ⭐ 只保存 file_id
                    "alt": "成绩表"
                }
            }
        ]
    )
)
```

---

### 10.3 Java 后端文件 API

#### 获取文件元数据

**端点**: `GET /api/studio/teacher/me/files/{fileId}`

**Headers**:
```
Authorization: Bearer <JWT>
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "fileId": "file-uuid-9999",
    "fileName": "exam-data.png",
    "fileType": "image/png",
    "fileSize": 204800,
    "purpose": "analysis",
    "ossUrl": "https://oss.insightai.hk/files/teacher-001/analysis/file-uuid-9999.png",
    "uploadedAt": "2026-02-04T10:00:00Z"
  }
}
```

**Java 实现**:
```java
@GetMapping("/api/studio/teacher/me/files/{fileId}")
public ResponseEntity<FileInfoResponse> getFile(
    @RequestHeader("Authorization") String authHeader,
    @PathVariable String fileId
) {
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 查询文件元数据
    FileMetadata file = fileRepository.findByFileId(fileId)
        .orElseThrow(() -> new NotFoundException("File not found"));

    // 检查权限（只能访问自己上传的文件）
    if (!file.getTeacherId().equals(teacherId)) {
        throw new ForbiddenException("No access to this file");
    }

    return ResponseEntity.ok(new FileInfoResponse(file));
}
```

---

#### 下载文件内容

**端点**: `GET /api/studio/teacher/me/files/{fileId}/download`

**Headers**:
```
Authorization: Bearer <JWT>
```

**返回结果**:
```json
{
  "code": 200,
  "data": {
    "fileId": "file-uuid-9999",
    "signedUrl": "https://oss.insightai.hk/files/...?signature=xxx&expires=3600",
    "expiresIn": 3600  // 1 小时
  }
}
```

**Java 实现**:
```java
@GetMapping("/api/studio/teacher/me/files/{fileId}/download")
public ResponseEntity<FileDownloadResponse> downloadFile(
    @RequestHeader("Authorization") String authHeader,
    @PathVariable String fileId
) {
    String teacherId = jwtService.extractTeacherId(authHeader);

    // 查询文件
    FileMetadata file = fileRepository.findByFileId(fileId)
        .orElseThrow(() -> new NotFoundException("File not found"));

    // 检查权限
    if (!file.getTeacherId().equals(teacherId)) {
        throw new ForbiddenException("No access to this file");
    }

    // 生成签名 URL（1 小时有效期）
    String signedUrl = ossService.generateSignedUrl(
        file.getOssUrl(),
        3600
    );

    return ResponseEntity.ok(new FileDownloadResponse(
        fileId, signedUrl, 3600
    ));
}
```

---

### 10.4 Blueprint/Page 中的文件引用

#### 示例 1: 图片组件

```json
{
  "id": "image-1",
  "type": "image",
  "props": {
    "fileId": "file-uuid-9999",
    "alt": "1A班成绩分布图",
    "width": "100%",
    "caption": "期中考试成绩分布"
  }
}
```

**前端渲染时**:
```typescript
// 前端从 Java 后端获取签名 URL
const imageUrl = await api.getFileDownloadUrl(component.props.fileId);

// 渲染图片
<img src={imageUrl} alt={component.props.alt} />
```

---

#### 示例 2: PDF 预览组件

```json
{
  "id": "pdf-viewer-1",
  "type": "pdf_viewer",
  "props": {
    "fileId": "file-uuid-8888",
    "fileName": "教案.pdf",
    "pageNumber": 1
  }
}
```

---

#### 示例 3: 文件下载按钮

```json
{
  "id": "download-1",
  "type": "download_button",
  "props": {
    "fileId": "file-uuid-7777",
    "fileName": "作业模板.pptx",
    "label": "下载作业模板"
  }
}
```

---

### 10.5 文件元数据表设计

#### ai_files 表

| 字段名 | 类型 | 约束 | 说明 | 示例值 |
|--------|------|------|------|--------|
| `id` | BIGINT | PRIMARY KEY, AUTO_INCREMENT | 记录 ID | 12345 |
| `file_id` | VARCHAR(100) | UNIQUE, NOT NULL | 文件唯一 ID | "file-uuid-9999" |
| `teacher_id` | VARCHAR(50) | NOT NULL, INDEX | 上传者 ID | "teacher-001" |
| `file_name` | VARCHAR(500) | NOT NULL | 原始文件名 | "exam-data.png" |
| `file_type` | VARCHAR(100) | NOT NULL | MIME 类型 | "image/png" |
| `file_size` | BIGINT | NOT NULL | 文件大小（字节） | 204800 |
| `oss_url` | VARCHAR(1000) | NOT NULL | OSS 存储路径 | "https://oss.../files/..." |
| `purpose` | VARCHAR(50) | NULL | 用途 | "analysis", "lesson_material" |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 上传时间 | "2026-02-04 10:00:00" |

#### 索引设计

| 索引名 | 字段 | 类型 | 目的 |
|--------|------|------|------|
| `PRIMARY` | `id` | PRIMARY KEY | 主键 |
| `idx_file_id` | `file_id` | UNIQUE INDEX | 唯一标识文件 |
| `idx_teacher_created` | `teacher_id`, `created_at` | COMPOSITE INDEX | 查询"我上传的文件" |

---

### 10.6 支持的文件类型

| 文件类型 | MIME Type | 最大大小 | AI 处理能力 |
|----------|-----------|----------|-------------|
| **图片** | image/png, image/jpeg | 10MB | ✅ OCR、视觉分析 |
| **PDF** | application/pdf | 50MB | ✅ 文本提取、分析 |
| **PPT** | application/vnd.ms-powerpoint, application/vnd.openxmlformats-officedocument.presentationml.presentation | 50MB | ⚠️ 只保存引用，不分析 |
| **Word** | application/msword, application/vnd.openxmlformats-officedocument.wordprocessingml.document | 20MB | ⚠️ 只保存引用，不分析 |
| **Excel** | application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | 20MB | ✅ 数据提取、分析 |

---

### 10.7 AI-MCP 文件处理策略

#### 策略 1: 按需下载（Lazy Loading）

**适用场景**: 文件只在 Page 中展示，AI 不需要分析内容

```python
# AI-MCP 不下载文件，只保存 file_id 引用
blueprint = Blueprint(
    uiComposition=UIComposition(
        components=[
            {
                "type": "image",
                "props": {"fileId": "file-uuid-9999"}  // 只保存 ID
            }
        ]
    )
)
```

**优势**:
- ✅ 减少带宽消耗
- ✅ 加快生成速度
- ✅ 文件内容由前端从 Java 后端直接获取

---

#### 策略 2: 主动下载（Eager Loading）

**适用场景**: AI 需要分析文件内容（如 OCR、数据提取）

```python
# AI-MCP 主动下载文件
file_content = await java_client.download_file(
    jwt_token=authorization,
    file_id="file-uuid-9999"
)

# 调用 Vision API 分析图片
ocr_result = await vision_service.extract_text(file_content)

# 将结果用于 Blueprint 生成
blueprint = await planner_agent.generate_blueprint(
    prompt=f"分析成绩：{ocr_result}"
)
```

**优势**:
- ✅ AI 可以深度分析文件内容
- ✅ 支持 OCR、图表识别等高级功能

---

### 10.8 完整示例：用户上传图片后生成分析

#### 步骤 1: 前端上传图片

```typescript
// 1. 上传文件
const formData = new FormData();
formData.append('file', imageFile);
formData.append('purpose', 'analysis');

const uploadResponse = await fetch('/api/studio/teacher/me/files/upload', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${jwt}` },
  body: formData
});

const { fileId } = await uploadResponse.json();
// fileId: "file-uuid-9999"
```

---

#### 步骤 2: 前端调用 AI-MCP

```typescript
// 2. 请求分析（只传 file_id）
const analysisResponse = await fetch('/api/workflow/generate', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${jwt}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    prompt: '分析这张成绩表',
    fileIds: [fileId],  // ⭐ 只传 file_id
    classIds: ['1A']
  })
});
```

---

#### 步骤 3: AI-MCP 处理

```python
@app.post("/api/workflow/generate")
async def generate_workflow(
    request: WorkflowRequest,
    authorization: str = Header(...)
):
    # 1. 获取文件元数据
    file_info = await java_client.get_file(
        jwt_token=authorization,
        file_id=request.fileIds[0]
    )

    # 2. 如果是图片，下载并进行 OCR
    if file_info.fileType.startswith("image/"):
        download_info = await java_client.get_file_download_url(
            jwt_token=authorization,
            file_id=request.fileIds[0]
        )

        # 下载文件内容
        async with httpx.AsyncClient() as client:
            image_response = await client.get(download_info.signedUrl)
            image_data = image_response.content

        # 调用 Vision API 进行 OCR
        ocr_result = await vision_service.extract_text(image_data)

        # 3. 生成 Blueprint（基于 OCR 结果）
        blueprint = await planner_agent.generate_blueprint(
            prompt=f"分析成绩：{ocr_result}",
            context={"classIds": request.classIds}
        )
    else:
        # 非图片文件，只保存引用
        blueprint = await planner_agent.generate_blueprint(
            prompt=request.prompt,
            files=[{"fileId": request.fileIds[0], "type": "reference"}]
        )

    # 4. 执行 Blueprint 生成 Page
    page_result = await executor_agent.execute_blueprint(blueprint)

    # 5. 回写 Java 后端
    java_response = await java_client.create_app(
        jwt_token=authorization,
        data={
            "appName": extract_app_name(request.prompt),
            "blueprint": blueprint.model_dump(),
            "pageContent": page_result.page.model_dump(),
            "classIds": request.classIds
        }
    )

    return java_response
```

---

#### 步骤 4: 前端渲染 Page

```typescript
// 前端获取生成的 Page
const { executionId } = analysisResponse.data;

const pageResponse = await fetch(
  `/api/studio/teacher/me/executions/${executionId}`,
  { headers: { 'Authorization': `Bearer ${jwt}` } }
);

const { pageContentUrl } = await pageResponse.json();

// 下载 Page JSON
const pageData = await fetch(pageContentUrl).then(r => r.json());

// 渲染组件（如果包含图片组件，再次获取签名 URL）
for (const component of pageData.components) {
  if (component.type === 'image' && component.props.fileId) {
    // 获取图片签名 URL
    const imageUrl = await api.getFileDownloadUrl(component.props.fileId);
    renderImage(imageUrl, component.props);
  }
}
```

---

### 10.9 安全性考虑

#### 1. 文件访问权限

**规则**: 只能访问自己上传的文件

```java
// Java 后端检查
if (!file.getTeacherId().equals(teacherId)) {
    throw new ForbiddenException("No access to this file");
}
```

---

#### 2. 签名 URL 有效期

**规则**: 签名 URL 有效期 1 小时，过期后需重新请求

```java
String signedUrl = ossService.generateSignedUrl(
    file.getOssUrl(),
    3600  // 1 小时
);
```

---

#### 3. 文件类型验证

**规则**: 上传时验证 MIME 类型和扩展名

```java
private void validateFile(MultipartFile file) {
    // 检查大小
    if (file.getSize() > 50 * 1024 * 1024) {  // 50MB
        throw new BadRequestException("File too large");
    }

    // 检查类型
    String contentType = file.getContentType();
    if (!ALLOWED_TYPES.contains(contentType)) {
        throw new BadRequestException("File type not allowed");
    }

    // 防止文件名注入
    String fileName = file.getOriginalFilename();
    if (fileName.contains("..") || fileName.contains("/")) {
        throw new BadRequestException("Invalid file name");
    }
}
```

---

### 10.10 实施清单

#### AI-MCP 端

- [ ] **JavaBackendClient 扩展**
  - [ ] 实现 `get_file(jwt_token, file_id)` - 获取文件元数据
  - [ ] 实现 `get_file_download_url(jwt_token, file_id)` - 获取签名 URL
  - [ ] 实现文件下载逻辑（从签名 URL）

- [ ] **文件处理策略**
  - [ ] 实现按需下载（lazy loading）
  - [ ] 实现主动下载（eager loading for OCR/分析）
  - [ ] 集成 Vision API（如需 OCR）

#### Java 后端

- [ ] **文件上传 API**
  - [ ] POST /api/studio/teacher/me/files/upload
  - [ ] 文件类型/大小验证
  - [ ] OSS 上传
  - [ ] 元数据存储

- [ ] **文件查询 API**
  - [ ] GET /api/studio/teacher/me/files/{fileId} - 获取元数据
  - [ ] GET /api/studio/teacher/me/files/{fileId}/download - 获取签名 URL

- [ ] **数据库表**
  - [ ] 创建 `ai_files` 表
  - [ ] 索引优化

---

## 11. 相关文档

- [存储优化方案](./storage-optimization-plan.md) - OSS 存储策略
- [API 分离与权限管理](./api-separation-and-permissions.md) - 版本分离设计
- [Java 后端集成规范](./java-backend-spec.md) - API 端点设计
- [App 架构快速参考](./app-architecture-quickref.md) - 核心概念
