# 活动迁移 dry-run

## 目标

在不修改真实项目的前提下，盘点现有工作项的结构化活动记录、可人工复核的日期位置和文档缺口，确认历史资料能否直接支撑按周汇总。

## 实现

- 新增 `experiments/frontier/activity_migration_dry_run.py` 的有界只读扫描。
- `.state.json` 先通过现有状态 schema 和 `activity_records` 校验；非法状态、深层 JSON、编码/权限/符号链接和读取中消失都会降级为缺口。
- `validation-log.md`、`progress/*.md` 的日期只作为候选位置，保留相对路径、行号和来源哈希；`current-status.md` 的日期单独列为忽略的状态日期。
- 缺少 `.state.json` 但其他文档完整时标记为 `legacy_unmigrated_candidate`，不称为文档损坏。
- 增加文件、字节、目录、日期和诊断数量上限；超限结果不会继续伪装成完整扫描。
- 活动覆盖按工作项统计，不能因节点内有一条记录就认为整个节点可生成完整周报。
- `ACTIVITY_SCHEMA.md` 明确活动条目是唯一结构化事实，历史正文只作证据；活动状态是发生/收口时的快照，后续变化应新建关联记录。

## 真实盘点结果

对 `agent-workflow`、`support-service`、`feedbackserver` 三个项目执行只读扫描：25 个工作项、0 条 `activity_records`、300 处候选日期位置。前两个项目结构完整；`feedbackserver` 的 2 个工作项均为旧格式待迁移。686 个来源文件扫描前后哈希一致，未向真实项目写入。

候选日期仍需要业务语义确认，不能直接生成活动摘要、状态或完成时间。证据：`experiments/frontier/evidence/mvp-light-migration-dry-run-20261015-v3.json`。

## 结论

历史资料不能直接作为可靠周报输入；建议从今后的本地工作收口开始写入结构化活动记录，历史日期只按需抽查迁移，不做批量自动补值。真实 Agent 盲测和稳定版模板修改尚未开始。
