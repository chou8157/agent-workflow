# P4 有界读取与统一后端包装层

本文件描述 `node_workflow.py` 的当前实验接口，取代 `p4-acceptance.md` 中“CLI 直接返回原文、仅支持文件关系”的旧描述。旧证据仍保留，不作为当前源码验收。

## 事实与覆盖范围

- `.state.json` 是工作项状态事实的原始权威。返回的规范事实身份为 `(origin_node_id, work_item_id)`；完成时间缺失保持 `unknown`，不从标题、进展或文档日期猜测。
- `read`/`aggregate` 的事实域是**工作项状态摘要**，不是完整周报、成果识别或任意文档的语义理解。
- 来源清单递归枚举获准节点 `.agent-workflow/` 内的 Markdown/JSON，包含 `progress` 等原始记录；按路径、SHA-256、行号和观察时间定位。其他扩展名不在本轮来源域内，符号链接不扩展读取范围。
- 库函数仍可返回四种核心文档的完整内容供确定性验收。CLI 派生产物仅保存事实元数据、来源清单、缺口、关系版本和变化检查信息；证据命令按需重读原始文件。没有把派生结果写回原文的接口。

## 关系后端与自治

`network-init` 和 `enable` 接受 `--backend file|sqlite|log|postgresql|neo4j`，默认 `file`，已有不含 `backend` 的身份配置继续按 `file` 解释。

| 后端 | `--registry` 含义 |
| --- | --- |
| file | JSON 权威文件路径 |
| sqlite | SQLite 权威文件路径 |
| log | 快照、追加日志和提交水位共同所在的权威目录 |
| postgresql / neo4j | `p2_*` 实验 namespace，保持字符串，不做路径规范化 |

五个后端共用加入、退出、退出恢复、聚合、迁址和迁址核对逻辑。服务连接读取专用实验环境变量；本文件和证据不保存连接凭据。

`local --project PATH -- ...` 仍运行原稳定 `task_context.py`，不读取可选 `.frontier-node.json`、不连接关系库；身份配置缺失、损坏或字段无效均不妨碍原本地任务。非活动备份标记仍禁止本地写入。

兼容边界：包装层拒绝工作流中的所有符号链接，这比直接使用原稳定 CLI 更严格。本轮不等同于所有原 CLI 使用方式的完全兼容性证明。

## 有界读取

```bash
python3 experiments/frontier/node_workflow.py read --project NODE --run-root CONTROL/runs
python3 experiments/frontier/node_workflow.py aggregate --project ROOT --source-root NODES --run-root CONTROL/runs
python3 experiments/frontier/node_workflow.py page --handle 'PATH/run.json#SHA256' --source-root NODES --kind facts --cursor 0
python3 experiments/frontier/node_workflow.py page --handle 'PATH/run.json#SHA256' --source-root NODES --kind sources --cursor 0
python3 experiments/frontier/node_workflow.py page --handle 'PATH/run.json#SHA256' --source-root NODES --kind gaps --cursor 0
python3 experiments/frontier/node_workflow.py evidence --handle 'PATH/run.json#SHA256' --source-root NODES --sha256 SOURCE_SHA --line-start 1 --line-end 4
```

- `read` 的 `--source-root` 隐含为其项目目录；后续 `page/evidence` 必须重申同一根目录。
- `read/aggregate` 默认将派生 run 写入系统临时目录下 `frontier-derived-runs/run-*/run.json`，只返回计数、覆盖缺口数量和 handle。显式 `--run-root` 也必须在授权来源根之外。
- 默认输出上限为 **4096 UTF-8 字节，包含 JSON 换行**。`page/evidence --max-bytes` 可设置 256 至 4096；这是传输字节预算，不是模型 token 预算。
- 分页返回 `cursor/next_cursor/done/total`。`facts` 只含规范事实元数据，不含 `documents`；`sources` 列来源坐标，`gaps` 列逐项缺口。单条无法装入一页时明确失败，不推进游标，不静默截断。
- 相同来源哈希对应多个路径时，`evidence` 需附加 `--source-path`。行号必须完整有效，超范围或超字节预算都明确失败。
- 源文档、工作项/来源清单、节点身份或关系版本变化时，旧 run 返回 `stale`，要求重新读取。每次分页重核验来源，不承诺跨文件原子快照或永久锁定来源。
- `full/partial` 返回退出码 0；无法建立范围、预算参数无效、取证失败或 `stale` 返回退出码 2。调用者必须检查 JSON 状态，不能仅凭退出码判断覆盖完整。

## 信任与资源边界

这是**可信本机调用者原型**。handle 的 SHA-256 用于发现意外修改，不提供来源授权真实性。具有控制目录写权限的调用者可以重新生成 run 和哈希；它不是防恶意 Agent、共享多租户或操作系统权限隔离机制。

加载器拒绝把来源目录充当 run、拒绝符号链接定位，并要求 `run-*/run.json` 形状；路径限制不能代替授权凭据。来源授权仍由可信调用者和外层工具权限保证。

分页会重新扫描获准来源以检测变化；大文件完整读取与哈希仍消耗本机内存和 I/O。4 KiB 上限限制进入调用者的单次输出，不等同于文件读取成本、累计 token、总执行耗时或全局事务预算。

## 当前验证

初次重跑原 32 项验收，结果为 32 passed；同套验收扩展到 file/sqlite/log 为 94 passed。新增本地与 CLI 用例的首轮结果为 132 passed、2 个真服务用例未配置而跳过（不是服务通过）。

首轮实际 subprocess CLI 共 127 次，其中有界接口 120 次，最大 stdout 为 3733 UTF-8 字节；包含 15 个事实、6000 行的进展原文、多页来源、超大标题/行范围拒绝及动态变化 stale。原始输出在 `evidence/p4-final-cli-local-initial.json`。最终源码和完整五后端验收以父任务后续重录证据为准。

最新本地回归为 **135 passed、5 个五候选统一生命周期用例显式 deselected、53.45 秒**，命令和当前源码指纹见 `evidence/p4-final-local-validation.json`。这 5 个用例由父任务单独连接真服务运行，不是失败或本轮通过。最新实际 CLI 121 次，其中有界接口 117 次、最大 stdout 3733 字节；详见 `evidence/p4-final-cli-local.json`。期间代码指纹未变化。

新增来源目录/run 分离检查后，旧测试曾因匹配较晚的旧错误分支出现 3 个失败；失败与修正说明保留在 `evidence/p4-final-before-scope-test-fix.json`。修正只把两个独立边界分开断言，最终范围负例和完整本地回归通过。

本轮测试只修改 tmp 副本；P3/P4 fixture 原文不修改。服务验收由父任务在 P2 计时结束后接手，避免污染服务性能样本。
