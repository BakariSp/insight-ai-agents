# Phase 1 Quiz 收敛阶段验收（代码 + 实测）

- 日期: 2026-02-08
- 对应方案: `docs/studio-v1/architecture/07-agent-convergence-plan.md`
- 验收范围: Phase 1（Quiz 收敛到 Unified Agent，保留旧 Skill fallback）

## 1. 代码测试（必须项）

执行命令（`cmd`）:

```bash
python -m pytest tests\test_router.py -q
python -m pytest tests\test_agent_path.py -q
python -m pytest tests\test_conversation_stream.py -q
```

结果:

- `tests/test_router.py`: 23 passed
- `tests/test_agent_path.py`: 51 passed
- `tests/test_conversation_stream.py`: 18 passed

覆盖点:

- Router quiz 关键词逻辑已从“强改 intent”改为“仅添加 tool hint”
- Unified quiz 工具已注册并可被 Agent Path 使用
- quiz 工具输出可映射为前端事件:
  - `data-quiz-question`
  - `data-quiz-complete`

## 2. 实际输出测试（必须项）

执行脚本:

```bash
python scripts\phase1_quiz_convergence_validation.py
```

产物:

- `docs/testing/phase1-quiz-convergence-validation.md`
- `docs/testing/phase1-quiz-convergence-validation.json`

测试请求:

- `请出5道一元二次方程选择题，附简短解析。`

对比结果（旧路径 vs 新路径）:

- `legacy_skill`
  - 首题时延: `31539ms`
  - 总时长: `31539ms`
  - 题目数: `5`
  - 结构质量通过率: `100%`
- `unified_agent`
  - 首题时延: `43235ms`
  - 总时长: `43235ms`
  - 题目数: `5`
  - 结构质量通过率: `100%`

## 3. 工具调用与前端可用性

前端协议兼容性:

- 两种模式都稳定输出:
  - `data-action`
  - `data-quiz-question`
  - `data-quiz-complete`
- 前端可继续按既有事件消费，不需要改协议。

Unified 调用情况:

- 该次实测中未观测到 `generate_quiz_questions` 的工具调用事件。
- 日志显示:
  - `UnifiedQuiz No quiz artifact from unified agent; fallback to legacy quiz skill path.`
- 说明当前“Unified 优先”可运行，但在本次请求下实际走了 fallback。

## 4. 门槛判定（Phase 1 Go/No-Go）

方案门槛（文档定义）:

- Quiz 成功率不低于基线
- 首题时延劣化 <= 10%

实测结论:

- Quiz 成功率: `达标`（两边都成功）
- 首题时延: `不达标`（`+37.1%`）

最终判定:

- `NEEDS_REVIEW`（暂不建议按 Phase 1 完成态进入下一阶段）

## 5. 后续修正建议

1. 增加 Unified quiz 的“早退 fallback”机制（例如在限定时间内未产出 quiz artifact 即回退）。
2. 在 quiz 场景下对 Agent 工具集做最小化约束（优先仅保留 `generate_quiz_questions`）。
3. 增加“Unified 真正命中率”指标（避免成功率被 fallback 掩盖）。
