# 文档结构

## 单项目默认结构

```text
AGENTS.md
.agent-workflow/
  WORKFLOW_VERSION
  README.md
  00-core/
    workflow.md
    principles.md
    disclosure.md
    preferences.md
  10-project/
    overview.md
    architecture.md
    conventions.md
    dependencies.md
    unknowns.md
  15-modules/
    README.md
    module-template.md
  20-gates/
    quality-gates.md
    task-gates.md
    safety-gates.md
  30-records/
    current-status.md
    progress-log.md
    validation-log.md
    decision-log.md
    risk-log.md
    pending-fixes.md
    adr/
    work-items/
      README.md
      W-<id>/
        README.md
        work-item.md
        current-status.md
        changes/
        progress/
```

## 文件职责

- `README.md`：工作流总入口，说明按什么任务读什么文件。
- `00-core/`：稳定流程、原则、渐进披露和用户偏好。
- `10-project/`：项目初版理解、架构、规范、依赖和未知区域。
- `15-modules/`：深读模块后的轻量索引，不替代源码阅读。
- `20-gates/`：质量、任务类型和高风险安全门禁。
- `30-records/`：项目公共的当前状态、进展、验证、决策、风险、待修复项和 ADR。
- `30-records/work-items/`：需求、任务和缺陷的独立恢复上下文。工作项继承项目公共规则，不复制 `00-core/`、`10-project/`、`15-modules/` 或 `20-gates/`。

## 命名与语言

- 文件名默认英文。
- 正文默认中文。
- 规则语气区分 `必须`、`默认`、`建议`、`禁止`。
- 关键事实标注来源和状态：`已确认`、`待确认`、`推断`。
- `WORKFLOW_VERSION` 表示工作流目录结构版本；模板新增结构或路由规则时，必须同时提供可审阅的升级路径。
