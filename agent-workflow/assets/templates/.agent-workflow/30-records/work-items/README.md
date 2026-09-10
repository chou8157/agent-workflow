# 工作项

本目录承载项目内需求、任务和缺陷的独立恢复上下文。每个工作项只记录自身的状态、变更、进展、验证、风险和待修复项；项目公共事实仍保留在上级 `30-records/`。

## 选择与恢复

1. 用户明确指定工作项 ID 时，读取该目录的 `README.md`、`current-status.md` 和 `work-item.md`。
2. 只有一个进行中工作项时，可以默认选择它，并在回复中说明。
3. 多个工作项同时进行而用户未指定时，必须先询问，不能猜测。
4. 详细历史只在需要时读取 `progress/`、`changes/` 或按事实创建的局部日志。

## 生命周期

- `planned`：已创建，尚未开始。
- `in_progress`：正在进行。
- `blocked`：被外部条件阻塞。
- `completed`：已完成，保留以便追溯。
- `archived`：已归档，不再作为默认恢复目标。

## 创建方式

优先使用 `task_context.py` 创建工作项，保证目录、模板和状态字段一致：

```bash
python3 path/to/agent-workflow/scripts/task_context.py /path/to/project create W-20260715-example --title "示例需求" --type 需求
```

## 记录边界

- `current-status.md` 只保留当前恢复所需摘要，不能写成长流水。
- `progress/` 按阶段拆分详细历史，完成的阶段不再堆入当前状态。
- 验证、决策、风险和待修复项只有发生对应事实时才创建局部文件。
- 跨任务的决策、风险和验证写回上级 `30-records/`。
