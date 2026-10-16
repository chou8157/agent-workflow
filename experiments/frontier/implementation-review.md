# P1 实现独立审查

- 日期：2026-10-10；范围：`coordinator.py`、`storage_common.py`、`benchmark.py` 与 CONTRACT/PLAN。
- 审查者只读实现，不修改主实现或其他 Agent 的测试；独立探针在 `independent_probe.py`。
- 初审发现保留于下文；最终探针在默认 Python 3.8.3 下全部通过，最新证据为 `evidence/independent-probe-v2.json`，保留首轮文件，运行中源码哈希稳定。

## 已复现的问题与修复追踪

| 级别 | 初审发现 | 原始实际结果 | 后续核查 |
| --- | --- | --- | --- |
| P1 | 先过滤时间窗再判冲突：同身份 revision 1 在窗内、revision 2 在窗外 | C/H 都返回 `full`、旧事实、空冲突 | 已改为先查冲突；最终均为 `partial/unresolved_version` |
| P1 | Python 字典相等把 JSON `true` 与 `1` 判为相同内容 | C/H 都返回 `full`、保留第一条 | 已改为规范编码比较；最终均为 `partial/conflicting_content` |
| P1 | 源事实显式声明 `origin_node_id=B`，但放在 A 文件时被重标 A | C/H 都 `full`，把外来事实当 A 自有事实 | 已显式拒绝；最终均为 `partial`，无事实输出 |
| P1 | 授权路径 `resolve` 后、首次打开前替换为根外 symlink | C 返回 `full` 并读到合成的根外内容 | 目录描述符/NOFOLLOW 或 Darwin fd 路径核验；最终文件及父目录两类竞态均拒绝 |
| P1 | 安全修复使用 `os.open(dir_fd=...)`，本机 Python 3.8 不支持 | 正常读取即 `NotImplementedError: dir_fd unavailable on this platform` | 增加 Darwin `F_GETPATH` 读前/读后核验；最终默认 3.8 下正常读取与竞态探针均通过 |
| P2 | 读取字节数只记成功源的一次长度，漏第二次和失败前读取 | 成功实际 288、报告 144；源变化实际 289、报告 0 | 已累计两次返回字节及失败前已返回字节；最终探针通过；不表示磁盘物理 I/O |
| P2 | `coverage` 无 `visited`；关系 revision/CAS 接受布尔值 | `validate(revision=True)` 与 `mutated(..., True)` 被接受 | 代码已增加 visited 及严格整数检查；拓扑探针会核对 visited |

初审定位：时间过滤在 `_read_node`，冲突比较在 `query` 的事实合并分支；来源归属和路径校验在 `_read_node`；布尔版本在 `storage_common.validate/mutated`。
初审期间采集的 coordinator SHA256：`d84f3bed75cbff0b568f672e3e321e85576781353e4c2610900423c2cad87042`。
初审 storage_common SHA256：`9e5a001caba202d9dbd820253a9dbca5080675eac33ae9acd0e354da2844f282`。
Python 3.8 兼容失败版本 coordinator SHA256：`e15d569d4c019b50cc0e1bae1bfba547e3819235a2dbfde48ddc49647422e026`。
首轮通过版本 coordinator SHA256：`b6bd0cbb785f230aac694723ec587dfedf9bb54b6ac86d6b03b2afb3cb6846e1`。
最终 storage_common SHA256：`aa9afee75aff31cd327abd6d6494b7f51b75d3d784dd1abb42be9dbf6ca1a92a`。
主 Agent 补充 `SourceReadError/_read_source`，修复 Darwin 读后路径校验拒绝时遗漏已读字节；本代理用原探针复跑至 `evidence/independent-probe-v2.json`，400 DAG × 2 策略、1200 深链、14 来源边界再次全过，源码稳定，新 coordinator SHA256 为 `71ca8d70b6fdcdaae2453d5d175e30365f71e61c4fde869d9dfc05ec189971d0`；新增分支的专门测试由主测试 Agent 提供，未扩大本探针覆盖声明。

## 多父、深链与完整性

- 独立 oracle 使用 Floyd–Warshall 全对最短路，不调用被测 BFS/postorder 来生成预期值。
- 固定 seed=20261010，400 个 12 节点随机 DAG，打乱身份顺序，加入多父、节点/深度预算和拒绝集，C/H 共 800 次集合核查通过。
- 对可达目标、按最短深度选中的节点、事实集合及读取去重做独立核对；初审未发现 H 后序归并漏事实。
- 1200 节点深链 H 可执行，无 Python 递归栈错误；转发引用 719400，符合 `N*(N-1)/2`，累计工作并非恒定。
- 上述拓扑测试注入确定性 `_read_node`，只证明遍历/归并逻辑；来源变化和权限探针另用真实临时文件。
- 原有读取前后内容变化能产生 `partial`；全局源事务、读取后再变更、动态权限撤回不在该证明内。
- 节点/深度预算仅限制源读取选择，仍需枚举关系与完整覆盖；不能说整个查询 CPU/内存已由该预算严格封顶。

## 基准公平性核查

- F/S 使用同一节点源、时间窗、返回字段和四格轮换；初始化、关系快照、程序查询及更新分开计时，未发现特定后端默认优先。
- `query_ms` 已排除关系库读取；比较端到端读取成本需要同时看 `snapshot_ms`，不能把 query_ms 单独解释为数据库查询性能。
- 两者都先加载全关系快照，未测原生递归 SQL、索引选择或 Cypher；这是当前实现的比较，不能外推候选产品性能上限。
- 初版 pass 只核对身份集合，已补 `revision/occurred_at/value` 和来源路径/哈希核验。
- 初版 manifest 使用不存在的 `run/result.json`，已补真实结果产物及 SHA256；原有字节数仍只能称程序返回字节。
- 5 次为探索样本，报告全部样本和 median/min/max；不能称可靠 P95。四位置轮换在 5 次中并非严格等频，应结合 position 看短时缓存噪声。
- 已建议将失败样本计时单列，只汇总 pass 的性能；全通过时不影响结果，出现失败时需核对最终实现和样本数。
- 初始化后立即重开属于本机热缓存环境，不是断电恢复或彻底冷启动；已在限制中说明未清 OS 缓存。
- H 以集合自底向上转交事实引用，声明为 `deterministic_simulation`；没有真实子 Agent、子进程通信、网络、模型上下文或 token 计量。

## 可重现命令与边界

```sh
env PYTHONDONTWRITEBYTECODE=1 python3 experiments/frontier/independent_probe.py --output experiments/frontier/evidence/independent-probe.json
```

- 最终探针记录 seed、每组输入哈希、800 次 C/H 核查、1200 深链、14 项真实文件来源边界及执行前后源码哈希。
- 首次使用 Python 3.8.3 执行在 dir_fd 能力处失败，未生成“通过”证据；Python 3.10.10 单独运行来源边界 14 项通过；最终同一默认 Python 3.8.3 命令退出码 0。
- 最终结果：400 DAG × 2 策略、1200 深链、14 来源边界全部通过，源码稳定；本轮发现的错误 full、权限竞态和运行时兼容问题已定向验证修复。
- 未发现已验证拓扑范围内的漏事实；这不是完整安全审计，也不把 Python 3.8 的 Darwin 特例推广为所有平台已支持。
- 未验证：真实 Agent 委派/摘要准确性、运行时身份权限系统、服务数据库、跨主机/网络故障、模型 token 或真实业务文档解析。
