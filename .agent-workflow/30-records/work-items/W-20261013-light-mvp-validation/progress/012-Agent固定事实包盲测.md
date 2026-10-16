# Agent 固定事实包早期调试

## 结果与边界

两个独立 Agent（blind_agent_a、blind_agent_b）的原始 final 均缺少 claims[].fact_ref，以当前声明契约回放均拒绝。原始字段值与预期的三个合成事实一致。

原始 final 已从会话日志提取，并与 task_complete 逐字核对；证据见 experiments/frontier/evidence/mvp-light-agent-blind-20261015-audited.json。

## 证据更正

旧 mvp-light-agent-blind-20261015.json 中的 fact_package 是事后构造。原生日志中的任务提示已加密，不能据此证明当时发送了完全相同的契约或输入字节，也不能把失败单独归因为模型能力。

旧文件保留并标记 superseded_by_raw_audit。后续以预先冻结的输入文件与可核验的实际读取内容进行验证。
