# Agent-First Convergence Work Folder

> 从"多路径并存"收敛到"统一自然语言 + Agent 编排工具"
> Build compile/execute/save-as-app 不在本范围内，见 [`docs/build-runtime/`](../build-runtime/README.md)

---

## 总方案

| 文档 | 路径 | 说明 |
|------|------|------|
| 收敛总方案 | [`07-agent-convergence-plan.md`](../../../docs/studio-v1/architecture/07-agent-convergence-plan.md) | 架构设计、分阶段迁移、验收指标、回退策略 |

---

## 收敛范围

Unified Agent 统一的是 **对话生成能力**：

| 能力 | 收敛前路径 | 收敛后 |
|------|-----------|--------|
| Quiz | Skill Path (`_stream_quiz_generate`) | Agent → `generate_quiz_questions` |
| PPT | Content Create Path | Agent → `propose_pptx_outline` / `generate_pptx` |
| 文稿 | Content Create Path | Agent → `generate_docx` / `render_pdf` |
| 互动网页 | Content Create Path | Agent → `request_interactive_content` |
| 问答 | Chat Path | Agent（无工具调用） |

**不在收敛范围内**：

| 能力 | 说明 | 文档 |
|------|------|------|
| Build compile/execute | 按钮触发的流水线，独立 API | [`docs/build-runtime/`](../build-runtime/README.md) |
| Save as App | Build 资产化，独立模块 | [`docs/build-runtime/`](../build-runtime/README.md) |

---

## Phase 进度总览

| Phase | 目标 | 状态 | 关键结论 |
|-------|------|------|---------|
| Phase 0 | 基线与开关 | DONE | Feature flags 已就绪，指标可观测 |
| Phase 1 | Quiz 收敛到 Agent | PASS | 成功率 100%，P50 劣化 +13.6%（门槛 20%） |
| Phase 2 | 对话生成收敛 + Quiz 优化 | IN PROGRESS | content_create 退场 + Quiz P50 优化 |
| Phase 3 | Router 轻量化 | PLANNED | — |
| Phase 4 | 清理旧路径 | PLANNED | — |

---

## Phase 1 — Quiz 收敛

Quiz 从 Skill Path 迁移到 Unified Agent 工具调用。

| 文档 | 说明 |
|------|------|
| [summary.md](phase1-quiz/summary.md) | 阶段验收总结（代码测试 + 实测） |
| [validation.md](phase1-quiz/validation.md) | 单轮协议兼容性验证 |
| [validation.json](phase1-quiz/validation.json) | 验证原始数据 |
| [acceptance.md](phase1-quiz/acceptance.md) | 多轮验收报告（10轮/模式） |
| [acceptance.json](phase1-quiz/acceptance.json) | 验收原始数据 |

### Phase 1 关键指标

```
legacy_skill:   成功率 100%  TTFQ P50 27567ms  P95 34917ms
unified_agent:  成功率 100%  TTFQ P50 31304ms  P95 36708ms  fallback 0%

P50 劣化 +13.6% | P95 劣化 +5.1% | 门槛 <=20% → PASS
```

---

## Phase 2 — 对话生成收敛 + Quiz 优化

两条并行线：对话 Agent 收敛（content_create 退场、PPT/文稿/互动网页统一）+ Quiz 专项性能优化。

| 文档 | 说明 |
|------|------|
| [execution-plan.md](phase2/execution-plan.md) | Agent 对话收敛执行说明（content_create 退场、统一工具、事件协议） |
| [clarify-fix-plan.md](phase2/clarify-fix-plan.md) | Clarify 连续对话问题修复方案（结构化输出 + 连续链路稳定性） |
| [quiz-optimization-input.md](phase2/quiz-optimization-input.md) | Quiz 专项优化输入（基线、模型矩阵、验收门槛） |
| [quiz-optimization-acceptance.md](phase2/quiz-optimization-acceptance.md) | Quiz 优化第 1 轮验收 |

### Phase 2 待产出

- [ ] `quiz-optimization-acceptance-r2.md` — Quiz 模型矩阵实验结果
- [x] 跨场景 E2E 测试报告（quiz -> ppt -> 互动网页）
  - 报告：`docs/convergence/phase2/cross-intent-e2e-report.md`
  - 原始数据：`docs/testing/phase2-cross-intent-switch-live.json`
  - 快速查看：`docs/testing/phase2-cross-intent-switch-live.md`
- [ ] Clarify 连续对话稳定性修复与复测
  - 方案：`docs/convergence/phase2/clarify-fix-plan.md`
  - 待补实测：`docs/testing/phase2-memory-chain-clarify-live.json`

---

## 关键配置开关

```python
# config/settings.py
agent_unified_enabled: bool = False           # 总开关
agent_unified_quiz_enabled: bool = False      # Quiz 能力开关
agent_unified_quiz_model: str = ""            # Quiz 模型覆盖
agent_unified_quiz_grace_ms: int = 4000       # Quiz 宽限时间
```

---

## 改造涉及的核心文件

| 文件 | 改造内容 |
|------|---------|
| `agents/router.py` | Light Router 模式，减少业务硬分流 |
| `api/conversation.py` | 统一 Agent 入口，旧 content_create/quiz 路径降级为 fallback |
| `agents/teacher_agent.py` | 减少场景硬编码，策略型提示 |
| `config/settings.py` | 收敛相关 Feature flags |

---

## 验收脚本

| 脚本 | 用途 |
|------|------|
| `scripts/phase1_quiz_convergence_validation.py` | 单轮协议验证 |
| `scripts/phase1_quiz_convergence_acceptance.py` | 多轮统计验收（P50/P95/成功率） |
