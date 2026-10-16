# 相近编排机制：官方资料核查

- 实际访问日期：2026-10-10（Asia/Shanghai）；仅只读获取下列 6 份官方文档，均返回 HTTP 200。
- 范围：A2A、LangGraph、CrewAI、Temporal 的机制与本项目目标的对应关系；未安装、启动服务或运行示例。
- 它们分别是协议、Agent/图执行框架或持久化工作流平台，不是已经验证能直接满足本项目要求的同类完整产品。
- “资料事实”只陈述所读页面；“借鉴建议/本项目边界”是工程判断，不表示框架没有其他相关能力。
- 这不是穷尽市场的调查，不给选型排名；`latest`/无版本 URL 会变化，后续实验必须固定具体版本。

## 机制定位

| 对象 | 文档定义的主要机制 | 与本项目相近的部分 |
| --- | --- | --- |
| A2A | 独立 Agent 之间的发现、任务交互、状态和产物协议 | 跨节点读任务的请求、进度、取消与结果封装 |
| LangGraph | 图执行、动态 orchestrator-worker、线程状态持久化 | 按请求划分工作、收集结果、恢复中断的聚合运行 |
| CrewAI hierarchical | manager Agent 分配任务并评估结果 | 按角色委派、经理协调和调用约束 |
| Temporal | 通过事件历史和重放恢复的持久化 Workflow Execution | 长任务进度恢复、外部调用重试和执行版本治理 |

## A2A：任务状态和产物协议

- **资料事实 [A]**：A2A 面向独立、内部实现可不透明的 Agent；Task 有唯一 `id`、`status`，并可携带 `artifacts`、交互历史及元数据。
- **资料事实 [A]**：任务状态区分 submitted/working、input-required/auth-required，以及 completed/failed/canceled/rejected 等终态；可通过 Get Task、流式订阅或支持的推送通知获取进展。
- **资料事实 [A]**：Cancel Task 是取消请求，成功不保证；规范要求检查 Agent Card 声明的可选能力，不能默认所有实现都支持流式或推送。
- **资料事实 [A]**：规范明确 `AUTH_REQUIRED` 状态本身不是操作授权，也不定义凭据的授权范围、有效性和撤销语义；具体操作如何授权仍由实现/发行方/扩展定义。
- **借鉴建议**：跨项目只读任务携带固定请求范围、关系版本、来源引用与覆盖表，以稳定任务 ID 跟踪；先验证查询/取消语义，再考虑流式体验。
- **本项目边界**：`completed` 表示服务端声明任务成功，不等于所有授权节点均已覆盖；内部实现不透明也不自动保证断网时节点本地工作可继续。
- **本项目边界**：Agent Card/Task ID 不替代项目身份、关系权威、权限规则或全局预算；这些字段的业务语义和验证仍需本项目定义。

## LangGraph：动态工作者与运行状态

- **资料事实 [L1]**：orchestrator-worker 模式由 orchestrator 拆分子任务、委派 workers、综合其输出；适用于子任务数量不能预先固定的情况。
- **资料事实 [L1]**：`Send` 可动态创建 worker 调用并传入专门输入；每个 worker 有自己的 state，输出写入 orchestrator 可访问的共享 state key。
- **资料事实 [L2]**：checkpointer 保存一个 thread 的图状态；store 保存图状态外的应用自定义数据，支持跨 thread 使用。两者职责不同。
- **资料事实 [L2]**：`MemorySaver/InMemorySaver` 状态在进程重启时丢失；需要持久化后端才能跨重启保存。文档同时提醒 checkpoint 累积可能增加存储和延迟，应设保留策略。
- **借鉴建议**：只在用户发起聚合时建立运行，将任务限定为节点集合或批次；worker 返回结构化证据及覆盖信息，程序负责去重、冲突和合并。
- **借鉴建议**：分别设计“聚合运行 checkpoint”和“项目关系权威”；恢复执行不能让旧 checkpoint 静默覆盖节点当前事实，恢复时应核查来源及授权版本。
- **本项目边界**：worker 独立 state 是一次执行的状态隔离，不等于项目自治；共享输出 key 也不是单节点日常必须向上同步的要求，应由应用明确触发边界。
- **本项目边界**：动态创建 worker 没有替我们证明遍历覆盖、深层总成本、来源真实性或最优批次大小；持久化图状态不能替代项目文档/关系库备份。

## CrewAI：manager 主导的层级执行

- **资料事实 [C]**：默认流程为 sequential，hierarchical 需显式设置；manager 协调流程、按角色/能力分配任务并评估结果，可自动创建或使用自定义 manager Agent。
- **资料事实 [C]**：页面给出 `manager_llm` 和 `manager_agent` 配置方式，并列出 delegation 控制、每分钟请求数、最大迭代次数和 context-window respect 等可配置机制。
- **借鉴建议**：可作为“由模型决定如何拆分任务”的实验对照；使用受限只读工具，让程序验收 manager/worker 返回的身份、来源和覆盖集合。
- **本项目边界**：manager 的结果评估不是确定性完整性证明；上下文窗口处理也不证明重要事实零丢失，更不能据此声称深层聚合总 token 固定。
- **本项目边界**：本项目允许任意节点独立工作、多父关系和可选聚合，不能因采用 hierarchical 流程就把项目组织模型强制改成唯一经理树。
- **本项目边界**：文档中的效率/令牌优化描述未在本项目实测；需要相同输入、模型、预算、失败注入和事实 oracle 后才能比较。

## Temporal：执行恢复和确定性边界

- **资料事实 [T1]**：Workflow Execution 的进展被记录，故障后通过 Event History 重放恢复；重放检查生成的 Commands 是否与已有历史匹配，依赖 Temporal Service 和 Worker Processes。
- **资料事实 [T2]**：Workflow 定义必须满足确定性约束；API、LLM、数据库查询等非确定性外部操作应放入 Activities；页面说明 Activities 可自动重试。
- **资料事实 [T1][T2]**：单次 Workflow Execution 有大小/吞吐限制，可使用 Continue-As-New；会影响命令序列的代码变更需要版本策略，不能假定任意更新都能重放旧历史。
- **借鉴建议**：若真实跨节点汇总需要跨进程故障恢复，可评估用持久化执行记录跟踪批次与重试；把节点读取当外部 Activity，同时保存请求版本及可核验来源。
- **本项目边界**：工作流恢复不等于业务事实被正确恢复；事件历史不会自动成为本项目关系和节点文档的唯一权威，也不证明离线本地节点自治。
- **本项目边界**：不能把 Workflow 的持久化执行表述扩大为所有外部副作用 exactly-once；重试下的幂等、来源变化、权限撤回和覆盖判定仍需专门设计。
- **本项目边界**：Continue-As-New 解决的是执行历史/运行组织问题，不能消除读取 N 个节点所需的总工作量或模型调用成本。

## 本项目仍需自行验证的五项要求

| 要求 | 可借鉴机制 | 不可直接从资料推出的保证 |
| --- | --- | --- |
| 单节点自治 | 独立执行入口、可选择的编排调用 | 关闭聚合服务后，本地既有工作仍能读写且不向上同步 |
| 关系和事实唯一 | 稳定身份、结构化状态、明确持久化职责 | 多父/多层关系写入的唯一权威、并发约束和恢复不分叉 |
| 按需汇总 | 显式任务请求、动态 worker、取消/恢复 | 未请求时不自动收集、不扩大读取范围、不遗留后台任务 |
| 全量覆盖 | Task/Artifact、共享输出、执行历史 | expected/visited/succeeded/failed/skipped 可核对，去重且不掩盖未知或冲突 |
| 深层资源可控 | 批次、迭代/请求限制、checkpoint 保留、Continue-As-New | 所有层累计调用、token、时间、内存有据可查，超预算不错误标 full |

建议保留现有确定性 oracle，将协议/框架适配器作为后续独立候选：先验收请求范围、失败和覆盖，再测真实模型输出与累计成本；本次文档核查不替代这些实验。

## 官方来源（均于 2026-10-10 实际访问）

- [A] A2A Specification，含 Task、TaskState、Capability Validation、In-Task Authorization Scope：https://a2a-protocol.org/latest/specification/
- [L1] LangGraph Workflows and agents，Orchestrator-worker / Send：https://docs.langchain.com/oss/python/langgraph/workflows-agents
- [L2] LangGraph Persistence，checkpointer/store 与内存持久性边界：https://docs.langchain.com/oss/python/langgraph/persistence
- [C] CrewAI Hierarchical Process，实际重定向至版本化页面：https://docs.crewai.com/v1.15.27/en/learn/hierarchical-process
- [T1] Temporal Workflow Execution，执行历史、Replay、单执行限制：https://docs.temporal.io/workflow-execution
- [T2] Temporal Workflow Definition，确定性、Activities、代码版本：https://docs.temporal.io/workflow-definition
