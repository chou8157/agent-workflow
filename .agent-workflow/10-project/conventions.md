# 项目规范

## 内容语言规范

- 必须：面向用户或智能体阅读的文档、脚本帮助、脚本输出以中文为主。
- 允许：文件名、目录名、命令参数、Python 标识符、模式名如 `init/use/record/check` 保持英文。
- 禁止：新增大段英文说明，除非是外部规范字段或必要技术标识。

## Skill 结构规范

- `SKILL.md` 保持精简，负责触发、路由和核心规则。
- 详细流程写入 `references/`，避免 `SKILL.md` 过长。
- 可复制模板写入 `assets/templates/`。
- 确定性、重复性强的结构操作优先写脚本。

## Python 规范

- 脚本应尽量兼容当前本机 `python3`，之前已遇到 Python 3.8 不支持 `str.removesuffix` 的问题。
- 用户可见的 argparse help、错误信息、普通输出使用中文。
- JSON 字段名可保留英文，便于机器读取。

## 测试规范

- 修改脚本后至少运行：`python3 -m pytest tests -q`。
- 修改 skill 结构后运行：`python3.10 /Users/yizhoucp/.codex/skills/.system/skill-creator/scripts/quick_validate.py agent-workflow`。
- 修改 Python 脚本后运行：`python3 -m py_compile agent-workflow/scripts/check_workflow.py agent-workflow/scripts/scaffold_workflow.py agent-workflow/scripts/task_context.py`。

## 安装同步规范

- 修改本地 `agent-workflow/` 后，如果希望重启 Codex 生效，必须同步到 `/Users/yizhoucp/.codex/skills/agent-workflow`。
- 同步后需要对安装版运行 `quick_validate.py`。

## Git 规范

- 源码仓库使用 `main` 作为默认分支，远端为 `chou8157/agent-workflow`。
- 开始修改前检查 `git status`，不得覆盖、回滚或混入用户已有改动。
- 提交前必须检查 diff，并运行与变更范围匹配的验证。
- 提交信息应简洁说明本次变更目标；推送、发布和创建标签必须在用户授权范围内执行。
- Codex 安装目录不是 Git 源码目录，不在其中直接开发。

## 工作流升级规范

- 模板新增目录、入口路由或强制规则时，必须同步更新 `WORKFLOW_VERSION`、`upgrade_workflow.py`、测试和升级说明。
- 升级已有工作流时，先生成计划；只自动补齐缺失结构，已有文档通过建议文件供用户确认。
