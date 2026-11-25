# agent-workflow

用于创建、使用、记录、检查、迁移和持续改进项目智能体工作流的 Codex Skill。

它以项目根目录的 `AGENTS.md` 为入口，并使用分层的 `.agent-workflow/` 目录保存项目规则、项目理解、质量门禁与工作项上下文；避免只依赖会话记忆来承接开发工作。

## 当前版本

当前 `main` 采用 `1.1.0-beta.1`，发行包的工作流结构版本为 `6`。2026-11-25，用户确认实际使用正常后，将实验提交纳入主线；本次保留原版本号和发行包内容。产品名和日常调用继续使用 `agent-workflow`，支持技能程序连续更新、恢复与回滚、已有项目增量升级、本地活动和可选多项目汇总。版本变化见 [CHANGELOG.md](CHANGELOG.md)。

合并前的主线（产品 `1.0.0` / 结构 `v5`）保存在 Git 标签 `v5-20261125`，对应提交 `31989c7`。本机另保留源码压缩包，详见 [主线切换记录](.agent-workflow/30-records/work-items/W-20261125-mainline-promotion/current-status.md)。

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

- `agent-workflow/`：基础工作流源码、参考流程、模板和 Python 脚本。
- `experiments/frontier/`：多项目运行模块、统一 Skill 入口及发行包构建脚本；完整安装包由两处源码组合生成。
- `tests/`：脚本自动化测试。
- `.agent-workflow/`：本项目自身的工作流与开发记录。
- `docs/adr/`：关键设计决策记录。
- `CONTEXT.md`：领域术语与设计背景。

## 本地验证

```bash
python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider
```

## 本地安装

当前版本使用完整发行包，构建及安装说明见 [RELEASE_USAGE.md](experiments/frontier/RELEASE_USAGE.md)。请使用组合构建后的发行包，单独复制仓库中的 `agent-workflow/` 不包含完整的多项目运行能力。首次安装使用 `install`；已有安装使用 `update-plan` 和 `update`，先结束旧写入，再按计划切换并保留备份。不要用直接覆盖复制替代更新，也不要为更新技能而重新初始化业务项目。

更新后新会话继续使用 `$agent-workflow`。项目结构升级先运行 `upgrade_workflow.py <项目> plan`，保留原文档、工作项与历史；冲突和建议单独处理，多项目关系不自动开启。

## 状态

2026-11-25 已完成主线快进合并。实验源码重新构建的发行包与本机安装版逐文件一致，回归结果为 `641 passed, 38 skipped`。本仓库既有工作流记录结构仍为 v5；发行包模板为 v6，其他项目也不会因合并自动迁移。当前交付状态见 [主线切换记录](.agent-workflow/30-records/work-items/W-20261125-mainline-promotion/current-status.md)。工作区外安装仍遵守会话授权和工具权限。
