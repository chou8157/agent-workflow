# 当前状态

## 恢复摘要

- 最近更新：2026-10-11
- 生命周期状态：见 `.state.json`（不要在本文件重复维护）
- 当前阶段：**本阶段验证与选型完成；正式产品开发尚未开始。**
- 实验范围：仅独立 worktree `codex/exp-frontier-workflow-20261009`，基线 `main@31989c7`；稳定源码、主工作区和安装版未修改。
- 已完成：P0-P4 多方案实验、独立审查、真实 Agent 评测、五后端节点回归、隔离复核和最终选型。

## 选型结论

- 关系控制面默认选择 **SQLite**；PostgreSQL 保留给未来团队/多机部署，Neo4j 和 F-log 暂不作为默认后端。
- 真实 Agent 编排没有合格生产赢家：C/H/M final 通过分别为 14/24、15/24、11/24；第一阶段只保留“确定性程序固定范围与预算 + 单次受控 Agent 汇总”的 C 作为实验基线。
- 节点事实仍由所属节点工作流文件唯一保存；聚合按需读取、只写运行记录和派生结果，不自动回写或同步其他节点。

## 当前阻塞与边界

- 无环境阻塞；但 P3 严格门槛未通过，因此不能把实验结果当作可上线的 Agent 编排能力。
- 当前未执行正式产品实现、真实项目试用、主分支合并、提交、推送或安装版同步；这些属于后续独立授权范围。

## 近期验证

- 稳定项目测试 `29 passed`；实验完整套件 `407 passed, 38 skipped`；服务契约 `44 passed`；P4 节点回归 `138 passed, 2 skipped`；P4 本地验证 `135 passed`。
- P1 正式矩阵 520 次通过；P2 文件/SQLite/F-log/PostgreSQL/Neo4j 存储、恢复和容器强杀证据已归档；P3 共 138 次 fresh Agent 调用且全部有审计证据；P4 覆盖自治、来源哈希、分页、证据下钻和有界查询。
- 最终隔离复核确认稳定文件、主工作区和安装版未受影响；详细结论见 `experiments/frontier/SELECTION.md` 与 `experiments/frontier/IMPLEMENTATION.md`。

## 关联阅读

- 需求定义：`work-item.md`
- 选型结论：`../../../../experiments/frontier/SELECTION.md`
- 正式开发路线：`../../../../experiments/frontier/IMPLEMENTATION.md`
- P3 真实 Agent：`../../../../experiments/frontier/evidence/p3-native-formal-20261010b/p3-results.md`
- P4：`../../../../experiments/frontier/p4-bounded-cli.md`
- 最终隔离：`../../../../experiments/frontier/evidence/final-isolation-20261011.json`
- 详细进展：`progress/`
- 需求变更：`changes/`

## 自动收口摘要

- 最近收口：本阶段验证与选型完成：P0-P4 证据、最终隔离复核和 SQLite/C 选型已收口；正式产品开发尚未开始。
