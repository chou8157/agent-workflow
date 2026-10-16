# 前沿实验验证区

本目录仅承载候选原型和测试，不接入稳定版 skill。

- 规则与阶段：[PLAN.md](PLAN.md)
- 当前结果与后续门槛：[RESULTS.md](RESULTS.md)
- 临时比较接口：[CONTRACT.md](CONTRACT.md)
- 官方资料：[research.md](research.md)
- 相近编排机制：[orchestration-research.md](orchestration-research.md)
- 独立审阅：[evaluation-review.md](evaluation-review.md)
- 实现审查与修复：[implementation-review.md](implementation-review.md)
- 稳定版基线：[baseline.md](baseline.md)
- 工作项：`.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/`
- 业务活动字段：[ACTIVITY_SCHEMA.md](ACTIVITY_SCHEMA.md)
- Agent 声明契约：[AGENT_CLAIM_CONTRACT.md](AGENT_CLAIM_CONTRACT.md)
- 活动迁移 dry-run：[ACTIVITY_MIGRATION_DRY_RUN.md](ACTIVITY_MIGRATION_DRY_RUN.md)
- 单节点活动收口：[ACTIVITY_CLOSEOUT.md](ACTIVITY_CLOSEOUT.md)

## 运行

从实验 worktree 根目录执行；本机 macOS 的 Python 3.8/3.10 已验证，pytest 为测试依赖。
文件存储依赖 POSIX 文件锁。安全来源读取的运行时要求见 CONTRACT。

```sh
env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest experiments/frontier tests -q
env PYTHONDONTWRITEBYTECODE=1 python3 experiments/frontier/benchmark.py --output /private/tmp/frontier-new-run.json
env PYTHONDONTWRITEBYTECODE=1 python3 experiments/frontier/independent_probe.py --output /private/tmp/frontier-new-probe.json
```

输出路径必须尚不存在，避免覆盖历史证据。规模、拓扑、事实量与重复次数可通过 `benchmark.py --help` 查看。
每轮在系统临时目录创建隔离源、关系库与结果，不读取业务项目；完整输出不直接灌入 Agent 上下文。
临时目录可能被系统清理，已交付运行的证据清单与压缩产物归档见 RESULTS。

文件/SQLite 已有初步实测，全部候选的产品级验收仍待完成。
数据库不可用、模拟执行成功、单次性能领先均不构成最终选型结论。

## 第一阶段只读报告

在已显式启用并加入关系网络的节点上，可从上级节点生成派生 Markdown 报告：

```sh
python3 experiments/frontier/light_report.py \
  --project /path/to/root \
  --source-root /path/to/authorized-root \
  --output /private/tmp/multi-node-summary.md
```

报告写入来源目录之外；完整结果返回 0，存在拒绝或其他缺口时返回 2，但仍保留报告并列出缺口。该入口不调用 Agent，也不修改节点原始文件。
