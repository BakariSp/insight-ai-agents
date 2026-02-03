# Java Backend Integration Test Report

> Test Date: 2026-02-03
> Teacher ID: `2fe869fb-4a2d-4aa1-a173-c263235dc62b` (userId: 3)

## 1. Authentication (DIFY Internal Account)

### Login Credentials

| Field | Value |
|-------|-------|
| Endpoint | `POST /api/auth/login` |
| Account | `dify@nomail` |
| Password | `dify-insightai` |
| Role | `DIFY` |
| SchoolId | `1` |

### Login Request

```json
{
  "schoolId": 1,
  "account": "dify@nomail",
  "password": "dify-insightai",
  "role": "DIFY"
}
```

### Login Response

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiJ9...",
    "expiresIn": 7200,
    "user": {
      "id": 46,
      "uid": "aced47cd-8534-492b-9ceb-4ea488ac2d8e",
      "username": "dify-internal",
      "email": "dify@nomail",
      "role": "DIFY"
    }
  }
}
```

### Token Refresh

| Field | Value |
|-------|-------|
| Endpoint | `POST /api/auth/refresh` |
| Method | Cookie: `refresh_token={token}` |
| Response | Same as login (new tokens) |

**Note**: Access token expires in 2 hours (7200s), refresh token expires in 7 days.

---

## 2. API Endpoints Tested

### 2.1 List Teacher Classes

**Endpoint**: `GET /api/dify/teacher/{teacherId}/classes/me`

**Response** (5 classes found):

| Class ID (uid) | Name | Subject | Grade | Students |
|----------------|------|---------|-------|----------|
| `d7aa27aa-cfc3-4497-839e-cdde75e99989` | 高一数学班 | 数学 | 高一 | 5 |
| `1e4fd110-0d58-4daa-a048-ee691fc7bef4` | 高一英语班 | 英语 | 高一 | 5 |
| `b8765929-ff20-4a17-9a44-f861afb1ab71` | 高三语文班 | 语文 | 高三 | 3 |
| `b8b3689a-440f-4059-949c-b2255c30d1d4` | 123 | physics | P4 | 1 |
| `abfbe9b3-ac81-466e-917a-e86c140a42c4` | 456 | chinese | P1 | 0 |

### 2.2 Get Class Detail

**Endpoint**: `GET /api/dify/teacher/{teacherId}/classes/{classId}`

**Sample Response** (高一数学班):

```json
{
  "id": 1,
  "uid": "d7aa27aa-cfc3-4497-839e-cdde75e99989",
  "name": "高一数学班",
  "subject": "数学",
  "grade": "高一",
  "description": "高中数学基础课程，涵盖函数、方程、不等式等核心概念，为后续学习打下坚实基础。",
  "teacherId": 3,
  "studentCount": 5,
  "assignmentCount": 0
}
```

### 2.3 List Class Assignments

**Endpoint**: `GET /api/dify/teacher/{teacherId}/classes/{classId}/assignments`

**Response** (49 total, page 1):

| Assignment ID | Title | Due Date | Status | Submissions |
|---------------|-------|----------|--------|-------------|
| `assign-b72bfd1f-...` | 未命名 | 2026-02-03 | DRAFT | - |
| `assign-b32b4fec-...` | 测试一 | 2026-01-30 | GRADED | 0/5 |
| `assign-35a85133-...` | 测试作业 | 2026-01-16 | GRADED | 2/5 |
| ... | ... | ... | ... | ... |

### 2.4 Get Assignment Submissions

**Endpoint**: `GET /api/dify/teacher/{teacherId}/submissions/assignments/{assignmentId}`

**Sample Response** (测试作业 - 5 submissions):

| Student | Name | Score | Status | Answers |
|---------|------|-------|--------|---------|
| `099ba4ae-...` | student1 | 5.0 | GRADED | 8 questions |
| `8f1021ea-...` | student2 | 22.0 | GRADED | 8 questions |
| `e630e711-...` | student3 | - | NOT_SUBMITTED | - |
| `464d83c2-...` | student4 | - | NOT_SUBMITTED | - |
| `dae4d1ac-...` | student5 | - | NOT_SUBMITTED | - |

**Detailed Submission Data** (student2 - score 22/40):

```json
{
  "uid": "8f1021ea-ffd2-4423-97d5-65ae94f12ada",
  "studentName": "student2",
  "score": 22.0,
  "feedback": "AI批改反馈：整体表现一般，得分率51%。选择题表现稳定，但复杂应用题存在失误。",
  "answers": [
    {
      "questionId": 10219,
      "questionText": "求圖中陰影區域的面積。",
      "studentAnswer": "D",
      "correctAnswer": "D",
      "isCorrect": true,
      "pointsEarned": 5.0,
      "totalPoints": 5,
      "questionType": "MULTIPLE_CHOICE"
    }
    // ... 7 more answers
  ]
}
```

### 2.5 Get Student Grades

**Endpoint**: `GET /api/dify/teacher/{teacherId}/submissions/students/{studentId}`

**Note**: This endpoint returned `400 - 学生不存在` for the submission UID. The student grades API may require numeric `studentId` (e.g., `1`, `2`) instead of UUID.

---

## 3. Data Model Mapping

### Java Response → Internal Model

| Java Field | Internal Field | Notes |
|------------|----------------|-------|
| `uid` | `class_id` / `student_id` | Primary identifier |
| `name` | `name` | Direct mapping |
| `studentCount` | `student_count` | camelCase → snake_case |
| `assignmentCount` | `assignment_count` | camelCase → snake_case |
| `totalPoints` | `max_score` | Renamed for clarity |
| `status` | `status` | Direct mapping |

### Response Wrapper

All Java API responses use `Result<T>` wrapper:

```json
{
  "code": 200,
  "message": "获取成功",
  "data": { ... },  // Actual payload
  "timestamp": "2026-02-03T08:30:16Z"
}
```

---

## 4. Test Results Summary

| Test | Status | Notes |
|------|--------|-------|
| List Classes | ✅ Pass | 5 classes returned |
| Class Detail | ✅ Pass | Full detail with description |
| List Assignments | ✅ Pass | 49 assignments, paginated |
| Assignment Submissions | ✅ Pass | 5 submissions with answers |
| Student Grades | ⚠️ Partial | Needs numeric studentId |

---

## 5. Configuration Reference

### .env Settings

```env
SPRING_BOOT_BASE_URL=https://api.insightai.hk
SPRING_BOOT_API_PREFIX=/api
SPRING_BOOT_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiJ9...
SPRING_BOOT_REFRESH_TOKEN=eyJhbGciOiJIUzI1NiJ9...
SPRING_BOOT_TIMEOUT=15
USE_MOCK_DATA=false
```

### Token Expiration

- Access Token: 2 hours (7200 seconds)
- Refresh Token: 7 days

### Auto-Refresh Flow

When access token expires:
1. Call `POST /api/auth/refresh` with refresh_token cookie
2. Update .env or call `java_client.update_tokens()`
3. If refresh token also expired, re-login with DIFY credentials

---

## 6. Files Generated

- `docs/testing/java_backend_responses.json` - Main test results
- `docs/testing/java_backend_detailed.json` - Detailed submission data
- `scripts/test_java_backend.py` - Test script
- `scripts/refresh_token.py` - Token refresh utility
