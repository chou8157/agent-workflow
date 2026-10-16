# 业务活动记录最小规范

第一阶段只读报告只汇总工作项状态。第二阶段增加 `activity_records` 后，只有明确记录的业务活动才参与时间范围查询。

## 存储位置

每个工作项的 `.state.json` 可以增加 `activity_records` 数组。该数组属于工作项事实的一部分，节点外只保存引用和哈希。

```json
{
  "activity_records": [
    {
      "id": "a-20261014-01",
      "date": "2026-10-14",
      "summary": "完成接口联调",
      "status": "completed",
      "evidence_refs": [
        {"path": ".agent-workflow/30-records/work-items/W-example/validation-log.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "line_start": 1, "line_end": 3}
      ]
    }
  ]
}
```

## 规则

- `id` 在同一工作项内唯一。
- `date` 必须是 `YYYY-MM-DD`，表示业务活动发生日期。
- `summary` 是该条活动的简短事实描述。
- `status` 使用工作流状态：`planned`、`in_progress`、`blocked`、`completed` 或 `archived`。
- 新生成的活动记录必须至少包含一条 `evidence_refs`；证据路径为项目内 `.agent-workflow/` 下 Markdown/JSON 的相对路径，并保存写入时的 SHA-256 和行号范围。该范围与当前聚合来源清单一致；不允许引用 `.state.json`，避免写入活动后自身证据立即失效。
- `evidence_refs[].hash_scope` 可选：省略或 `file` 时保持整文件哈希兼容；`lines` 时只校验所引用 UTF-8 行的原始字节（包含换行）。新操作入口使用 `lines`，范围外追加不影响原活动；引用行修改、删除或前方插入导致行号变化时仍提示缺口。不会自动升级已有引用。
- 活动条目是该活动事实的唯一结构化记录；`progress/` 和 `validation-log.md` 只作为补充说明或证据引用，不再为同一活动维护第二份独立摘要。
- `status` 表示该活动记录在发生或收口时的状态快照，不是工作项当前状态的别名；后续变化应新增具有关联 ID 的活动记录，不能静默改写已用于历史汇总的记录。
- `created_at`、`updated_at`、文件修改时间和验证日志日期不参与业务活动窗口。
- 缺少 `activity_records` 只表示日期未知，不表示没有工作。
- 记录格式错误时，整个节点降级为缺口，不能静默忽略。

## 当前边界

该规范已在实验原型中验证，但尚未修改稳定版工作项模板，也尚未迁移真实项目。活动状态是历史快照，工作项状态是当前生命周期，二者不能互相替代。历史日志日期不会批量自动迁移。哈希验证来源一致性，不判断摘要语义是否准确。
