# Agent-First Convergence Work Folder

> 从"多路径并存"收敛到"AI 原生 Tool Calling 自主编排"
> Build compile/execute/save-as-app 不在本范围内，见 [`docs/build-runtime/`](../build-runtime/README.md)

---

## 总方案

| 文档 | 路径 | 说明 |
|------|------|------|
| 收敛总方案 | [`07-agent-convergence-plan.md`](../../../docs/studio-v1/architecture/07-agent-convergence-plan.md) | 架构设计、分阶段迁移、验收指标、回退策略 |
| **AI 原生重构方案** | [`2026-02-09-ai-native-rewrite.md`](../plans/2026-02-09-ai-native-rewrite.md) | **Phase 3+4 合并执行** — 完整实施计划 |

---

## Phase 进度总览

| Phase | 目标 | 状态 | 关键结论 |
|-------|------|------|---------|
| Phase 0 | 基线与开关 | ✅ DONE | Feature flags 已就绪，指标可观测 |
| Phase 1 | Quiz 收敛到 Agent | ✅ PASS | 成功率 100%，P50 劣化 +13.6%（门槛 20%） |
| Phase 2 | 对话生成收敛 + Quiz 优化 | ✅ DONE | content_create 退场 + Quiz P50 优化 |
| Phase 3+4 | **AI 原生重构** | 🔄 IN PROGRESS | 合并执行 — 详见 AI 原生重构方案 |

> **Phase 3+4 合并说明**: 原 Phase 3（Router 轻量化）和 Phase 4（清理旧路径）被 AI 原生重构方案取代。
> 新方案直接删除 Router、Executor、PatchAgent 等全部旧编排代码，用 NativeAgent + LLM Tool Calling 替代。
> 详见 `docs/plans/2026-02-09-ai-native-rewrite.md`

---

## AI 原生重构 = Phase 3+4

原 Convergence Phase 3-4 的目标已被 AI 原生重构方案吸收：

| 原 Phase | 原目标 | AI 原生重构对应 |
|----------|--------|----------------|
| Phase 3 | Router 轻量化 | Step 1-2: 直接删除 Router，LLM 自主选 tool |
| Phase 4 | 清理旧路径 | Step 3-4: 一次性删除全部旧编排代码 |

### 收敛范围

NativeAgent 统一的是 **所有对话生成能力**：

| 能力 | 收敛前路径 | 收敛后 |
|------|-----------|--------|
| Quiz | Skill Path (`_stream_quiz_generate`) | NativeAgent → `generate_quiz_questions` tool |
| PPT | Content Create Path | NativeAgent → `propose_pptx_outline` / `generate_pptx` tool |
| 文稿 | Content Create Path | NativeAgent → `generate_docx` / `render_pdf` tool |
| 互动网页 | Content Create Path | NativeAgent → `request_interactive_content` tool |
| 问答 | Chat Path | NativeAgent → 直接回复或调 `search_teacher_documents` |
| 数据分析 | Blueprint 三阶段流水线 | NativeAgent → `build_report_page` tool |
| 修改 | PatchAgent 正则匹配 | NativeAgent → `get_artifact` → `patch_artifact` tool |
| 实体解析 | EntityResolver 状态机 | NativeAgent → `resolve_entity` tool |
| 澄清 | Confidence 阈值 + clarify handler | NativeAgent → `ask_clarification` tool |

---

## Phase 1 — Quiz 收敛 ✅ PASS

Quiz 从 Skill Path 迁移到 Unified Agent 工具调用。

| 文档 | 说明 |
|------|------|
| [summary.md](phase1-quiz/summary.md) | 阶段验收总结（代码测试 + 实测） |
| [validation.md](phase1-quiz/validation.md) | 单轮协议兼容性验证 |
| [acceptance.md](phase1-quiz/acceptance.md) | 多轮验收报告（10轮/模式） |

### Phase 1 关键指标

```
legacy_skill:   成功率 100%  TTFQ P50 27567ms  P95 34917ms
unified_agent:  成功率 100%  TTFQ P50 31304ms  P95 36708ms  fallback 0%

P50 劣化 +13.6% | P95 劣化 +5.1% | 门槛 <=20% → PASS
```

---

## Phase 2 — 对话生成收敛 ✅ DONE

| 文档 | 说明 |
|------|------|
| [execution-plan.md](phase2/execution-plan.md) | Agent 对话收敛执行说明 |
| [clarify-fix-plan.md](phase2/clarify-fix-plan.md) | Clarify 连续对话问题修复方案 |
| [quiz-optimization-input.md](phase2/quiz-optimization-input.md) | Quiz 专项优化输入 |
| [quiz-optimization-acceptance.md](phase2/quiz-optimization-acceptance.md) | Quiz 优化验收 |

---

## 旧配置开关（AI 原生重构后删除）

```python
# config/settings.py — 以下 flags 将在 Step 4 清理中删除
agent_unified_enabled: bool = False           # → 被 NATIVE_AGENT_ENABLED 取代
agent_unified_quiz_enabled: bool = False      # → 删除
agent_unified_quiz_model: str = ""            # → 删除
agent_unified_quiz_grace_ms: int = 4000       # → 删除
```

新开关: `NATIVE_AGENT_ENABLED=true/false`（在 `conversation.py` 入口处，非配置中间件）

---

## 验收脚本

| 脚本 | 用途 |
|------|------|
| `scripts/phase1_quiz_convergence_validation.py` | Phase 1 单轮协议验证 |
| `scripts/phase1_quiz_convergence_acceptance.py` | Phase 1 多轮统计验收 |
| `scripts/native_smoke_test.py` | AI 原生重构 最小场景验证 |
| `scripts/native_full_regression.py` | AI 原生重构 S1-S11 全场景回归 |
| `scripts/golden_conversation_runner.py` | AI 原生重构 行为级回归 |
