# Phase 2 Quiz 优化验收（第 1 轮）

- 日期: 2026-02-08
- 对应方案: `docs/studio-v1/architecture/07-agent-convergence-plan.md`
- 参考脚本: `scripts/phase1_quiz_convergence_acceptance.py`
- 测试请求: `请出5道一元二次方程选择题，附简短解析。`

## 1. 本轮已落地优化

- Unified quiz direct-tool 路径支持模型覆盖透传。
- 配置 `agent_unified_quiz_model` 现在可直接影响 `generate_quiz_questions` 的真实执行模型。
- 目的：为 Phase 2 的 Qwen / GLM / Claude 实验矩阵提供同一条执行链路，减少“配置生效不一致”误差。

## 2. 多轮结果（每模式 10 轮）

| 模式 | 成功率 | fallback率 | TTFQ P50(ms) | TTFQ P95(ms) |
|---|---:|---:|---:|---:|
| legacy_skill | 100% | 0% | 27567 | 34917 |
| unified_agent | 100% | 0% | 31304 | 36708 |

## 3. 门槛判定

- TTFQ P50 劣化: `+13.6%`（门槛 <= `20%`）
- TTFQ P95 劣化: `+5.1%`（门槛 <= `20%`）
- Unified 成功率: `100%`（门槛 >= `95%`）
- 结论: `PASS`

## 4. 风险与下一步

- 当前主要风险是 P50 仍慢于 legacy，且本轮 P95 也出现劣化。
- 建议下一轮直接按模型矩阵执行：
  - 固定请求集，分别跑 `dashscope/qwen-max`、`zai/glm-*`、`anthropic/claude-*`
  - 保持同一脚本与同一统计口径，比较 P50/P95/成功率/fallback率
