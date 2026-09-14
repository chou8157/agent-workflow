---
name: agent-workflow
description: 创建、使用、记录、优化、自检和迁移项目智能体工作流系统。适用于用户要求接手项目、初始化项目、创建或集成 AGENTS.md、生成 .agent-workflow/、记录/归档/沉淀开发进展、更新工作流规则、以后都这样、优化规则、自检、迁移旧 agent_docs/ 或 stack-workflow 目录，以及管理多项目/上下游/共享工作流的场景。
---

# 智能体工作流

使用本 skill 为项目创建和维护一套可控的 智能体工作流。核心产物是分层的 `.agent-workflow/` 目录；`AGENTS.md` 是项目根目录入口，必须完整但不要承载长篇项目百科。项目公共知识只保留一份；需求、任务和缺陷使用工作项目录隔离各自上下文。

## 第一步

先阅读 `references/operating-model.md`，确认模式路由和安全边界；然后只阅读当前模式对应的 reference 文件。不要默认加载所有 reference，避免上下文膨胀。

## 模式路由

把用户的自然语言意图映射到内部模式：

- **init**：用户说“接手项目”“初始化工作流”“新项目”“创建 AGENTS.md”，或要求生成 `.agent-workflow/`。读取 `references/init-mode.md` 和 `references/document-structure.md`。
- **init shared**：用户提到“多项目”“上下游”“共享链路”“跨仓库工作流”。读取 `references/shared-workflow.md`。
- **use**：用户要求按项目工作流开始开发、恢复上下文或查看当前状态。读取 `references/use-mode.md`。
- **record**：用户说“记录一下”“归档”“沉淀”“更新进展”。读取 `references/record-mode.md`。
- **improve**：用户说“以后都这样”“优化规则”“改工作流”“更新习惯”。读取 `references/improve-mode.md`。
- **check**：用户要求“自检”“检查工作流”“看结构是否完整”。读取 `references/check-mode.md`。
- **migrate**：用户要求迁移旧 `agent_docs/`、`stack-workflow/` 或其他工作流文档。读取 `references/migrate-mode.md` 和 `references/document-structure.md`。
- **upgrade**：用户要求把已生成工作流更新到最新结构、同步模板更新或查看工作流版本。读取 `references/upgrade-mode.md`。
- **delivery**：用户要求生成周报、阶段报告、交付、验收或发布说明。读取 `references/delivery-mode.md`。
- **capability**：用户要求按项目规模初始化、启用能力、精简目录或渐进升级。读取 `references/capability-mode.md`。
- **finalize**：本轮实际执行了开发、测试、状态变更或交付操作并准备结束时，默认执行工作流收口。读取 `references/finalize-mode.md`。纯讨论、阅读、规划和未产生项目事实的任务不触发。
- **memory**：用户要求沉淀、索引或恢复项目长期知识。读取 `references/memory-mode.md`，不得把草稿和交付中间物写入 Memory。

如果模式不明确，先问一个简短澄清问题，再写文件。

## 核心规则

- 默认优先处理单项目 `.agent-workflow/`；共享工作流是显式触发的次级能力。
- 必须保留已有 `AGENTS.md`。如果需要大幅改写，先给计划或 diff，等待用户确认。
- 禁止静默迁移或删除旧工作流目录。
- 项目关键事实必须标注来源和状态：`已确认`、`待确认` 或 `推断`。
- `validation-log.md` 只能记录真实执行过的测试、命令或人工验收。
- `current-status.md` 必须保持简短，历史进入 `progress-log.md`。
- 新初始化项目默认创建 `30-records/work-items/`。每个实际开发需求必须归属到一个工作项；公共规则、架构和跨任务记录不得复制到工作项中。
- 多个进行中工作项而用户未指定目标时，必须先询问；只有一个进行中工作项时可以默认选择，并说明选择结果。
- Git 分支和 worktree 是可选的代码状态适配能力，未明确启用时不得创建、切换或删除 Git 工作区。
- 实际开发、测试、状态变更或交付完成后默认执行 `finalize` 收口；纯讨论、阅读、规划和未产生项目事实的任务不触发。收口只写入可验证事实，不自动改写项目级判断或 Memory。

## 内置资源

- 模板位于 `assets/templates/`。
- 单项目模板位于 `assets/templates/.agent-workflow/`，入口模板为 `assets/templates/AGENTS.md`。
- 共享工作流模板位于 `assets/templates/.agent-workflow-shared/`。

## 内置脚本

需要稳定生成或检查目录结构时，优先使用脚本：

```bash
python3 path/to/agent-workflow/scripts/scaffold_workflow.py /path/to/project
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project
python3 path/to/agent-workflow/scripts/check_workflow.py /path/to/project --fix-low-risk
python3 path/to/agent-workflow/scripts/task_context.py /path/to/project create W-example --title "示例需求"
python3 path/to/agent-workflow/scripts/upgrade_workflow.py /path/to/project plan
python3 path/to/agent-workflow/scripts/upgrade_workflow.py /path/to/project apply-safe
```

`scaffold_workflow.py` 会创建缺失的模板文件。如果目标项目已有 `AGENTS.md` 且缺少工作流入口，它不会直接改写原文件，而是生成 `AGENTS.md.agent-workflow-suggestion` 供用户确认。

`check_workflow.py` 会检查必需结构。`--fix-low-risk` 可以补齐缺失的工作流目录和占位核心文件，但不会修改 `AGENTS.md`。

`task_context.py` 用于创建、列出、查看和更新工作项生命周期状态。生命周期状态唯一保存在工作项目录的 `.state.json`；旧工作项先用 `migration-check` 做只读检查。它不执行 Git 操作，也不替代记录模式中的真实事实判断。

`upgrade_workflow.py` 根据结构版本生成升级计划。`apply-safe` 只补齐缺失结构和版本标记；已有入口文档只生成建议文件，必须由用户确认后人工合并。

`delivery_context.py` 用于生成和发布独立外部交付物。草稿写入 staging，发布前检查内部路径、内部工作项 ID、未确认判断和敏感字段；published 版本不可原地覆盖。

`capability_context.py` 管理能力模块、依赖、profile 和只读升级建议。默认初始化使用 `minimum`，启用能力前由用户确认，检查和升级不会要求未启用模块存在。

收口时按 `references/finalize-mode.md` 执行：更新目标工作项的状态、进展和真实验证记录；项目级状态、长期 Memory 和外部交付物不因普通开发自动改写。

## 输出要求

向用户汇报时保持简洁，并说明：

- 创建或修改了什么。
- 有哪些内容故意没有修改。
- 哪些文件需要用户确认。
- 如何验证了工作流。
