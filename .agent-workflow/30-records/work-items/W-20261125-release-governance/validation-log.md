# 验证记录

## 2026-11-25：第一批发布治理

| 验证 | 结果 |
| --- | --- |
| `python3 -B -m pytest experiments/frontier/test_release_governance.py experiments/frontier/test_release_package.py experiments/frontier/test_release_update.py -q -p no:cacheprovider` | 72 passed |
| `python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider` | 657 passed, 38 skipped，Python 3.8.3 |
| 源码及候选包 `quick_validate.py` | 均通过 |
| 发布脚本、测试及三个基础脚本的 Python 3.8 编译 | 通过；缓存写入临时目录 |
| Python 3.12 独立候选校验 | 1.1.0，84 个交付文件，通过 |
| CI YAML、四段 shell 语法与五份公开/方案文档引用 | 通过，无失效本地链接 |
| `check_workflow.py . --require-work-items --json` | ok=true，issues=[] |
| `check-release --require-clean --expected-tag v1.1.0` | 当前未提交源码被正确拒绝，退出码 2 |
| 压缩包独立解压，真实 beta 安装副本 -> 候选 -> 回滚 | 通过；重复更新为 unchanged；项目和真实安装文件未变 |
| 包内容对照当前 beta | 原包 80 个文件一致，仅 release_package.py 变化，新增三个发行文件 |
| `git diff --check` | 通过 |

38 项跳过为服务环境开关 2 项、PostgreSQL 环境 18 项和 Neo4j 环境 18 项。远端 CI 和 Linux 实机执行未在本轮完成。

原始完整回归 XML 位于 `/private/tmp/agent-workflow-release-governance-20261125/tests.xml`；可复核结果与摘要保存在 `verification.json`。压缩包与候选差异均针对本次实际生成产物。
