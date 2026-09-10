# agent-workflow

用于创建、使用、记录、检查、迁移和持续改进项目智能体工作流的 Codex Skill。

它以项目根目录的 `AGENTS.md` 为入口，并使用分层的 `.agent-workflow/` 目录保存项目规则、项目理解、质量门禁与工作项上下文；避免只依赖会话记忆来承接开发工作。

## 能力

- 初始化或补充项目的 `AGENTS.md` 与 `.agent-workflow/`。
- 在开发、排障时按需读取项目工作流和目标工作项上下文。
- 记录进展、验证、风险与稳定决策。
- 检查工作流结构，并只自动修复低风险缺失项。
- 从旧工作流目录迁移，或安全升级既有工作流结构。

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

将 `agent-workflow/` 同步到 Codex 的本地 skills 目录后，重启 Codex 即可使用 `$agent-workflow`。安装目录依赖本机 Codex 配置；请勿在不确认的情况下覆盖已有安装版。

## 状态

当前版本已实现工作项上下文与工作流版本化升级能力；真实项目试跑仍在后续验证范围内。详见 [项目工作流状态](.agent-workflow/30-records/current-status.md)。
