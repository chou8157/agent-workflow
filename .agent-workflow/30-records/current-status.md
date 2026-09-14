# 当前状态

## 项目状态（结构化）

```yaml
project_status: maintenance
current_phase: release_consistency
primary_work_item: W-20260911-workflow-optimization
updated_at: 2026-09-14
```

以上字段用于机器读取；项目目标、阶段判断、风险和下一步仍记录在下文。

## 基本信息

- 最近更新：2026-09-14
- 当前目标：开发并稳定 `agent-workflow` Codex skill，用于生成、使用、记录、改进、自检、迁移和恢复多工作项上下文。
- 当前阶段：项目已完成状态统一、文档治理和能力渐进生成，并通过当前项目自托管试用，进入后续维护阶段。

## 已完成

- 完成需求澄清和领域建模，记录在 `CONTEXT.md`。
- 已形成 36 条设计决策，记录在 `docs/adr/0001...0036`。
- 创建 `agent-workflow/` skill 初版，包含 `SKILL.md`、`references/`、`assets/templates/`、`scripts/` 和 `agents/openai.yaml`。
- 使用 TDD 完成 `check_workflow.py` 和 `scaffold_workflow.py` 的核心行为测试。
- 完成达尔文式干跑评估、小优化和本地前向测试，记录在 `agent-workflow/evaluation-notes.md`。
- 已安装到 `/Users/yizhoucp/.codex/skills/agent-workflow`。
- 已修复英文内容过多的问题，当前面向阅读的文档和脚本输出已中文为主。
- 已为当前项目创建 `AGENTS.md` 和 `.agent-workflow/`，用于新 session 接手。
- 已将源码目录统一为 `/Users/yizhoucp/Documents/agent-workflow`，初始化 Git，并将 `main` 推送到公开仓库 `chou8157/agent-workflow`。
- 已补充仓库 `README.md` 和 `.gitignore`，缓存文件不纳入版本控制。

## 下一步

1. 根据后续使用反馈维护文档交付和能力模块边界。
2. 如有明确授权，再单独规划外部案例迁移。
3. 建立 CI 自动发布流程；安装版当前已与源码同步。

## 当前阻塞

- 无明确阻塞。

## 当前风险摘要

- 三个外部案例尚未迁移或试跑；这不是当前版本发布阻塞，而是后续兼容性验证范围。
- Git/worktree 代码状态适配尚未实现，当前第一期只覆盖任务文档上下文。
- 本地源码与 Codex 安装版依赖人工同步，后续迭代可能发生版本漂移。
- CI 和开源许可证策略仍待后续治理；产品版本与结构版本已通过 `CHANGELOG.md` 区分。

## 工作项摘要

- 进行中的工作项：无。
- 最近完成：`W-20260715-multi-work-items`。
- 最近完成：`W-20260715-workflow-upgrade`。
- 跨任务阻塞：无。
