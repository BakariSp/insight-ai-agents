# /update-docs — 项目文档自动更新

你是一个文档维护专家。你的任务是根据项目当前代码和 git 状态，更新 `docs/` 下的多文件文档体系，确保文档始终反映项目的真实现状。

## 文档结构

```
docs/
├── README.md                      # 导航首页 + 项目概览
├── architecture/
│   ├── overview.md                # 系统架构、项目结构、核心模块
│   ├── agents.md                  # 多 Agent 设计
│   └── blueprint-model.md         # Blueprint 数据模型
├── api/
│   ├── current-api.md             # 当前 API 端点
│   ├── target-api.md              # 目标 API 端点
│   └── sse-protocol.md            # SSE 协议、Block 格式
├── guides/
│   ├── getting-started.md         # 快速开始
│   ├── adding-skills.md           # 添加技能
│   └── environment.md             # 环境变量
├── integration/
│   ├── frontend-integration.md    # 前端集成
│   └── java-backend.md            # Java 后端对接
├── tech-stack.md                  # 技术栈
├── roadmap.md                     # 实施路线图
└── changelog.md                   # 变更日志
```

## 执行步骤

### 1. 收集当前状态

执行以下操作收集项目信息:

- **Git 状态**: `git status`, `git log --oneline -20` 了解最近变更
- **Git Diff**: `git diff --stat` 了解未提交的改动
- **项目结构**: 扫描目录树，了解文件组织
- **依赖**: 读取 `requirements.txt` 了解技术栈变化
- **代码变更**: 读取所有有改动的文件，理解新增/修改的功能
- **测试**: 读取测试文件，了解测试覆盖情况
- **配置**: 读取 `.env.example` 和 `config.py`，了解配置变化

### 2. 分析变更影响并更新对应文件

对比当前文档内容和实际代码，按变更类型更新对应文件:

| 变更类型 | 更新文件 |
|---------|---------|
| 新增/删除文件或模块 | `docs/architecture/overview.md` (项目结构) |
| 新增/修改 API 端点 | `docs/api/current-api.md` 或 `docs/api/target-api.md` |
| 新增/修改技能或工具 | `docs/guides/adding-skills.md` |
| 路线图进度变化 | `docs/roadmap.md` (`- [ ]` → `- [x]`) |
| 依赖增删 | `docs/tech-stack.md` |
| 架构设计调整 | `docs/architecture/` 下对应文件 |
| Agent 设计变化 | `docs/architecture/agents.md` |
| Blueprint 模型变化 | `docs/architecture/blueprint-model.md` |
| SSE/Block 格式变化 | `docs/api/sse-protocol.md` |
| 前端集成变化 | `docs/integration/frontend-integration.md` |
| Java 对接变化 | `docs/integration/java-backend.md` |
| 环境变量变化 | `docs/guides/environment.md` |

### 3. 必须更新的文件

无论什么变更，以下文件**始终需要检查**:

1. **`docs/README.md`**: 更新"当前阶段"和核心目标状态表
2. **`docs/roadmap.md`**: 更新路线图 checkbox
3. **`docs/changelog.md`**: 在最前面（`---` 分隔线之后）追加本次变更条目

### 4. 格式要求

- 保持中文为主的写作风格
- 保持现有的 markdown 结构
- 代码块保持原格式
- 表格对齐
- 变更日志格式: `## YYYY-MM-DD — 简短标题`

### 5. 输出摘要

更新完成后，输出:
```
文档更新摘要
━━━━━━━━━━━━━━━
更新日期: YYYY-MM-DD
修改文件: file1.md, file2.md, ...
主要变更:
  - ...
  - ...
路线图进度: Phase X — XX%
```

## 重要提示

- **只修改文档文件**，不要修改任何代码
- **基于事实**，只记录已经发生的变更，不要预测未来
- **保持简洁**，变更日志每条不超过一行
- 如果没有实质性变化，告知用户"文档已是最新，无需更新"
