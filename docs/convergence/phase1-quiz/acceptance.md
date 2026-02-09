# Phase 1 Quiz 多轮验收报告

- 时间: 2026-02-08 22:48:20
- 每模式轮次: 10
- 请求: `请出5道一元二次方程选择题，附简短解析。`

## 汇总指标

| 模式 | 成功率 | fallback率 | TTFQ P50(ms) | TTFQ P95(ms) | Total P50(ms) | Total P95(ms) | 平均题数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| legacy_skill | 100% | 0% | 27567 | 34917 | 27567 | 34917 | 4.90 |
| unified_agent | 100% | 0% | 31304 | 36708 | 31304 | 36709 | 5.00 |

## 对比判定

- TTFQ P50 劣化: `+13.6%`（阈值 <= 20%）
- TTFQ P95 劣化: `+5.1%`（阈值 <= 20%）
- Unified 成功率: `100%`（阈值 >= 95%）
- 结论: `PASS`

## 明细

### legacy_skill
| 轮次 | success | ttfq_ms | total_ms | question_count | fallback | error |
|---:|---|---:|---:|---:|---|---|
| 1 | True | 36502 | 36502 | 5 | False |  |
| 2 | True | 26896 | 26896 | 5 | False |  |
| 3 | True | 28238 | 28238 | 5 | False |  |
| 4 | True | 28320 | 28320 | 5 | False |  |
| 5 | True | 25710 | 25710 | 5 | False |  |
| 6 | True | 29366 | 29366 | 5 | False |  |
| 7 | True | 32979 | 32979 | 5 | False |  |
| 8 | True | 25525 | 25526 | 4 | False |  |
| 9 | True | 26751 | 26751 | 5 | False |  |
| 10 | True | 25138 | 25138 | 5 | False |  |

### unified_agent
| 轮次 | success | ttfq_ms | total_ms | question_count | fallback | error |
|---:|---|---:|---:|---:|---|---|
| 1 | True | 34381 | 34381 | 5 | False |  |
| 2 | True | 29273 | 29273 | 5 | False |  |
| 3 | True | 34484 | 34484 | 5 | False |  |
| 4 | True | 27978 | 27978 | 5 | False |  |
| 5 | True | 37217 | 37217 | 5 | False |  |
| 6 | True | 30224 | 30224 | 5 | False |  |
| 7 | True | 27577 | 27577 | 5 | False |  |
| 8 | True | 36087 | 36087 | 5 | False |  |
| 9 | True | 24226 | 24226 | 5 | False |  |
| 10 | True | 32384 | 32384 | 5 | False |  |
