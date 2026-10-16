# Agent 边界验证收口

## 阶段结论

可以推进轻量实验版的最小集成：确定性聚合和程序报告作为基础，Agent 只作为可选的组织层。Agent 输出不合格时固定展示全部事实和缺口，避免让使用能力依赖模型每次都生成完美结构。

本阶段没有实现自由文本语义自动核验；通过不用模型自由文本作为权威正文保证当前展示边界。当前仍是工作项状态摘要，活动周报和子 Agent 自治收集调度属于后续增量。

## 已完成

- 输入模板引用实际事实，16 KiB 预检；原始 JSON 超限、重复键、无效常量、深嵌套直接拒绝。
- 声明校验覆盖字段层级、值和类型、重复身份/声明、明确遗漏与未知引用。
- 独立复查修复未知 omitted 可注入文本和 partial 空结果缺口丢失；复核无新增阻塞项。
- render_with_fallback() 对非法模型输出走确定性报告，保留全部原事实和失败节点，拒绝原因另存且不混入正文。
- 实验端到端测试通过本地活动创建、幂等重试、按需读取、日期窗口、拒绝 leaf、非法模型输出降级和来源不变。

## 真实调用与纠错

早期 a/b、c/d、e/f 三组原始 final 重新提取后结果为 0/2、2/2、0/2。旧 v3 手工重建了 e/f 输出并修改了 f 字段，导致错误 1/2，已作废。旧输入包哈希也只能证明事后构造，不能证明当时发送字节。旧文件保留并标记 superseded，由 audited 文件记录原始文本、SHA-256 和差异。

随后在调用前冻结 input.txt、summary.json、代码哈希和预算，使用两个 fresh 子会话。原生日志确认每个会话只读取该 input.txt，返回字节与冻结输入相同；final 与 task_complete 逐字一致。两次均通过全部字段声明校验，重渲染均保留 in_progress、未知日期和 denied 缺口。

证据：experiments/frontier/evidence/mvp-light-agent-frozen-20261015/。2/2 仅是受控小样本，不能代表生产稳定率。

## 最终回归

- python3 -m pytest experiments/frontier/test_agent_blind_eval.py experiments/frontier/test_mvp_light.py -q：33 passed。
- python3 -m pytest experiments/frontier -q：470 passed, 38 skipped。
- python3 -m pytest tests -q：29 passed。

## 后续顺序

先验证活动写入并发和失败恢复，再做实验版收口/汇总统一入口，最后选择一个低风险真实项目试用。工作项保持 in_progress；主分支、安装版及真实项目本轮均未改变。
