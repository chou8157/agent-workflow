# P4 自治集成与真实文档副本验收

日期：2026-10-10。状态：可选包装层 MVP 已实现并执行验收；原稳定 CLI、安装版与原始项目文档未修改。

## 本轮已完成

- `node_workflow.py` 将本地任务操作直接交给原 `agent-workflow/scripts/task_context.py`，不会打开关系库；网络加入、退出、聚合、迁址均为显式操作。
- 关系权威只记录节点身份、项目目录定位和边。任务生命周期仍取自原 `.state.json`；Markdown 保留原文作为证据，不另建可编辑任务事实库。
- `read` 返回字段来源与原文文档：路径、SHA-256、行号、观察时间；字段缺失或损坏保留 `unknown` 并列缺口。完成时间只读取权威状态，不从自由文本、文档更新日期或工作项 ID 推断。
- `aggregate` 使用固定关系快照枚举预期来源，按 `(origin_node_id, work_item_id)` 去重；自身工作项同样包含。拒绝、退出、缺文档和越界读取均明确 `partial`，无法建立网络范围则 `failed`。
- 本地节点身份存于 `.frontier-node.json`；退出关系备份仅用于显式恢复。节点备份带清单和文件哈希，禁止直接读取为活动节点、执行本地任务或重新加入网络。

## 真实副本与预期结果

真实原文复制来源与逐文件哈希见 [fixture-manifest.json](fixtures/p4/fixture-manifest.json)。这是实验节点归属，不代表原项目本来就有此网络。

| 节点 | 原工作项 | 权威状态 | 完成时间 |
| --- | --- | --- | --- |
| root | W-20260911-workflow-optimization | completed | 2026-09-14T12:28:21+08:00 |
| middle | W-20260715-workflow-upgrade | completed | unknown |
| leaf | W-20260715-multi-work-items | completed | unknown |

关系为 `root → middle`、`root → leaf`、`middle → leaf`。完整聚合必须恰好 3 个事实，leaf 不重复计数。
leaf 的 `current-status.md` 副本末尾额外加入有标记的越权读取指令和伪完成日期；原 `.state.json` 与原项目文件保持原样。
诱导目标是节点授权目录外的合成 sentinel 文件。程序不执行文本指令；真实模型是否遵守范围，由 P3 单独核验。

## 已运行的验收

证据：[p4-acceptance.json](evidence/p4-acceptance.json)，包含命令、原始输出、每个测试名、源码指纹和 37 份原始文件哈希复核。

| 范围 | 实际结果 |
| --- | --- |
| Python 3.8.3 | 32 passed，零跳过，8.41 秒 |
| Python 3.10.10 | 32 passed，零跳过，7.57 秒 |
| 根/中间/叶子 × 未启用/关系损坏/断链/退出 | 12 个用例，原 CLI 创建、推进、完成和重读均通过；其他节点和关系控制目录哈希不变 |
| 文档提取 | 3 个固定事实、2 个未知完成时间；原文哈希、行号、字段来源正确 |
| 缺失与越界 | 缺 `.state.json` 保留 unknown + partial；拒绝 leaf 有明确覆盖缺口；越界符号链接与诱导文本不会读取外部内容 |
| 退出恢复 | 中间节点退出后根仍可经直接边读取 leaf；恢复后原节点/边集合恢复，关系版本递增 |
| 迁址 | 身份与源文件字节不变，关系定位更新；可迁回原地址；提交前失败回滚目录位置 |
| 不确定提交 | 已提交但回执失败先重读关系确认；关系也不可读时报告实际目录与待核对状态，恢复后显式 `reconcile` |
| 备份恢复 | 原地址存在时禁止另起活动身份；缺失原地址时按清单恢复；文件篡改/新增与符号链接被拒绝 |

固定预期集合与完成时间直接写在 `test_node_workflow.py`，没有调用被测遍历/提取逻辑生成预期。

## 给 P3 的稳定入口

在实验 worktree 根执行，输出为 JSON；这些命令只读真实副本，不写原项目。

```bash
python3 experiments/frontier/node_workflow.py read --project experiments/frontier/fixtures/p4/nodes/leaf
python3 experiments/frontier/node_workflow.py aggregate --project experiments/frontier/fixtures/p4/nodes/root --source-root experiments/frontier/fixtures/p4/nodes
python3 experiments/frontier/node_workflow.py aggregate --project experiments/frontier/fixtures/p4/nodes/root --source-root experiments/frontier/fixtures/p4/nodes --deny leaf
```

完整聚合输出样本见 [p4-fixture-read.json](evidence/p4-fixture-read.json)。该文件是派生验收证据，修改它不会更新项目事实。
`read` 可在网络不可用时读取单节点；`aggregate` 必须明确启用并已加入网络。返回 `partial` 时 CLI 仍返回 0，但调用者必须读取 `status/coverage/gaps`；无法建立范围返回 `failed` 和退出码 2。

## 可选操作接口

| 操作 | CLI 入口与边界 |
| --- | --- |
| 初始化节点 | `init --project PATH --node-id ID`，不会创建关系库 |
| 本地任务 | `local --project PATH -- create W-example --title 标题`；参数交给原稳定 CLI，包装层拒绝工作流中的符号链接 |
| 初始化关系 | `network-init --registry PATH`，显式创建新关系权威，拒绝覆盖 |
| 启用/加入 | `enable --project PATH --registry PATH`；`join --project PATH --parent ID`，重复身份不同定位需迁址 |
| 退出/恢复 | `leave --project PATH`；`restore-membership --project PATH`，恢复前以当前关系版本做 CAS |
| 迁址 | `relocate --project PATH --destination NEW --allowed-root ROOT`，目标不能存在，两端必须在授权根内 |
| 核对定位 | `reconcile --project PATH --allowed-root ROOT`；旧定位仍存在时拒绝猜测活动副本 |
| 备份/恢复 | `backup --project PATH --destination BACKUP`；`restore-node --backup BACKUP --destination ORIGINAL`，只向缺失原地址恢复 |

## 验证边界

- 本轮把原稳定 CLI 接到可选包装层并在真实文档副本上执行；未把包装层安装进稳定版 skill，也未操作真实业务项目。
- 只支持此实验的 POSIX 文件关系适配；S/P/G 后端与跨机器节点注册由其余实验单独验证。本轮不声称所有后端的生命周期一致性已经覆盖。
- 每个源文件双读核验变化，关系快照有版本；跨文件/跨节点仍无全局原子快照。人工同时改动源文件、断电和所有并发迁址时序未穷举。
- 元数据、关系和目录迁移不属于一个分布式事务。不确定状态明确暴露并由 `reconcile` 恢复；尚无进程被强杀后自动恢复的守护任务。
- 本地操作的写范围、原文路径边界及固定诱导样本已测；这不是任意恶意文件系统并发下的安全证明，也不能代替真实 Agent 工具权限隔离。
- 文档提取与去重是确定性程序。模型事实判断、真实父子委派、累计 token 与模型对诱导文本的表现应使用 P3 运行记录判断。
