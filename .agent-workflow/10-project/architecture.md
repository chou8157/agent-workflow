# 架构理解

## 当前架构概述

`agent-workflow` 是一个以文档和模板为主、少量 Python 脚本辅助的 Codex skill。`SKILL.md` 保持精简，负责触发和模式路由；详细流程拆分到 `references/`；可复制产物放在 `assets/templates/`；确定性的结构检查和脚手架生成由 `scripts/` 提供。

## 核心模块

| 模块 | 位置 | 作用 | 状态 | 来源 |
|---|---|---|---|---|
| Skill 入口 | `agent-workflow/SKILL.md` | 定义触发场景、模式路由、核心规则和脚本入口 | 已确认 | 文件结构 |
| 模式文档 | `agent-workflow/references/` | 拆分 init/use/record/improve/check/migrate/shared 等流程 | 已确认 | 文件结构 |
| 模板资产 | `agent-workflow/assets/templates/` | 提供 `AGENTS.md`、`.agent-workflow/` 和 `.agent-workflow-shared/` 模板 | 已确认 | 文件结构 |
| 自检脚本 | `agent-workflow/scripts/check_workflow.py` | 检查项目工作流结构，并可补齐低风险缺失项 | 已确认 | 脚本和测试 |
| 脚手架脚本 | `agent-workflow/scripts/scaffold_workflow.py` | 从模板生成单项目或共享工作流目录 | 已确认 | 脚本和测试 |
| 工作项脚本 | `agent-workflow/scripts/task_context.py` | 创建、列出、查看和更新工作项生命周期状态 | 已确认 | 脚本和测试 |
| 升级脚本 | `agent-workflow/scripts/upgrade_workflow.py` | 检查结构版本，补齐安全结构并生成入口文档建议 | 已确认 | 脚本和测试 |
| 评估记录 | `agent-workflow/evaluation-notes.md` | 记录达尔文式评估、小优化、验证和残留风险 | 已确认 | 文件内容 |

## 数据流 / 调用流

1. 用户通过自然语言或 `$agent-workflow` 触发 skill。
2. `SKILL.md` 判断模式，并指引读取对应 `references/*.md`。
3. 初始化或自检时，优先调用 `scripts/scaffold_workflow.py` 或 `scripts/check_workflow.py`。
4. 脚本从 `assets/templates/` 复制模板到目标项目。
5. 涉及开发需求时，智能体先选择 `30-records/work-items/<ID>/`，再按 `record-mode.md` 更新目标工作项和必要的模块索引。
6. 只有跨任务的事实才更新项目根 `30-records/`。

## 已知架构债务

- `record` 没有专用脚本，当前依赖文档流程和人工判断。（状态：已确认；来源：evaluation-notes）
- Git/worktree 代码状态适配尚未实现；当前工作项能力只隔离文档上下文。（状态：已确认；来源：当前开发范围）
- 当前项目不是 git 仓库，缺少版本追踪能力。（状态：已确认；来源：`git status` 失败）
