# Phase 2.x Quiz Optimization Input (based on Phase 1 acceptance)

## 0. 文档定位

本文是 **Quiz 专项** 的 Phase 2 优化输入。  
若你要看 `07-agent-convergence-plan` 的总体 Phase 2（build 收敛、content_create 退场、PPT/文稿/互动网页统一接管），请看：

- `docs/convergence/phase2/execution-plan.md`

## 1. 目标范围

Phase 2 目标是继续优化 Unified 入口质量与性能，在保持现有架构前提下：

- 继续提升 Unified 端到端速度（重点看 P50）
- 保持或提升稳定性（重点看 P95 和成功率）
- 维持前端协议不变（`data-quiz-question` / `data-quiz-complete`）

不在本阶段做：

- 协议变更
- 大规模架构重写
- 非 quiz 场景的统一化

## 2. 当前事实基线（2026-02-08）

来源：

- `docs/convergence/phase1-quiz/acceptance.md`
- `docs/convergence/phase1-quiz/acceptance.json`

多轮验收（每模式 10 轮，阶段1基线）：

- `legacy_skill`
  - 成功率：`100%`
  - TTFQ P50：`24678ms`
  - TTFQ P95：`34992ms`
- `unified_agent`
  - 成功率：`100%`
  - fallback率：`0%`
  - TTFQ P50：`26677ms`（相对 legacy `+8.1%`）
  - TTFQ P95：`28662ms`（相对 legacy `-18.1%`）

结论：

- 阶段1在当前门槛（时延劣化 <= 20%，成功率 >= 95%）下已 `PASS`
- Unified 尾部稳定性优于 legacy（P95 更低）
- Unified 典型时延仍有优化空间（P50 略慢）

补充：2026-02-08 最新复测（优化代码落地后）：

- `legacy_skill`: 成功率 `100%`，TTFQ P50 `27567ms`，TTFQ P95 `34917ms`
- `unified_agent`: 成功率 `100%`，fallback率 `0%`，TTFQ P50 `31304ms`，TTFQ P95 `36708ms`
- 结论：`PASS`（P50 劣化 `+13.6%`，P95 劣化 `+5.1%`，均在 20% 门槛内）

## 3. 已落地的关键机制（供 Phase 2 继承）

- Unified quiz 入口已支持确定性执行（默认 `force_tool=true`）
- Quiz 工具统一为 `generate_quiz_questions`
- 仍保留模型编排与最终 fallback 作为安全网
- 支持 Unified quiz 模型覆盖配置（可指定如 `zai/glm-*`）
- Unified direct-tool 路径已支持模型覆盖透传（`agent_unified_quiz_model` 可直接作用于实际出题调用，而非仅备用链）

关键配置（`config/settings.py`）：

- `agent_unified_enabled`
- `agent_unified_quiz_enabled`
- `agent_unified_quiz_force_tool`
- `agent_unified_quiz_model`
- `agent_unified_quiz_grace_ms`

## 4. Phase 2 优先优化项（建议顺序）

1. 减少 quiz 生成方差（降低 P95 波动）
2. 降低 P50（目标先追平 legacy，再争取优于 legacy）
3. 增强结构完整性（确保题量、题型、解析稳定）
4. 模型 AB 对比（Qwen / GLM / Claude）在统一口径下评估

## 5. 模型实验矩阵（建议）

固定请求集（至少 20 条，覆盖中英、不同题型）：

- 单科单题型（选择题）
- 混合题型（选择/填空/判断）
- 含约束（难度、年级、知识点）

每模型至少 20 轮，统计：

- 成功率
- TTFQ P50 / P95
- Total P50 / P95
- 平均题目数
- 结构有效率（字段完整、题型一致）

候选模型链：

- `dashscope/qwen-max`（当前基线）
- `zai/glm-*`（工具调用对照）
- `anthropic/claude-*`（质量对照，关注延迟成本）

## 6. Phase 2 验收建议门槛

建议把门槛拆成“硬门槛 + 目标门槛”：

- 硬门槛：
  - 成功率 >= `99%`
  - TTFQ P95 不劣于 Phase 1 基线 + `10%`
- 目标门槛：
  - TTFQ P50 <= legacy 基线（即 <= `24678ms`）
  - fallback率持续接近 `0%`

## 7. 执行与记录规范

每轮优化完成后必须同步：

- 代码测试结果（pytest）
- 多轮验收报告（Markdown + JSON）
- 变更摘要（改了哪些配置、提示词或执行策略）

推荐沿用脚本：

- `scripts/phase1_quiz_convergence_acceptance.py`

报告输出路径：

- `docs/convergence/phase1-quiz/acceptance.md`
- `docs/convergence/phase1-quiz/acceptance.json`

若进入 Phase 2，可按相同格式新增：

- `docs/convergence/phase2/quiz-optimization-acceptance.md`
- `docs/convergence/phase2/quiz-optimization-acceptance.json`

## 8. Scope Note

- This doc is Quiz-only optimization input (Phase 2.x).
- Phase 2 common capability convergence and Save as App implementation are maintained in `insight-ai-agent/docs/convergence/phase2/execution-plan.md`.
- Keep this file focused on Quiz metrics, experiments, and acceptance gates.

