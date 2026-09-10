# AGENTS.md

## 项目概览

- 项目名称：`待补充`
- 项目类型：`待确认`
- 主要语言/框架：`待确认`
- 项目状态：见 `.agent-workflow/30-records/current-status.md`
- 需求/任务状态：见 `.agent-workflow/30-records/work-items/`

## 必须遵守

- 必须先阅读本文件，再按任务类型阅读 `.agent-workflow/` 中的相关文档。
- 必须保护用户已有改动，不得擅自回滚或覆盖未确认内容。
- 涉及真实环境、副作用、权限、安全、发布、数据迁移时，必须先确认方案、验证方式和回滚/止损策略。
- 有歧义时必须先提问确认，不得猜测。

## 智能体工作流入口

- 工作流总入口：`.agent-workflow/README.md`
- 项目状态：`.agent-workflow/30-records/current-status.md`
- 工作项：`.agent-workflow/30-records/work-items/`
- 任务流程：`.agent-workflow/00-core/workflow.md`
- 任务门禁：`.agent-workflow/20-gates/`
- 项目理解：`.agent-workflow/10-project/`
- 模块索引：`.agent-workflow/15-modules/`
- 记录沉淀：`.agent-workflow/30-records/`

## 默认工作方式

- 低风险任务可以直接执行并简要说明。
- 中风险任务先只读分析和给出方案，再执行。
- 高风险任务必须等待确认后执行。
- 深度阅读模块后，如用户要求记录，应更新 `.agent-workflow/15-modules/`。
- 每个实际开发需求必须归属到一个工作项；有多个进行中工作项而用户未指定时，必须先询问。
- 工作项只记录任务私有事实，公共规则、项目理解和跨任务记录只维护一份。

## 禁止事项

- 禁止把推断写成确认事实。
- 禁止伪造测试或验收结果。
- 禁止无确认大幅改写已有 `AGENTS.md`。
- 禁止静默迁移或删除旧工作流目录。
