# 验证记录

## 2026-11-26：统一升级编排第一阶段

| 验证 | 结果 |
| --- | --- |
| `python3 -B -m pytest tests/test_unified_upgrade.py tests/test_versioned_upgrade.py -q -p no:cacheprovider` | 46 passed |
| `python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider` | 663 passed，38 skipped |
| Python 编译检查 | 通过 |
| `check_workflow.py . --require-work-items --json` | `ok=true` |
| Skill 快速校验 | `Skill is valid!` |
| 独立发行包构建、verify、入口帮助检查 | 通过；85 个 manifest 文件，包含统一入口 |
| 独立发行包统一计划验证 | 通过 |
| 本机安装更新 | 未执行，按用户要求保留 `1.1.0-beta.1` |
| 外部项目迁移 | 未执行 |

## 2026-11-27：公开安装文档与自动安装提示词

| 验证 | 结果 |
| --- | --- |
| `git diff --check` | 通过 |
| `python3 -B agent-workflow/scripts/check_workflow.py . --require-work-items --json` | `ok=true` |
| `python3 -B experiments/frontier/build_release.py check-release` | 通过；版本 `1.2.0`，源码存在未提交文档改动 |
| README 本地链接检查 | 通过 |
| 完整发行包构建与 `release_package.py verify` | 已在本轮 README 调整前验证通过；README 不进入发行包内容 |
| 本机安装更新 | 未执行，按用户要求保留 `1.1.0-beta.1` |
| Git checkpoint、标签、正式 Release、推送 | 未执行，等待单独授权 |

## 2026-11-26：文档与项目事务第二阶段

| 验证 | 结果 |
| --- | --- |
| `tests/test_document_baseline.py` | 5 passed |
| `python3.10 -m pytest tests experiments/frontier -q -p no:cacheprovider` | 668 passed，38 skipped |
| 本地候选包构建 | 通过；版本 `1.2.0`，manifest 文件 87 个 |
| 候选包 `release_package.py verify` | 通过 |
| 候选压缩包 | `/private/tmp/agent-workflow-1.2.0-local-candidate-final6.tar.gz`；SHA-256 `bb248f2457a5c6eec32ba5358bc3a0efa29aa605691017c7d2f2415b21579914` |
| 本机安装更新 | 未执行，按用户要求保留 `1.1.0-beta.1` |
| 外部项目迁移 | 未执行 |
