# Agent 结构化声明契约

## 日期

2026-10-14

## 实现

- `validate_agent_draft` 要求每个段落提供 `claims`。
- 程序逐项校验 `fact_ref`、字段和值；允许字段为 `title`、`status`、`completed_at` 和 `completed_at_status`。
- 自由文本保留为非权威表达，不能单独引入事实。
- 未覆盖事实仍必须显式进入 `omitted`。

## 验证

- 合法状态声明通过。
- 将已完成事实声明为 `in_progress` 的合成草稿被拒绝。
- `python3 -m pytest experiments/frontier/test_mvp_light.py -q`：`7 passed`。
- 证据：`experiments/frontier/evidence/mvp-light-agent-claim-contract-20261014.json`。

## 边界

这只是程序契约验证，没有调用真实 Agent；模型是否能持续生成正确声明，仍需后续盲测。
