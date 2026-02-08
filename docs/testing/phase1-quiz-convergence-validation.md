# Phase 1 Quiz 收敛验收报告

- 生成时间: 2026-02-08 21:43:41
- 测试请求: `请出5道一元二次方程选择题，附简短解析。`

## 结果总览

| 模式 | 成功 | 首题时延(ms) | 总时长(ms) | 题目数 | 结构质量通过率 | action | orchestrator |
|---|---:|---:|---:|---:|---:|---|---|
| legacy_skill | Y | 31539 | 31539 | 5 | 100% | quiz_generate |  |
| unified_agent | Y | 43235 | 43235 | 5 | 100% | quiz_generate |  |

## 前端协议兼容性

### legacy_skill
- 事件: `data-action, data-conversation, data-quiz-complete, data-quiz-question, finish, finish-step, reasoning-delta, reasoning-end, reasoning-start, start, start-step, text-delta, text-end, text-start`
- 工具调用: `(none)`
- 错误: `(none)`

### unified_agent
- 事件: `data-action, data-conversation, data-quiz-complete, data-quiz-question, finish, finish-step, reasoning-delta, reasoning-end, reasoning-start, start, start-step, text-delta, text-end, text-start`
- 工具调用: `(none)`
- 错误: `(none)`

## 阶段1门槛判断

- 首题时延变化: `+37.1%`（门槛: 劣化 <= 10%）
- Quiz 成功率: `legacy=True, unified=True`
- 结论: `NEEDS_REVIEW`
