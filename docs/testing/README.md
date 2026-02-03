# 测试报告与用例记录

> 每个开发阶段的测试报告（pytest 结果）、Live 测试日志（真实 LLM 调用）和功能用例（Use Cases）集中存放于此目录。

---

## 目录结构

```
docs/testing/
├── README.md                          # 本文件 — 测试文档导航
├── phase4-test-report.md              # Phase 4 — 统一会话网关 测试报告
├── phase4-conversation-log.md         # Phase 4 — Live 对话日志 (7 场景)
├── phase4.5-test-report.md            # Phase 4.5 — 健壮性增强 测试报告 + Use Cases
├── phase4.5-conversation-log.md       # Phase 4.5 — Live 对话日志 (15 场景)
└── (后续 Phase 按同样格式添加)
```

---

## 各阶段测试概览

| Phase | 阶段名称 | 测试总数 | 新增测试 | 测试报告 | Live 日志 | 关键 Use Cases |
|-------|---------|---------|---------|---------|----------|---------------|
| 4 | 统一会话网关 | 151 | 59 | [报告](phase4-test-report.md) | [日志](phase4-conversation-log.md) | 7 种 action 路由、置信度边界、闭环流程 |
| 4.5 | 健壮性增强 | 222→230 | 71→79 | [报告](phase4.5-test-report.md) | [日志](phase4.5-conversation-log.md) | 实体解析 12 种场景、多轮交互流程、错误拦截 |
| 5 | Java 后端对接 | 238 | 8 | — | — | Adapter 映射、重试/熔断降级、mock fallback |
| 6 | 前端集成 + SSE 升级 + Patch | 320 | 82 | — | — | SSE Block 事件、Per-Block AI、Patch 机制 |
| Live | 上线前真实 API 测试 | 10 | 10 | [报告](live-integration-test-report.md) | [结果](live-integration-results.json) | 真实 LLM 调用、Router/Blueprint/Page 全链路、Java 后端 E2E |

---

## 文档规范

每个阶段应包含以下文件（按需）:

### 1. 测试报告 (`phaseX-test-report.md`)

记录 pytest 自动化测试结果:

- **总体概览**: 测试总数、通过/失败、运行环境
- **测试模块清单**: 各测试文件的测试数和覆盖范围
- **各模块测试详情**: 每条测试的输入/预期/结果
- **Use Case Examples**: 典型功能用例的完整交互流程说明
- **数据模型示例**: 关键 JSON 请求/响应样本
- **回归测试结果**: 确认旧功能未受影响

### 2. Live 对话日志 (`phaseX-conversation-log.md`)

记录真实 LLM 调用的端到端测试:

- **请求/响应**: 完整的 HTTP 请求体和响应体
- **耗时**: 每次调用的响应时间
- **场景分类**: 按功能模块分组 (如 A.班级解析 / B.学生解析 / C.多轮交互)
- **汇总表**: 所有测试场景的结果一览

### 3. 命名约定

```
docs/testing/phaseX-test-report.md          # pytest 测试报告
docs/testing/phaseX-conversation-log.md     # Live 对话日志
docs/testing/phaseX.Y-test-report.md        # 子阶段测试报告
docs/testing/phaseX.Y-conversation-log.md   # 子阶段 Live 日志
```

---

## 功能用例索引 (Use Cases)

### Phase 4 — 统一会话网关

| # | 场景 | Action | 描述 |
|---|------|--------|------|
| 1 | 闲聊 "你好" | chat_smalltalk | 友好回复 + 功能引导 |
| 2 | QA "KPI是什么" | chat_qa | 教育领域知识问答 |
| 3 | 模糊请求 "分析英语表现" | clarify | 反问 → 班级选项列表 |
| 4 | 明确请求 "分析 Form 1A 英语成绩" | build_workflow | Blueprint 生成 |
| 5 | 追问 "哪些学生需要关注？" | chat | 基于页面数据回复 |
| 6 | 微调 "只显示不及格学生" | refine | 新 Blueprint |
| 7 | 重建 "加语法分析模块" | rebuild | 全新 Blueprint |

### Phase 4.5 — 实体解析与健壮性

| # | 场景 | Action | 描述 |
|---|------|--------|------|
| 1 | 单班精确匹配 "Form 1A" | build_workflow | 精确解析 → 自动生成 |
| 2 | 中文别名 "1A班" / "F1A" | build_workflow | 别名匹配 (confidence=1.0) |
| 3 | 多班对比 "1A 和 1B" | build_workflow | 多班自动解析 |
| 4 | 年级展开 "Form 1 全年级" | build_workflow | 年级下所有班级展开 |
| 5 | 班级+学生 "1A 班学生 Wong Ka Ho" | build_workflow | 联合解析 class + student |
| 6 | 学生+已有 context "学生 Li Mei" | build_workflow | 依赖 context.classId 解析 |
| 7 | 缺班级上下文 "学生 Wong Ka Ho" | clarify | missing_context → 班级选项 |
| 8 | 作业解析 "1A 班 Unit 5 Test" | build_workflow | 联合解析 class + assignment |
| 9 | 不存在班级 "2C班" | — | 优雅降级 (scope=none) |
| 10 | 歧义匹配 "F1" | clarify | 多模糊结果 → 选项确认 |
| 11 | context 已有 classId | build_workflow | 跳过解析 → 直接 build |
| 12 | 英文关键词 "student Chan Tai Man" | build_workflow | 英文触发学生解析 |

### Phase 5 — Java 后端对接

| # | 场景 | 描述 |
|---|------|------|
| 1 | Java API 正常调用 | adapter → java_client → 真实数据 |
| 2 | Java 500 错误 | 重试 3 次 → mock fallback |
| 3 | Java 超时 | 指数退避 → 熔断 → mock fallback |
| 4 | 连续失败触发熔断 | 5 次失败 → OPEN → 快速 mock |
| 5 | 熔断恢复 | HALF_OPEN 探测 → CLOSED |
| 6 | USE_MOCK_DATA=true | 配置开关直接使用 mock |

### Phase 6 — 前端集成 + SSE 升级 + Patch ✅ 已完成

| # | 场景 | 描述 | 状态 |
|---|------|------|------|
| 1 | SSE 事件模型序列化 | BlockStartEvent / SlotDeltaEvent / BlockCompleteEvent camelCase 输出 | ✅ |
| 2 | Block 事件流 | BLOCK_START → SLOT_DELTA → BLOCK_COMPLETE 顺序 | ✅ |
| 3 | Per-Block AI 生成 | 各 component_type 独立 LLM 生成 | ✅ |
| 4 | Patch Layout | refine "改颜色" → 无 LLM 调用 | ✅ |
| 5 | Patch Compose | refine "缩短分析" → 只重生成 AI blocks | ✅ |
| 6 | E2E 全生命周期 | prompt → Blueprint → BLOCK 事件 → Patch → 降级 | ✅ |

### Live Integration — 上线前真实 API 测试

| # | 场景 | 描述 | 结果 |
|---|------|------|------|
| A1 | Router 闲聊分类 | "你好" → chat_smalltalk (confidence=0.9) | ✅ 1.7s |
| A2 | Router 构建分类 | "分析高一数学班的期末考试成绩" → build_workflow (0.85) | ✅ 2.3s |
| A3 | Router 澄清分类 | "分析一下英语表现" → clarify (0.5) + 反问 | ✅ 2.6s |
| B1 | Blueprint 生成 (中文) | 完整三层结构生成 | ✅ 25.3s |
| B2 | Blueprint 生成 (英文) | 多语言支持验证 | ✅ 24.8s |
| C1 | Conversation 对话 | 自然语言对话响应 | ✅ 6.0s |
| C2 | Conversation 构建 | 实体解析 → clarify 流程 | ✅ 3.1s |
| D1 | 完整页面生成 | Blueprint → SSE 三阶段 → Page 输出 | ✅ 33.1s |
| D2 | 端到端完整流程 | Conversation → Blueprint → Page (需手动选择) | SKIP |
| **D3** | **关键链路 E2E (Java)** | **真实后端: 高一英语班'测试一' → 完整页面生成** | **✅ 23.4s** |
