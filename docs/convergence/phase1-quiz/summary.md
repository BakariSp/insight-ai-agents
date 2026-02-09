# Phase 1 Quiz 收敛阶段验收（代码 + 实测）

- 日期: 2026-02-08
- 对应方案: `docs/studio-v1/architecture/07-agent-convergence-plan.md`
- 验收范围: Phase 1（Quiz 收敛到 Unified 入口）
- 当前验收口径: 只看自然语言出题端到端 `速度 + 成功率`

## 1. 代码测试

执行命令（`cmd`）:

```bash
python -m pytest tests\test_router.py -q
python -m pytest tests\test_agent_path.py -q
python -m pytest tests\test_conversation_stream.py -q
```

结果:

- `tests/test_router.py`: 23 passed
- `tests/test_agent_path.py`: 51 passed
- `tests/test_conversation_stream.py`: 19 passed

## 2. 实测输出

执行脚本:

```bash
python scripts\phase1_quiz_convergence_validation.py
```

产物:

- `docs/convergence/phase1-quiz/validation.md`
- `docs/convergence/phase1-quiz/validation.json`

测试请求:

- `请出5道一元二次方程选择题，附简短解析。`

最新结果:

- `legacy_skill`
  - 首题时延: `44469ms`
  - 总时长: `44469ms`
  - 成功: `True`
- `unified_agent`
  - 首题时延: `36156ms`
  - 总时长: `36156ms`
  - 成功: `True`
  - 标记: `orchestrator=unified_agent`

## 3. 门槛判定（按 20% 劣化阈值）

- 时延变化（Unified 相对 Legacy）: `-18.7%`
- 成功率: `legacy=True, unified=True`

结论:

- `PASS`

## 4. fallback 说明（和失败率的区别）

- `fallback` 是执行路径切换，不等于请求失败。
- 请求可“fallback 后成功”，因此 `fallback rate` 与 `failure rate` 是两套指标。

## 5. 阶段2输入（优化基线）

阶段2优化请以多轮验收为准（而不是单次）：

- 参考文档: `docs/convergence/phase1-quiz/acceptance.md`
- 关键基线（2026-02-08，10轮，最新复测）:
  - `legacy_skill`: 成功率 `100%`，TTFQ P50 `27567ms`，TTFQ P95 `34917ms`
  - `unified_agent`: 成功率 `100%`，fallback率 `0%`，TTFQ P50 `31304ms`，TTFQ P95 `36708ms`
  - 当前结论: `PASS`（P50 劣化 `+13.6%`，P95 劣化 `+5.1%`，仍在 20% 门槛内）

阶段2详细优化输入见：

- `docs/convergence/phase2/quiz-optimization-input.md`
