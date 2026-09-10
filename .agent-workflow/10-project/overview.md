# 项目概览

## 基本信息

- 项目名称：`agent-workflow`
- 项目类型：Codex skill 开发项目
- 主要技术栈：Markdown 文档、Python 脚本、Codex skill 目录结构
- 运行入口：`agent-workflow/SKILL.md`
- 脚本入口：`agent-workflow/scripts/check_workflow.py`、`agent-workflow/scripts/scaffold_workflow.py`
- 安装目标：`/Users/yizhoucp/.codex/skills/agent-workflow`

## 当前理解

- 本项目用于设计、开发和维护 `agent-workflow` skill。（状态：已确认；来源：当前会话产物和文件结构）
- `agent-workflow/` 是 skill 本体，包含触发说明、模式 reference、模板资产和辅助脚本。（状态：已确认；来源：文件结构）
- `CONTEXT.md` 和 `docs/adr/` 是需求澄清阶段留下的领域模型和决策记录。（状态：已确认；来源：当前会话产物）
- 当前项目已安装到 Codex 本地 skills 目录，重启 Codex 后可通过 `$agent-workflow` 调用。（状态：已确认；来源：安装和校验命令）

## 接手入口

新 session 建议按顺序阅读：

1. `AGENTS.md`
2. `.agent-workflow/README.md`
3. `.agent-workflow/30-records/current-status.md`
4. `agent-workflow/SKILL.md`
5. `agent-workflow/evaluation-notes.md`

## 未知项

详见 `unknowns.md`。
