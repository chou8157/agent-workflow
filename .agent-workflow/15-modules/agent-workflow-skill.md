# agent-workflow Skill 模块

## 代码位置

- `agent-workflow/SKILL.md`
- `agent-workflow/references/`
- `agent-workflow/assets/templates/`
- `agent-workflow/scripts/`
- `agent-workflow/agents/openai.yaml`
- `experiments/frontier/build_release.py`、`release_update.py`：完整包构建、校验与安装事务。
- `VERSION`：当前产品构建版本；`docs/releasing.md`：维护者发行流程。

## 模块职责

- 为 Codex 提供项目智能体工作流的生成、使用、记录、改进、自检、迁移、共享工作流和多工作项上下文能力。

## 主要入口

- Skill 入口：`agent-workflow/SKILL.md`
- 自检脚本：`agent-workflow/scripts/check_workflow.py`
- 脚手架脚本：`agent-workflow/scripts/scaffold_workflow.py`
- 工作项脚本：`agent-workflow/scripts/task_context.py`
- 工作项状态：每个工作项目录的 `.state.json`
- 升级脚本：`agent-workflow/scripts/upgrade_workflow.py`
- 评估记录：`agent-workflow/evaluation-notes.md`

## 关键依赖

- 模板资产：`agent-workflow/assets/templates/`
- 渐进式披露文档：`agent-workflow/references/`
- 安装目标：`/Users/yizhoucp/.codex/skills/agent-workflow`

## 注意事项

- 文档内容必须中文为主。
- 修改本地 skill 后，如需 Codex 重启后生效，必须同步安装版。
- `AGENTS.md` 和 `.agent-workflow/` 是当前项目接手入口，不要与 skill 模板目录混淆。
- 本记录只做轻量索引，不替代源码和文档阅读。

## 阅读记录

- 最近阅读：2026-11-25。
- 来源：第一批发布与版本治理源码及候选验证。
- 结论：产品版本由根 VERSION 提供，完整组合包生成发行信息；当前仅准备本地候选，远端 CI、发布和实际安装分别跟进。
