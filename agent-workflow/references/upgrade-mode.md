# 升级模式（upgrade）

## 目标

让已经生成的 `.agent-workflow/` 能安全跟进当前模板的结构版本，而不覆盖用户已有的入口文档、项目事实和历史记录。

## 标准流程

1. 运行 `upgrade_workflow.py <项目> plan`，读取当前结构版本、可安全执行项和待审阅项。
2. 向用户说明哪些目录或文件会补齐，哪些已有文档只会生成建议文件。
3. 用户确认后运行 `apply-safe`。该操作只补齐缺失结构、写入 `WORKFLOW_VERSION` 并生成建议文件。
4. 用户审阅并确认建议文件后，才手工合并到已有 `AGENTS.md`、工作流入口或渐进读取规则。
5. 运行 `upgrade_workflow.py <项目> status` 和 `check_workflow.py`，记录真实升级结果。

工作流版本 3 引入工作项 `.state.json`。升级旧项目时，先用 `task_context.py migration-check` 生成只读清单，再只对无冲突项目执行 `migration-apply`；升级脚本不会自动覆盖旧工作项状态。

## 安全边界

- 结构版本与文档审阅状态分开：即使目录已升级，仍可能存在待审阅建议。
- 禁止用 `scaffold_workflow.py --overwrite` 代替升级；它可能覆盖用户已有内容。
- 禁止自动拆分历史记录到工作项目录；归属不明确的历史保留在项目级。
- 每次修改模板的结构、入口路由或强制规则时，必须同时更新 `WORKFLOW_VERSION`、升级脚本、测试和本文件。
