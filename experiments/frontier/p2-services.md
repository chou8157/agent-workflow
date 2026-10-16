# P2 PostgreSQL / Neo4j 服务后端

## 当前证据状态

- 2026-10-10 最终真实契约测试 **44 passed in 8.22s**（36 个真服务用例 + 8 个配置保护用例，无 skip）。
- 实际服务：PostgreSQL **16.15**、Neo4j Community **5.26.31**；Python **3.10.10**，psycopg **3.3.6**、neo4j driver **5.28.6**。
- 最终正式矩阵 **320/320 样本通过**，P/G 原生后代查询 **280/280 通过**；运行前后代码哈希一致，当前源码与证据相符。
- 两个专用容器经 `KILL` 强杀并重新启动后，已提交 revision=2 的完整快照均保留；这是容器进程崩溃恢复，不是主机断电测试。
- 首次沙箱 TCP 连接被 `Operation not permitted` 拒绝，按权限流程重试后全过；保留 [环境失败摘要](evidence/p2-service-sandbox-attempt.json)，不将其归为后端契约失败。
- 本文只比较限定实现及部署代价，不选择赢家；不连接任何现存业务库。

## 实测证据与方法修正

| 证据 | 结果与用途 |
| --- | --- |
| [最终矩阵 v2](evidence/p2-service-matrix-v2.json) | 1/10/100/1000 节点 × flat/balanced/chain/diamond × 四后端 × 5 次轮换；含完整脱敏 pytest 输出、服务版本、逐样本和源码哈希 |
| [首轮矩阵](evidence/p2-service-matrix.json) | 同样 320/320 通过；保留原始记录，其 Python 闭包计时用了重复扫描 oracle，不再作为应用遍历性能依据 |
| [播种](evidence/p2-service-recovery-before.json) / [恢复核验](evidence/p2-service-recovery-after.json) | P/G 的已提交关系、节点定位与 revision=2 完整保持 |
| [容器强杀操作](evidence/p2-service-container-crash.json) | 根 Agent 实际 Docker 工具操作回传，记录容器/镜像身份、退出码和隔离边界 |
| [早期无服务预检](evidence/p2-service-preflight.json) | 历史预检，不能替代最终真服务验收 |

最终计时采用 O(V+E) 邻接遍历（包含每次构建邻接索引），独立集合闭包仅用作正确性 oracle。
首轮发现深链 oracle 重复扫描后进行了方法修正，服务适配器和 SQL/Cypher 未因这次修正改变；两个运行都保留。
以下为 v2 的 1000 节点、四形状各 5 次，共每后端 20 样本的中位数，单位毫秒。逐形状与 min/max 见原始证据，不把混合形状中位数当产品 SLO。

| 后端 | 初始化 | 首次快照（含重连） | 同连接重复快照 | 单节点定位更新 | 重开快照 |
| --- | ---: | ---: | ---: | ---: | ---: |
| F 文件 | 14.766 | 7.176 | 7.040 | 25.680 | 6.676 |
| S SQLite | 11.085 | 3.160 | 2.881 | 15.072 | 2.842 |
| P PostgreSQL | 89.279 | 20.227 | 12.525 | 25.076 | 20.338 |
| G Neo4j | 79.873 | 64.730 | 60.472 | 80.915 | 67.930 |

1000 节点全根原生查询仅传 9,027 字节 ID/版本；全快照传 99,868 字节，diamond 为 155,700 字节，且包含定位与边。
v2 中均衡树选择性子树的 P/G 原生查询中位数为 3.934/3.532 ms，全快照为 21.678/63.527 ms；这是减少返回内容后的专用查询收益，不能称为相同载荷的直接提速。
原生查询对运行状态有明显敏感性：相同 PostgreSQL 深链 SQL 在首轮中位数 256.965 ms，v2 为 5.756 ms。没有同期执行计划/统计信息证据，原因未确认，不将任一短运行耗时当稳定承诺。
两次 1000 节点 diamond 原生查询均正确且无超时；这只覆盖当前合成 DAG，不能推导更大或更密集图都没有路径成本。

## 连接与隔离

依赖：`psycopg[binary]` 3.x、`neo4j` 驱动和 pytest；依赖安装由根 Agent 在专用运行时完成。

| 配置 | 要求 |
| --- | --- |
| `FRONTIER_SERVICE_SANDBOX` | 必须显式为 `1` |
| `FRONTIER_PG_DSN` | 专用 PostgreSQL URL，主机只接受 `127.0.0.1` / `localhost` / `::1` |
| `FRONTIER_NEO4J_URI` | 专用 Bolt URL，主机只接受 loopback；推荐 `bolt://127.0.0.1:<端口>` |
| `FRONTIER_NEO4J_USER` / `FRONTIER_NEO4J_PASSWORD` | 专用 Neo4j 实例凭据；不写入代码、日志或证据 |
| `FRONTIER_NEO4J_DATABASE` | 默认 `neo4j`，适配 Community 单数据库 |

每个实例使用唯一 `p2_*` namespace；构造器不建表、不连接服务。初始化拒绝覆盖已有 namespace。
契约测试和常规基准只删除自己创建的 namespace，保留数据库 schema/约束；重启播种模式明确保留数据供后续核验。
显式 sandbox 开关是调用者对专用实例的声明，不是数据库账户权限系统；loopback 也不代表任意本地服务都可以使用。

## 事务与一致性

| 维度 | PostgreSQL | Neo4j Community |
| --- | --- | --- |
| 权威结构 | registry 元行、nodes/edges 表；主键、唯一性、外键 | registry 元节点、项目节点、真实 contains/related 关系；节点唯一约束 |
| 写入 | 元行 `FOR UPDATE`；事务内读版本、CAS、拓扑校验、增量写入、更新版本 | 元节点显式锁；同一事务内 CAS、拓扑校验和关系/节点增量写入 |
| 快照 | `REPEATABLE READ READ ONLY`，一致 MVCC 快照 | 临时元节点属性 SET 后 REMOVE 获取锁，持锁读取 |
| 读取代价 | 可用数据库只读事务读取现有 schema | 需要写事务权限，且同 namespace 的读取互斥；不声称数据库层纯只读 |
| 持久化 | `synchronous_commit=on` | 服务默认事务持久化；具体版本/版别由实测返回 |
| 等待 | 连接 5 秒、锁 5 秒、语句 15 秒 | 连接 5 秒、事务 15 秒；应用不自动重试 |
| 提交确认丢失 | 网络提交确认异常报告 `ServiceCommitUncertainError` | 网络提交确认异常报告 `ServiceCommitUncertainError` |

节点日常工作事实不进入这两个关系库；聚合调用不修改业务关系版本或节点事实。
Neo4j 快照内部需要元节点锁写，这是当前实现对一致性的选择，必须与完全只读角色要求单独评估。
所有拓扑约束以通过适配器的写入为边界；未声称管理员绕过适配器直接写库仍受完整 DAG 约束保护。
确认丢失后必须重读版本并核对操作，不能盲目重试；本阶段的进程终止测试不等于已覆盖网络提交确认丢失。

## 验证入口

```sh
env PYTHONDONTWRITEBYTECODE=1 python -m pytest experiments/frontier/test_service_stores.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 python experiments/frontier/service_benchmark.py --run-tests --sizes 1 10 100 1000 --repeats 5 --output <新的证据路径.json>
```

- 真服务契约：初始化/拒绝覆盖、真实过期 CAS、断链/重复边/成环、关联删除、命名空间隔离。
- 真并发：两个 spawn 客户端竞争反向边，只有一个旧版本提交成功；另一方重读后仍因成环拒绝。
- 并发规模：1/4/16 个独立连接同时竞争相同预期版本，只有一个提交成功，其余明确报告 CAS 冲突。
- 真故障：实际写入后、提交前注入异常或终止客户端进程，重新连接后验证事务回滚及继续写入。
- 真快照：并发写入期间，独立读连接看到的节点内容与关系版本匹配。
- 恢复边界：关闭适配器重开、带哈希逻辑备份/新 namespace 恢复、保留版本；不是服务物理备份或源码备份。

## 原生查询与公平性

- 四候选使用相同关系图、标识和修改，轮换顺序，分开记录初始化、首次全快照、重复全快照、更新与重开耗时。
- PostgreSQL 用 `WITH RECURSIVE ... UNION` 返回去重后代；Neo4j 用真实关系变长路径和 DISTINCT 返回后代。
- 全快照路线使用邻接遍历，与独立集合闭包 oracle 核对；原生路线必须返回相同关系版本、相同后代 ID 集合，覆盖全根与选择性子树。
- 原生路线只传节点 ID，全快照还传定位和边；分别报告载荷，不能把二者延迟当作同内容传输性能。
- 原生优化节省了应用传输/遍历，但增加后端专用查询和一致性策略；图多路径场景可能增加查询代价，超时须保留。
- 连接策略也计入当前实现成本：PostgreSQL 适配器维持一个连接，Neo4j driver 使用连接池；本机 RPC 不代表跨机延迟。
- 所有样本保存，性能汇总只使用通过样本；少量重复只作探索，不估计可靠 P95，不得从未运行服务中选出赢家。

## 专用服务重启核验

```sh
python experiments/frontier/service_benchmark.py --seed-recovery --backends postgresql neo4j --output experiments/frontier/evidence/p2-service-recovery-before.json
# 根 Agent 实际重启对应专用服务，等待服务恢复就绪。
python experiments/frontier/service_benchmark.py --verify-recovery experiments/frontier/evidence/p2-service-recovery-before.json --output experiments/frontier/evidence/p2-service-recovery-after.json
```

播种文件保留 namespace、已提交快照与逻辑备份；“重启后恢复”必须同时有外部实际重启和 verify 结果，不能只凭播种或重开客户端下结论。

## 尚未验证

- 跨主机部署、真实业务权限、TLS/密钥管理、网络分区、磁盘损坏/断电、服务原生备份恢复未在适配器代码中获得证明。
- Neo4j Community 的元节点锁式快照是否符合最终产品的只读权限硬约束，必须独立决策，不能以事实文件未修改掩盖数据库写权限需求。
- 本阶段只验证关系存储接口与查询；P/G 尚未接入 P4 的可选节点包装层，不能借用 F 的生命周期集成结果。
- 同一服务中的数据库 namespace 隔离不等于多租户权限隔离；实际需要专用账户、schema/约束初始化权限、备份和服务生命周期管理。
- 性能样本为本机 Docker 服务与本地文件/SQLite 的具体实现比较；未隔离页缓存、后台维护和查询规划状态，未估计可靠 P95。

## 运维与退出

- 两个服务由根 Agent 新建，Docker **29.7.2**，仅 loopback 端口，明确实验标签，`--restart=no`；专用凭据未进入证据文件。
- [部署与资源快照](evidence/p2-service-resources.json) 已独立只读采集镜像、端口、数据卷与限制：两个镜像均为 arm64，PG/Neo4j 逻辑镜像大小为 158,931,123 / 361,998,364 字节；无单容器显式 CPU/内存上限。
- Neo4j 配置初始 heap 256m、最大 heap 512m、page cache 256m。矩阵结束后的单次 `docker stats` 为 PG **55.06 MiB / 6 PIDs**，Neo4j **961.1 MiB / 88 PIDs**；这不是峰值、空载基线或可靠资源需求估计，镜像层也不等于独占磁盘占用。
- P/G 日常使用均依赖服务进程与驱动；Neo4j 另需要图约束和写事务权限。实验适配器不是产品化权限或部署工具。
- 契约测试和矩阵已清理各自 namespace；仅保留两个明确标识的恢复播种 namespace，供根 Agent 最终处置专用实例。
- `logical_backup()` 输出版本化、带哈希的中立节点/关系快照；`restore()` 只写新 namespace 并保留 revision，拒绝覆盖已有权威。
- 逻辑导出适合本次语义核对和迁移入口；没有实测数据库原生物理备份恢复，也未宣称文件与服务可无缝切换。
