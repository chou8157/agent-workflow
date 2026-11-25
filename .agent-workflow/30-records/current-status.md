# 当前状态

## 项目状态（结构化）

```yaml
project_status: maintenance
current_phase: mainline_maintenance
primary_work_item: W-20261125-mainline-promotion
updated_at: 2026-11-25
```

以上字段用于机器读取；项目目标、阶段判断、风险和下一步仍记录在下文。

## 基本信息

- 最近更新：2026-11-25
- 当前目标：开发并稳定 `agent-workflow` Codex skill，用于生成、使用、记录、改进、自检、迁移和恢复多工作项上下文。
- 当前阶段：用户确认 `1.1.0-beta.1` 实际使用正常，实验提交 `0c79386` 已快进纳入本地与远端主线；本次保留版本号和发行包内容。
- 版本边界：当前发行包模板结构为 v6，本仓库原有自用记录结构仍为 v5；本次不批量迁移任何项目。

## 已完成

- 2026-11-25 完成原主线 v5 备份：标签 `v5-20261125` 对应 `31989c7`，本机压缩包 184 个受 Git 管理的文件均与原提交一致。
- 重新构建实验发行包，确认与原发行包及本机安装版逐文件一致；安装版为 `1.1.0-beta.1`，无需更新。
- 本轮回归 `641 passed, 38 skipped`，实验工作流检查通过；未将跳过项计为通过。
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
3. 持续使用完整发行包构建与校验流程，按需求推进 CI 发布治理。

## 当前阻塞

- 无明确阻塞。

## 当前风险摘要

- 三个外部案例尚未迁移或试跑；这不是当前版本发布阻塞，而是后续兼容性验证范围。
- 本地源码分为基础工作流和多项目模块，必须组合构建发行包；安装内容变化需重新核对，不能只比较版本号。
- 38 项依赖专用环境或其他条件的测试本轮跳过；跨机器并发、真实硬件断电不在本轮验收范围。
- CI 和开源许可证策略仍待后续治理；产品版本、发行包模板结构版本与各项目现有记录结构分别管理。

## 工作项摘要

- 进行中的工作项：无。
- 最近完成：`W-20261125-mainline-promotion`，实验版主线采用、v5 备份与安装核对。
- 最近完成：`W-20260715-multi-work-items`。
- 最近完成：`W-20260715-workflow-upgrade`。
- 跨任务阻塞：无。
