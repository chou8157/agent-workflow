# 当前状态

## 项目状态（结构化）

```yaml
project_status: maintenance
current_phase: maintenance
primary_work_item: W-20261125-release-governance
updated_at: 2026-11-26
```

以上字段用于机器读取；项目目标、阶段判断、风险和下一步仍记录在下文。

## 基本信息

- 最近更新：2026-11-26
- 当前目标：开发并稳定 `agent-workflow` Codex skill，用于生成、使用、记录、改进、自检、迁移和恢复多工作项上下文。
- 当前阶段：`1.1.0` 已正式发布；本机安装仍保持 `1.1.0-beta.1`，未自动更新。此前已采用的 beta 包和 v5 备份保留原样。
- 版本边界：当前发行包模板结构为 v6，本仓库原有自用记录结构仍为 v5；本次不批量迁移任何项目。

## 已完成

- 2026-11-25 完成第一批版本集中、发行信息与一致性检查、公开文档和 CI 配置；完整回归 657 项通过、38 项专用环境跳过。候选与真实 beta 副本更新/回滚通过，详见 `W-20261125-release-governance`。
- 2026-11-25 完成原主线 v5 备份：标签 `v5-20261125` 对应 `31989c7`，本机压缩包 184 个受 Git 管理的文件均与原提交一致。
- 重新构建实验发行包，确认与原发行包及本机安装版逐文件一致；安装版为 `1.1.0-beta.1`，无需更新。
- 前次主线切换回归 `641 passed, 38 skipped`，实验工作流检查通过；不作为本轮新增功能的验收结果。
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

1. 如需使用正式版，再单独安排本机安装更新并核对结果。
2. 后续按计划评估统一升级入口和文档自动合并，进入 `1.2.0-beta` 预览规划。

## 当前阻塞

- 无明确阻塞。

## 当前风险摘要

- 三个外部案例尚未迁移或试跑；这不是当前版本发布阻塞，而是后续兼容性验证范围。
- 本地源码分为基础工作流和多项目模块，必须组合构建发行包；安装内容变化需重新核对，不能只比较版本号。
- 38 项服务环境、PostgreSQL 和 Neo4j 专用测试本轮跳过；跨机器并发、真实硬件断电不在本轮验收范围。
- CI 已新增配置，远端矩阵尚未执行；开源许可证策略仍待后续治理。产品版本、发行包模板结构版本与各项目现有记录结构分别管理。

## 工作项摘要

- 进行中的工作项：无。
- 最近完成：`W-20261125-release-governance`，第一批发布治理与本地候选验证；不代表已发布。
- 最近完成：`W-20261125-mainline-promotion`，实验版主线采用、v5 备份与安装核对。
- 最近完成：`W-20260715-multi-work-items`。
- 最近完成：`W-20260715-workflow-upgrade`。
- 跨任务阻塞：无。
