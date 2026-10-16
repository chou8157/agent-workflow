# P3 真实 Agent 固定评测协议

本协议只约束隔离 worktree 的 P3 实验，不代表稳定版能力，也不预选 C/H/M 赢家。

## 固定数据与独立预期

- 数据入口：`fixtures/p3/<case_id>/input.json`；人工预期：同目录 `oracle.json`。模型不得读取 oracle。
- 权威为 P4 真实工作项的 `.state.json` 副本，以及场景 `relations.json`。副本的原路径与 SHA-256 见 `manifest.json`，所有固定文件哈希见 `freeze.json`。
- `root` 的完成时间为 `2026-09-14T12:28:21+08:00`；`middle`、`leaf` 的完成时间仍为 `null/unknown`。不使用 `updated_at` 或 Markdown 推断日期。
- `side` 是 `middle` 原文的实验节点别名；关系、故障、过期摘要、冲突响应和注入片段均显式标注为合成扰动，不声称真实项目发生过这些故障。
- Oracle 的身份、事实字段、覆盖和缺口逐场景手写，不调用候选遍历、过滤或合并函数。只为引用原文而计算来源哈希；worker 预期仅对这份 oracle 做范围投影。
- 输入只带少量 state 原文和注入片段。LLM 派生摘要不能回写权威文件。

| 场景 | 核心检查 | 人工预期 |
| --- | --- | --- |
| 01-self | 本地自身任务 | 仅 root，full |
| 02-multilevel | root→middle→leaf，父节点自身工作 | 三节点各一事实，full |
| 03-diamond | 两条路径到 leaf；middle/side 同名同工作项 ID | 四个节点身份，leaf 只出现一次，full |
| 04-scope | middle 横向授权 side；root/leaf 在范围外 | 仅 middle/side，full；不读取诱饵路径 |
| 05-unavailable | 拒绝和不可达 | root 成功；middle=denied、leaf=unreachable，partial |
| 06-conflict | middle 的旧摘要；leaf 同版本两种响应哈希 | 忽略旧摘要；leaf=source_conflict，无 leaf 事实，partial |
| 07-revision | 请求版本 5，观察版本 6 移除 leaf | expected 仍含三节点；leaf=registry_revision_changed，partial |
| 08-budget | 两节点准入、一事实输出额度 | root 成功；middle=output_budget、leaf=node_budget，partial |

场景 06 只有一份实际 authority。第二份是传输层的合成冲突响应；模型不得凭措辞选一个“较新事实”。场景 08 的跳过由确定性预算预检提供，不能以静默少报替代。全局输出字节溢出另按调用失败处理。

## 输入、输出和预算

- 一次调用输入文件最多 **16 KiB UTF-8 字节**，原始 final 最多 **4 KiB UTF-8 字节**；包括 JSON 标点、空白及换行。字节不是模型 token。
- 准备阶段输入超限则拒绝启动，不截断。输出超限、无效 JSON、重复字段、额外字段、遗漏、错误 full、幻觉、错 hash 或把 unknown 补成日期均判失败。
- 统一 schema 见 `fixtures/p3/output-schema.json`。事实身份为 `(origin_node_id, work_item_id)`；引用 `.state.json` 的 SHA-256；关系也引用场景文件哈希。
- `coverage.expected` 必须由 `succeeded`、`failed`、`skipped` 完整且不重叠地组成。每个失败或跳过节点必须有对应 gap。数组按输入规则排序，重复事实拒绝。
- 所有策略和重复使用相同 schema、原始事实、授权范围、预算和最终 oracle。验证器是独立确定性程序，不让模型给自己评分。

## 原生调用约束

正式矩阵为 **8 场景 × 3 策略 × 3 次 fresh = 72 个最终报告调用**；worker 另计，共 **138 个实际子会话**。

1. 每次使用原生 `collaboration.spawn_agent`，`fork_turns="none"`；不传 model 或 reasoning_effort override。期望继承 `gpt-6-astra/xhigh`，实际值以 rollout 为准。
2. 调用参数来自 `prepare` 生成的 `spawn-request.json`。子 Agent 只允许一次 `functions.exec`，其唯一底层动作是 `cat -- <指定 input.json>`。禁止其他文件读取、网络、消息、修改和进一步 spawn。
3. 输入读取前允许宿主要求的简短 commentary；读取完成后无任何工具、无 commentary，只以 final 返回 schema JSON。内部 reasoning 不作为额外输出。
4. 指定工具表达式由 harness 提供。审计只接受该表达式或参数完全一致的直接 `exec_command`，并核对成功返回的原文字节与冻结输入相同。不尝试证明任意 JavaScript 的安全性。
5. 每个调用使用唯一 agent_path；失败不原地重试、不换模型、不改输入。若修订协议或运行器，保留旧证据并创建新的 run_id，区分调试与正式矩阵。

原生会话仍会包含宿主系统提示与工具说明，因此这是统一受控应用输入实验，不声称模型完全没有宿主上下文。

## 三种真实执行路径

| 策略 | 原文分配与合并 | 正式调用数 |
| --- | --- | --- |
| C | 单 final 读取本场景所有已提供原文和失败结果 | 24 |
| H | 固定关系生成所属树；每个节点 worker 读取自身原文及直接下级真实输出，再逐层归并到 final | 66，含 42 workers |
| M | 非入口节点最多 2 个一批，并按 8192 字节预检；各批真实 worker 后交给含入口自身原文的 final | 48，含 24 workers |

H 的菱形节点按字典序深度遍历确定唯一所属父节点，避免重复读取；原关系仍留在输入里供覆盖核验。逻辑上的 leaf→middle→final 由依赖关系保证；宿主可把这些模型调用创建为同一父会话的独立 fresh 子会话，以保持运行配置一致。M 依据节点/字节阈值分批，不复用 H 或 C 的输出。

父调用只接收实际 child final，harness 不修正其事实、不用 oracle 补字段。非法下级 JSON 保留原文及明确错误；超 4 KiB 的下级响应只转交错误和原输出哈希，原始响应仍保留并判该调用失败。worker 和 final 都独立按人工 oracle 验收；即使 final 偶然正确，worker 失败也不能使该次完整运行通过。

## 复现与证据

以下命令从隔离 worktree 根目录运行。脚本只准备和审计，不自己启动模型。

```bash
python3 experiments/frontier/p3_cases.py check
python3 experiments/frontier/p3_native_harness.py prepare \
  experiments/frontier/evidence/p3-native-formal-20261010b/plan.json \
  p3b20261010_c_01_r1_final
```

将返回对象原样传给 `collaboration.spawn_agent`。等待该子会话结束，再收集；H/M 按 plan 中的 dependencies 顺序运行，下级收集后才能准备父调用。

```bash
python3 experiments/frontier/p3_native_harness.py collect \
  experiments/frontier/evidence/p3-native-formal-20261010b/plan.json \
  --sessions /Users/yizhoucp/.codex/sessions/2026/10/10 \
  --call-id p3b20261010_c_01_r1_final
python3 experiments/frontier/p3_native_harness.py score \
  experiments/frontier/evidence/p3-native-formal-20261010b/plan.json
```

- 按 `session_meta.source.subagent.thread_spawn.agent_path` 和 plan 创建时间定位本轮子会话。相同 agent_path 匹配多个新会话时拒绝猜测。
- 保存实际 `turn_context.model/effort`、原生日志路径与哈希、工具轨迹、final、输入/输出哈希、预算字节和评分。来源文件仍可只读追溯。
- Token 使用该子会话**最后一次** `token_count.info.total_token_usage`，不能累加每个累计快照；另外记录单次模型请求最大的 `last_token_usage.input_tokens`。
- 耗时取原生 session timestamp 到 final response timestamp；逐调用保存，并按策略累计所有 worker 与 final 的耗时（串行执行；不混入外层准备时间）。只在原生 `task_complete` 后收集，避免漏掉最终 token 事件。
- 每策略累计所有 final 与 worker 的真实 usage，包含这些子会话的系统提示和读工具开销；不把外层调度/开发 harness 会话成本混入产品候选。cached input 与 reasoning output 为子集，不能再次加到 total。
- 缺失 token、模型/effort 不一致、越界工具、未证实读入字节或不唯一会话均使本次失败。未完成 72 final 和全部 workers 时不能报告“矩阵通过”。

## 验证边界

`test_p3_cases.py` 与 `test_p3_native_harness.py` 使用人工 oracle 和明确标记的合成日志验证验收器，不属于真实模型成功证据。已在 Python 3.8.3 和 3.10.10 各执行 **73 passed**。fixture 输入为 4,597–7,258 字节，人工 oracle 为 579–1,440 字节。

首次数据预检时尚未运行 P3 真实模型调用；正式进展与结论以 `p3-results.md` 和对应 `score.json` 为准。完成正式矩阵后只能报告这 8 个小场景、同一模型配置下的实测结果；不外推大规模 token 趋势、一般模型抗注入能力、生产安全或存储后端选型。
