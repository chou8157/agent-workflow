# 自检模式（check）

## 目标

检查项目工作流结构是否完整、入口是否可发现、核心记录是否可恢复上下文。

## 推荐命令

```bash
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project
```

输出 JSON：

```bash
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project --json
```

低风险自动补齐：

```bash
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project --fix-low-risk
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project --require-work-items
```

## 修复边界

- 可自动补齐：缺失目录、空模板核心文件。
- 需用户确认：`AGENTS.md` 冲突、规则冲突、大量迁移、已有内容重写。
- 不确定事实：进入 `unknowns.md`，不能自动补成事实。

## 半残缺结构处理

如果项目已有 `.agent-workflow/` 但目录或核心文件不完整：

1. 先运行 `check_workflow.py --json` 识别缺失项。
2. 缺失的是空目录或全新核心文件时，可以用 `--fix-low-risk` 补齐。
3. 已有文件内容不符合新模板时，不自动覆盖；先报告差异和建议。
4. 旧结构中有大量内容时，切换到 `migrate` 模式给映射方案。
5. 补齐后再次运行自检，确认 `ok: true` 或列出剩余需确认项。

`--require-work-items` 用于已启用多工作项能力的项目。旧工作流默认不因缺少该目录而失败。

启用多工作项检查时，还会检查每个工作项目录是否存在 `.state.json`。缺少状态文件时先执行 `task_context.py migration-check`，不要手工批量改写工作项正文。
