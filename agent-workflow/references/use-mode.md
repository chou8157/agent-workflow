# 使用模式（use）

## 目标

在日常开发、排障或阅读前，按任务类型渐进加载项目工作流，避免上下文爆炸。

## 最小必读

1. `AGENTS.md`
2. `.agent-workflow/README.md`
3. `.agent-workflow/30-records/current-status.md`（项目公共状态）
4. 选择目标工作项后，读取 `30-records/work-items/<ID>/README.md`、`current-status.md` 和 `work-item.md`。

## 工作项选择

- 用户明确指定工作项 ID：直接恢复该工作项。
- 只有一个 `in_progress` 工作项：可以默认选择，并在回复中说明。
- 有多个 `in_progress` 工作项但未指定：先询问，不能读取任一任务的详细上下文。
- 没有进行中工作项且用户提出新的开发需求：先创建工作项，再开始开发。
- 项目初始化、工作流维护和跨任务架构治理可以保持项目级，不强行创建业务工作项。

## 按需读取

- 涉及执行流程：读 `00-core/workflow.md`。
- 涉及用户偏好：读 `00-core/preferences.md`。
- 涉及具体模块：读对应 `15-modules/*.md`，然后重新阅读源码确认细节。
- 涉及测试/验收：读 `20-gates/quality-gates.md`。
- 涉及副作用、发布、权限、真实环境：读 `20-gates/safety-gates.md` 和 `30-records/risk-log.md`。
- 涉及架构或规范：读 `10-project/architecture.md`、`10-project/conventions.md`。
- 涉及需求变更或历史追溯：按需读目标工作项的 `changes/`、`progress/` 和局部日志。
- 涉及 Git 代码状态：只读目标工作项的 `code-state.md`；未明确启用 Git 能力时不执行 Git 操作。

## 任务分级

- 低风险：可直接执行，完成后简要说明。
- 中风险：先只读分析和方案，再执行。
- 高风险：必须确认方案、验证方式和回滚/止损策略。
