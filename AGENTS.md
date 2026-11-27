# AGENTS.md

## 项目概览

- 项目名称：`agent-workflow`
- 项目类型：Codex skill 开发项目
- 当前核心产物：`agent-workflow/`
- 项目状态：见 `.agent-workflow/30-records/current-status.md`
- 当前需求/任务：见 `.agent-workflow/30-records/work-items/`

## 必须遵守

- 必须始终用中文回答。
- 必须先阅读本文件，再按任务类型阅读 `.agent-workflow/` 中的相关文档。
- 必须保护用户已有改动，不得擅自回滚或覆盖未确认内容。
- 有歧义时必须先提问确认，不得猜测。
- 面向用户或智能体阅读的文档、脚本帮助和脚本输出必须中文为主。
- 涉及安装同步到 `/Users/yizhoucp/.codex/skills/agent-workflow` 时，必须确认这是工作区外写入。

## 智能体工作流入口

- 工作流总入口：`.agent-workflow/README.md`
- 项目状态：`.agent-workflow/30-records/current-status.md`
- 工作项：`.agent-workflow/30-records/work-items/`
- 任务流程：`.agent-workflow/00-core/workflow.md`
- 项目规范：`.agent-workflow/10-project/conventions.md`
- 项目理解：`.agent-workflow/10-project/`
- 模块索引：`.agent-workflow/15-modules/`
- 任务门禁：`.agent-workflow/20-gates/`
- 记录沉淀：`.agent-workflow/30-records/`

## 新 session 接手顺序

1. 读 `AGENTS.md`。
2. 读 `.agent-workflow/README.md`。
3. 读 `.agent-workflow/30-records/current-status.md`，了解项目公共状态。
4. 选择目标工作项后，读其 `README.md`、`current-status.md` 和 `work-item.md`。
5. 若继续开发 skill，读 `.agent-workflow/15-modules/agent-workflow-skill.md` 和 `agent-workflow/SKILL.md`。
6. 若继续调试脚本，读 `.agent-workflow/10-project/conventions.md` 和对应脚本。

## 当前重点

- 当前正式发行版本为 `1.2.0`；本机安装仍保留已验证的 `1.1.0-beta.1`，不因源码版本切换自动更新。发行包模板结构保持 v6；原主线结构 v5 保存在标签 `v5-20261125`。
- 完整运行包由 `agent-workflow/` 与 `experiments/frontier/` 组合构建，不能仅复制基础源码目录替代发行包。
- 本机安装版已核对与实验发行包一致，用户已确认实际使用正常；本次 1.2.0 迭代不更新本机安装。主线切换见 `W-20261125-mainline-promotion`。
- 当前源码由 Git 管理，`main` 跟踪公开仓库 `chou8157/agent-workflow`。发布与版本治理第一期见 `W-20261125-release-governance`；维护说明见 `docs/releasing.md`，发布与实际安装分别安排。

## 禁止事项

- 禁止把推断写成确认事实。
- 禁止伪造测试或验收结果。
- 禁止无确认大幅改写已有入口文件或安装版 skill。
- 禁止静默迁移或删除旧工作流目录。
- 多个进行中工作项而用户未指定目标时，必须先询问，不能猜测。
