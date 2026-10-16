# 存储候选官方资料核查

- 实际访问日期：2026-10-10（Asia/Shanghai）；下列官方 URL 均使用 `curl` 获取，返回 HTTP 200。
- 范围：文件、SQLite、PostgreSQL、图存储的初步能力比较；图存储以 Neo4j 为具体代表，不能外推到所有图数据库。
- 证据边界：本文只有资料核查和设计建议；没有启动数据库、安装依赖、连接业务库或执行数据库性能/恢复实验。
- 版本边界：`current` 与 Python `/3/` 文档会变化；真正运行实验时必须记录引擎、驱动、版别、持久化参数及硬件。Neo4j 迁移例证明确限于 4.4 → 5.26 LTS。

## 先区分权威与索引（设计建议）

1. 项目内部事实由项目自身的唯一来源管理；普通项目工作不要求上传摘要、更新父项目或访问聚合服务。
2. 每条关系必须可定位到唯一权威及其版本；父/子入口中出现的引用、缓存或摘要不因此成为第二个可写权威。
3. “关系权威库”保存不可由其他数据完整推导的关系；它丢失后需要从备份恢复，不能宣称随时重建。
4. “可重建索引”只由指定权威导出；必须保存来源、版本/指纹和生成时间，可删除后重建，不承接独立业务写入。
5. 数据库存储形式不决定其角色：SQLite、PostgreSQL、Neo4j 均可成为权威或索引；文件也可以是关系权威。
6. 聚合按请求读取相关节点，子 Agent 接收有范围的只读任务；节点故障应产生“不可达/未知”，不得被转写为“无工作/已完成”。
7. 权威是逻辑写入责任，不等于必须集中部署。若关系分散在多个独立权威库，跨库原子更新、全局无环和全局同一快照需要额外协调协议；单库 ACID 不提供这些跨库保证。

## 官方资料事实与实现边界

| 候选 | 官方资料确认的事实 | 本实验需要自己实现或明确的边界 |
| --- | --- | --- |
| 文件 | Python `os.replace` 成功时重命名是原子的，跨文件系统可能失败；`flush` 后 `fsync` 用于刷新文件缓冲。`fcntl` 提供 Unix 文件锁。[F1][F2] | 原子替换一个文件不等于多个文件事务，也不等于完整断电持久化证明；并发读改写、结构约束、版本冲突和恢复均由应用负责。 |
| SQLite | 多个读事务可以并存，同时只有一个写事务；WAL 允许读写并行，但仍只有一个写者，要求进程在同一主机，不支持网络文件系统。[S1][S2] | 需要锁等待/有界重试策略；长读可能阻碍 checkpoint。不能把本地 WAL 文件放在共享盘当跨主机数据库。 |
| PostgreSQL | 默认 Read Committed，每条查询读自己的快照；Serializable 可保证成功提交的事务等价于串行执行，但应用必须处理序列化失败并重试。[P1] | 不能只在默认隔离下“先检查后写入”就宣称并发关系约束安全；要规定拓扑写入的隔离、锁或版本比较策略。 |
| Neo4j | 图、索引和 schema 操作通过事务满足 ACID；默认 Read Committed，显式锁可以实现更强隔离；部分读改写会丢失更新，死锁需要处理。[N1][N2] | 图边天然可查询不代表业务关系天然正确；需要约束、写入协议、超时、锁顺序和重试。不能用“图数据库”替代故障设计。 |

### 索引与关系表达

- **文件事实/建议分界**：`os`/`fcntl` 只提供文件与锁原语。建议基线采用一个带版本号的关系快照，加独立且稳定的锁文件，锁内执行读取、校验、写临时文件、替换；原子替换会改变 inode，不应把锁绑在会被替换的数据文件上。
- **SQLite 资料事实**：支持普通/唯一/部分/表达式索引；外键启用状态要逐连接设置并检查，不能依赖编译或运行时默认。[S3][S4]
- **PostgreSQL 资料事实**：支持唯一、外键等约束；递归 CTE 可以遍历关系，`CYCLE` 可检测查询路径中的环。[P2][P3]
- **Neo4j 资料事实**：索引由 DBMS 自动填充和维护；提供 range/text/point/token lookup 等性能索引。属性唯一约束可用于节点或关系；属性存在、属性类型、key 约束存在 Enterprise 版别边界。[N3][N4]
- **共同设计建议**：多父关系使用独立边标识及边类型，不给每个节点只留一个 `parent_id`。对需要无环的关系类型，在同一写事务/写锁内检查并写入；允许环的类型则必须限制遍历深度、去重和预算。
- **不能混淆**：查询中的 `CYCLE` 检测不是写入时 DAG 约束；Neo4j 的 ACID、唯一属性也不是全局无环证明。两条并发边分别通过旧快照检查，仍可能合成环。

### 备份与恢复

| 候选 | 官方资料事实 | 验证建议 |
| --- | --- | --- |
| 文件 | 原子重命名保证目标名称切换的原子性。[F1] | 单一不可变快照可复制；多文件事实应固定一个版本清单再备份。必须实测崩溃点、旧/新版本完整性及恢复，不能只验证 JSON 可解析。 |
| SQLite | Online Backup API 允许在线增量复制，完成后得到一致快照；`VACUUM INTO` 也是官方提供的备份途径。[S5] | 备份恢复后验证关系、版本及约束；不能简单复制活跃 WAL 模式下的主 `.db` 就宣称完整备份。 |
| PostgreSQL | `pg_dump` 产生单库一致快照，一般不阻塞正常读写；需要排他锁的操作例外。单库 dump 不含角色/表空间；`pg_dumpall` 的多个数据库快照不同步。[P4] | 保存所需全局配置与版本；恢复到独立实例，再核验数据。多个节点的分别备份不能自动解释为统一时间点。 |
| Neo4j | Community 提供离线数据库备份/dump；在线备份等能力属于 Enterprise。[N5] | 按实际版别分别测停机和在线恢复，不把 Enterprise 文档能力算作 Community 已有能力。 |

### 迁移与部署

- **文件建议**：维护明确的格式版本、确定性迁移与旧版本回滚备份；迁移和写入使用同一锁域。Git 可审阅文本差异，但 Git 提交不能为运行中多文件更新自动补上事务。
- **SQLite 资料事实**：`ALTER TABLE` 支持有限操作，通用复杂变更有重建表的官方步骤。[S6] **建议**：模式升级在事务内执行并做完整性检查，阻止旧写入器继续写新格式；数据库文件格式兼容不等于业务 schema 可无条件降级。
- **PostgreSQL 资料事实**：服务端/客户端架构；`CREATE INDEX CONCURRENTLY` 允许正常写入继续，但需多次扫描、可能留下无效索引且不能放在事务块内；逻辑 dump 通常可载入较新版本。[P4][P5][P6] **建议**：把服务进程、账户、连接、升级窗口和监控成本纳入比较。
- **Neo4j 资料事实**：官方 4.4 → 5.26 LTS 指南要求新 DBMS、备份/dump，并指出迁移需要停机；运行要求按 Neo4j/JDK 版本配套。[N6][N7] **建议**：固定具体版本和版别，再验证 Cypher/schema 与存储升级；不能把该旧版本迁移步骤当作所有未来版本通用流程。
- **部署共同建议**：本地嵌入与服务化分开评分。共享关系服务不可达时，节点本地既有工作仍应可读写；只有依赖关系服务的操作返回明确的降级结果。备份关系库不等于备份节点源码、工作项或权限凭据。

## 同台验证的范围（实验建议，不是结果）

| 维度 | 所有候选使用同一验收条件 | 不能这样比较 |
| --- | --- | --- |
| 语义 | 同一节点/边数据、稳定 ID、关系类型、权威版本；菱形、多父、多层、移动、解绑、自环、重复边、缺失节点 | 只给 SQL 方案加完整约束，却给文件方案无锁裸写；用内存字典冒充真实图数据库 |
| 并发 | 独立进程并发写、重复请求、版本冲突、两笔反向边竞争、读到旧/新完整快照；统计失败和重试 | 单进程串行结果冒充并发能力；一方关闭 fsync，一方同步持久化后直接比写速 |
| 故障 | 规定提交前/提交后崩溃点；重启后验证已承诺写入、未提交写入和半成品 | `kill` 进程就宣称通过断电测试；数据库崩溃恢复等同于业务库不可达时节点仍自治 |
| 自治 | 关闭聚合层/关系权威服务，节点内部操作仍完成且不自动向上写入；聚合返回缺失清单 | 将节点本地工作也改成依赖共享数据库，然后仅比较查询速度 |
| 聚合 | 按请求选择节点、只读委派、权限过滤、预算/超时/取消、重复路径去重、来源版本 | 预先同步全部节点摘要的方案与实时按需读取方案忽略新鲜度差异后比延迟 |
| 恢复迁移 | 同一逻辑数据导出、恢复、格式升级、旧写入器拒绝、恢复后结果一致 | 仅备份文件存在就判成功；为只有某版支持的在线备份打“全系列支持”勾 |
| 性能成本 | 相同数据规模/分布、冷/热状态、事务边界、持久化保证；报告延迟分布、重试、内存、磁盘及操作步骤 | 直接用嵌入式函数调用对跨网络 RPC 排全局名次；忽略服务安装、常驻资源和备份成本 |

1. 第一层可共享纯契约测试，但每种候选必须写入自己的真实存储，并自行实现满足契约的事务方案；协议通过不等于后端实现通过。
2. 第二层需要实际引擎的事务、索引、恢复和迁移实测。没有 PostgreSQL/Neo4j 运行环境时，标记“未运行”，不以模拟结果补齐，更不计为失败。
3. 第三层单列跨主机、网络分区、长事务、多个权威协作和实际负载；本机微基准不能推导这些结论。
4. 决策先看硬约束是否满足，再比较复杂度和成本。文件可以因低操作成本胜出；服务库可以因多客户端管理/并发需要胜出；SQLite 不享有默认优先权，图存储也不享有关系场景的默认优先权。

## 尚未验证

- 未检验本机各引擎/驱动是否可用，未运行任何存储候选；本报告不提供吞吐量、延迟或规模上限结论。
- 未验证 macOS/APFS 的断电持久性、磁盘满、网络文件系统锁语义、真实跨主机故障、企业版授权成本或升级回滚。
- 未证明分布式关系权威的一致性协议；若后续采用分权关系方案，须单独定义允许的暂时不一致、冲突处理及事实来源。
- 官方文档说明能力边界，不替代实现代码和端到端验收；当前候选没有最终排名。

## 官方来源（均于 2026-10-10 实际访问）

- [F1] Python `os.replace` / `os.fsync`：https://docs.python.org/3/library/os.html
- [F2] Python Unix 文件锁：https://docs.python.org/3/library/fcntl.html
- [S1] SQLite 事务：https://www.sqlite.org/lang_transaction.html
- [S2] SQLite WAL：https://www.sqlite.org/wal.html
- [S3] SQLite 索引：https://www.sqlite.org/lang_createindex.html
- [S4] SQLite 外键：https://www.sqlite.org/foreignkeys.html
- [S5] SQLite 在线备份：https://www.sqlite.org/backup.html
- [S6] SQLite schema 变更：https://www.sqlite.org/lang_altertable.html
- [P1] PostgreSQL 隔离级别：https://www.postgresql.org/docs/current/transaction-iso.html
- [P2] PostgreSQL 约束：https://www.postgresql.org/docs/current/ddl-constraints.html
- [P3] PostgreSQL 递归与 CYCLE：https://www.postgresql.org/docs/current/queries-with.html
- [P4] PostgreSQL 逻辑备份：https://www.postgresql.org/docs/current/backup-dump.html
- [P5] PostgreSQL 并发索引：https://www.postgresql.org/docs/current/sql-createindex.html
- [P6] PostgreSQL 部署架构：https://www.postgresql.org/docs/current/tutorial-arch.html
- [N1] Neo4j 事务：https://neo4j.com/docs/operations-manual/current/database-internals/transaction-management/
- [N2] Neo4j 并发访问：https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/
- [N3] Neo4j 索引：https://neo4j.com/docs/cypher-manual/current/indexes/
- [N4] Neo4j 约束与版别：https://neo4j.com/docs/cypher-manual/current/constraints/
- [N5] Neo4j 备份与版别：https://neo4j.com/docs/operations-manual/current/backup-restore/
- [N6] Neo4j 4.4 → 5.26 LTS 迁移：https://neo4j.com/docs/upgrade-migration-guide/current/version-5/migration/
- [N7] Neo4j 运行要求：https://neo4j.com/docs/operations-manual/current/installation/requirements/
