# Phase2 Clarify 修复方案（Unified Agent）

## 1. 问题结论

当前 Phase2 的 `quiz -> ppt -> interactive` 主链路已可跑通，但 **clarify 后续执行链路仍不稳定**。  
典型现象：

1. 首轮能正确返回 `clarify_needed`
2. 用户补充信息后，Unified Agent 偶发出现结构化输出失败（`UnexpectedModelBehavior` / output validation exceeded）
3. 失败时会触发模型 fallback，但仍可能无法稳定收敛到 `FinalResult`

这意味着：**多轮对话 + 意图切换可运行，但带 clarify 的连续链路尚未达到“稳定可验收”标准。**

## 2. 根因拆解

## 2.1 输出协议约束不足

- 已使用 `output_type=FinalResult`，但 prompt 里对结构化终态约束不够硬，模型在复杂回合里仍可能输出非 `FinalResult` 结构。

## 2.2 缺少“结构修复回路”

- 当前重试主要覆盖 `validate_terminal_state`（事件/工具一致性）。
- 对“模型返回不符合 `FinalResult`”的情况，没有独立的修复层（reformat/repair pass）。

## 2.3 Clarify 上下文拼接信息不足

- `_compose_content_request_after_clarify()` 仅拼接原请求和补充信息，
- 未显式注入“上一轮 clarify 问题 + 缺失槽位”，导致模型有时只做确认，不进入工具执行。

## 2.4 重试预算混用

- 终态校验重试与结构化输出失败都在统一流程内处理，缺乏分级预算和独立观测指标。

## 3. 修复方案（按优先级）

## P0（本周必须）

1. 强化 Teacher prompt 的硬约束
- 文件：`config/prompts/teacher_agent.py`
- 增加严格规则：
  - 仅允许 `status in {answer_ready, artifact_ready, clarify_needed}`
  - `clarify_needed` 必须带 `clarify.question`
  - 给 1 个合法 `clarify_needed` JSON 示例和 1 个 `artifact_ready` 示例

2. 新增结构修复回路（Output Repair Pass）
- 文件：`api/conversation.py`
- 在 `run_stream/get_output` 抛结构化异常时：
  - 先记录原始异常类型
  - 触发一次“修复请求”（要求模型仅输出合法 `FinalResult`）
  - 修复失败再走 provider fallback
- 目标：把“结构错误”与“业务错误”分离。

3. Clarify 连续对话拼接增强
- 文件：`api/conversation.py`（`_compose_content_request_after_clarify`）
- 拼接内容增加：
  - 上一轮 assistant clarify 问句
  - 明确“已补充字段/仍缺字段”
  - 强制指令：本轮要么产出 artifact，要么再次 clarify（不能仅确认）

## P1（随后一轮）

4. 重试预算分离
- 文件：`api/conversation.py`
- 拆分为：
  - `output_retry_budget`（结构化输出修复）
  - `validation_retry_budget`（终态一致性）
- 分开打点，避免互相挤占。

5. 终态校验扩展
- 文件：`services/agent_validation.py`
- 增加 clarify 语义校验：
  - `clarify.question` 不能是空泛模板句（如“请补充更多信息”无槽位）
  - 可选：要求 `clarify.hint` 在可识别集合中（如 `needClassId` 等）

## 4. 测试补齐（必须新增）

1. 单测：clarify 连续链路
- 文件：`tests/test_conversation_stream.py`
- 用例：
  - `clarify_needed -> user_answer -> artifact_ready`
  - `clarify_needed -> user_answer -> clarify_needed(仍缺关键字段)`

2. 单测：结构修复回路
- 文件：`tests/test_conversation_stream.py`
- 模拟模型先返回非法结构，再经 repair pass 返回合法 `FinalResult`。

3. Live E2E：自然多轮链路（单 conversation_id）
- 新增数据文件建议：
  - `docs/testing/phase2-memory-chain-clarify-live.json`
  - `docs/testing/phase2-memory-chain-clarify-live.md`
- 场景：
  - 出数学题（信息不完整）-> clarify
  - 补充年级/时长 -> 产出 PPT 提纲
  - 基于 PPT 重点 -> 产出互动内容

## 5. 验收门槛（Clarify 专项）

1. 结构化终态成功率（含 clarify 场景）>= 95%
2. clarify 后下一轮进入有效执行（artifact 或继续有效 clarify）>= 95%
3. `UnexpectedModelBehavior` 在 clarify 链路下降到 < 5%
4. 同一 `conversation_id` 的自然三轮链路（含 clarify）连续通过率 >= 90%

## 6. 当前阶段判定

- Phase2 主链路（不含 clarify）: **可验收**
- Phase2 clarify 连续链路: **未达稳定验收，需要按本方案补齐 P0/P1**
