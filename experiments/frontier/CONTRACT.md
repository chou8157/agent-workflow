# P1 临时实验契约

版本 v1，2026-10-10；只供候选原型比较，不是产品永久接口。

## 关系权威

一个实验实例只选一个关系权威：F 的 registry.json 或 S 的 registry.sqlite。
节点内部活动/工作事实保存在独立节点文件；关系库只存身份、定位和边，不存项目事实副本。
权威库不能称为可重建缓存。备份与恢复必须覆盖关系版本；本阶段不做双向同步。

Registry(path) 暴露 initialize(nodes, edges)、snapshot()、apply(expected_revision, ...) 和 close()。
snapshot 返回 {revision, nodes, edges}，节点字段 id/locator；边字段 source/target/kind。
初始化 revision=1；成功 apply 增加一次 revision；提交前失败不改变任何内容。
文件原子替换后若目录 fsync 失败，必须报告 CommitUncertainError，要求重读，不宣称已回滚或自动重试。
apply 接收 upsert_nodes/add_edges/remove_edges/remove_nodes，未提供集合视为空。
节点删除必须先移除关联边，否则拒绝。边不得重复，contains 不允许成环，related 不用于聚合。
比较写入 expected_revision 必须在锁/事务内部，过期写入抛 RevisionConflict。
返回按 ID/边三元组排序，读取是一个一致的关系快照。断链/损坏抛错误，不返回空网络。
F/S 必须支持多进程竞争；锁超时或冲突需显式失败。本轮不承诺跨机器事务。

## 源文件与事实

节点 locator 指向实验授权根内的 JSON 文件。源文件包含 node_id/view_id/facts。
每次查询只选择节点的一种 view（本轮固定 main）；不混合多个 worktree/分支视图。
事实字段 record_id/revision/occurred_at/value；权威节点由读取节点身份确定。
事实身份为 (origin_node_id, record_id)；revision 与内容哈希不参与身份去重。
跨项目同需求的贡献属于不同事实，不能只凭标题合并。统一需求统计留到独立产品口径。
同身份同 revision 同内容为重复；同 revision 不同内容为冲突。
同身份不同 revision 属于版本分歧，本轮不擅自选择最新，报告 unresolved_version，结果不完整。
不接受响应把另一个节点的事实当作自己的新事实；中间节点只转交保留 origin 的证据。
source_path/source_sha256/observed_at 为来源坐标；哈希证明读取字节，不证明业务事实真实。
时间使用带时区时间戳和 [start,end)；本轮仅按 occurred_at 筛选，不推断完成时间。

## 请求与完整性

请求固定 root、scope=self/subtree、关系 revision、view、时间窗、节点/深度/输出预算。
执行器根据该关系快照先枚举授权目标集合：自身节点也在集合内。
全局 visited 去重，非 contains 边不扩展目标；仅加载请求实际覆盖的源文件。
full：目标集合已知，全部目标读取成功、源版本未检测到变化、无冲突或预算遗漏。
partial：目标集合已知，但任一目标失败/拒绝/预算截断/冲突/源变化，覆盖表列出原因。
failed：范围无法建立（关系不可读、根节点不存在、无效请求），不能报告成功零条事实。
合法目标全部无区间内活动可 full 且零条事实；读取失败不能伪装为零活动。
无全局源事务；每节点读取前后核验字节变化，有变化标记 partial。不同节点观察时刻可以不同。
coverage 保留 expected/visited/succeeded/failed/skipped 以及对应节点集合，不能只统计返回数量。
分页只改变传输，不改变全量结果集合；末页/游标明确，禁止隐式截断并宣称 full。
根输出只给有界摘要和结果文件指针，事实全集保存在运行产物中，可按页读取。
分页字节预算不是模型 token 预算；程序执行器不是 Agent 沙箱或权限系统。

## P1 证据边界

P1 测实际 F/S 持久化、CAS、基础查询集合、C/H 等价性和响应字节，不测模型语义准确率。
无结果缓存，各候选同样重新读取节点；若加缓存须新增权限/关系/view/请求/来源版本键测试。
P2 才覆盖真实服务后端、高并发持久性、kill/恢复/权限撤回等完整故障集。
P3 才测真实 Agent 委派、全部调用上下文、摘要事实核验与累计 token 成本。

## 本机运行与安全读取

文件候选使用 POSIX flock；本轮以 macOS 本地文件系统运行，不声称 Windows 或网络共享盘兼容。
支持 dir_fd 的 Python 逐段以 O_NOFOLLOW 打开来源；本机 Python 3.8 没有此能力，
改用 Darwin F_GETPATH 校验已打开的普通文件实际路径，读取前后都与授权后的规范路径比较。
缺少 dir_fd 且不是 Darwin 时明确拒绝来源读取，不静默退化成普通路径读取。
这只验证了本机路径边界与已测试的符号链接替换，不能替代真实 Agent 的操作系统隔离、
动态授权撤回或任意恶意并发文件系统变更下的安全证明。
