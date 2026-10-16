# 活动记录迁移 dry-run

`activity_migration_dry_run.py` 只扫描现有工作项并生成候选，不会改写项目。

```sh
python3 experiments/frontier/activity_migration_dry_run.py \
  /path/to/project --json
```

规则：

- `progress/*.md` 和 `validation-log.md` 的日期只标记为候选记录日期，必须人工确认后才能成为 `activity_records`。
- `current-status.md` 的日期只作为状态更新时间提示，不自动转成业务活动。
- `.state.json` 的 `updated_at`、文件修改时间和扫描时间不会成为候选活动日期。
- 缺失工作项文档和非法状态会显示为 `partial`，不会被当成空项目；缺少 `.state.json` 但其他资料完整时标记为 `legacy_unmigrated_candidate`，表示旧格式待适配，不等于文档损坏。
- 输出的是日期位置、来源行号和来源哈希，不是已经确认的活动事件；同一日期的多处记录不会自动合并，也不会自动补摘要、状态或完成时间。
- 扫描有文件数、字节数和诊断数量上限；超限结果会降级并保留缺口。它是有界的近似盘点，不保证跨整个运行期间的原子快照。
- 脚本没有写入逻辑，输出可作为后续迁移工具的输入，但不能直接作为事实源。
