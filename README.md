# agent-workflow

用于创建、使用、记录、检查、迁移和持续改进项目智能体工作流的 Codex Skill。

它以项目根目录的 `AGENTS.md` 为入口，并使用分层的 `.agent-workflow/` 目录保存项目规则、项目理解、质量门禁与工作项上下文；避免只依赖会话记忆来承接开发工作。

## 当前版本

当前实验分支提供 `1.1.0-beta.1` 预览包，工作流结构版本为 `6`；原主线产品为 `1.0.0`。产品名和日常调用继续使用 `agent-workflow`。预览版补齐技能程序连续更新、恢复与回滚，已有项目按版本增量升级，并包含本地活动和可选多项目汇总。版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 能力

- 初始化或补充项目的 `AGENTS.md` 与 `.agent-workflow/`。
- 在开发、排障时按需读取项目工作流和目标工作项上下文。
- 记录进展、验证、风险与稳定决策。
- 检查工作流结构，并只自动修复低风险缺失项。
- 从旧工作流目录迁移，或安全升级既有工作流结构。
- 通过 `delivery` 管理可发布文档的来源快照、审批、发布、替代、撤回与归档。
- 通过 `capability` 按需启用模块，默认 `minimum`，不强制生成完整目录。
- 在实质开发、测试或交付结束时自动收口工作项记录；纯讨论不会触发收口。

## 目录

- `agent-workflow/`：可安装的 Codex Skill；包含入口、参考流程、模板和 Python 脚本。
- `tests/`：脚本自动化测试。
- `.agent-workflow/`：本项目自身的工作流与开发记录。
- `docs/adr/`：关键设计决策记录。
- `CONTEXT.md`：领域术语与设计背景。

## 本地验证

```bash
python3 -m pytest tests -q
```

## 本地安装

预览版使用完整发行包，构建及安装说明见 [RELEASE_USAGE.md](experiments/frontier/RELEASE_USAGE.md)。首次安装使用 `install`；已有安装使用 `update-plan` 和 `update`，先结束旧写入，再按计划切换并保留备份。不要用直接覆盖复制替代更新，也不要为更新技能而重新初始化业务项目。

更新后新会话继续使用 `$agent-workflow`。项目结构升级先运行 `upgrade_workflow.py <项目> plan`，保留原文档、工作项与历史；冲突和建议单独处理，多项目关系不自动开启。

## 状态

本分支与 main 隔离，真实项目不随发布自动迁移。实际安装状态和验证证据见 [连续升级工作项](.agent-workflow/30-records/work-items/W-20261016-versioned-upgrade/current-status.md)。工作区外安装仍遵守会话授权和工具权限。
