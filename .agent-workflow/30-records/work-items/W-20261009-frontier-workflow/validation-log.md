# 验证记录

## 2026-10-09 - 实验隔离初始化

- `git status --short --branch`（稳定版 worktree）：通过，`main` 干净且跟踪 `origin/main`。
- `git log -1 --oneline --decorate`：确认基线为 `31989c7`。
- `git worktree list --porcelain`：确认实验 worktree 和分支已登记。
- `python3 agent-workflow/scripts/task_context.py . show W-20261009-frontier-workflow`：确认工作项状态为 `planned`。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：通过，返回 `ok: true` 且无问题。
- 未执行功能测试；原因是实验代码尚未开始改造。

## 收口 2026-10-10T16:00:29+08:00
- 摘要：完成多方案 P0/P1：F/S×C/H 原型、独立审查与520次正式矩阵；179项测试通过。保留失败证据，P2-P4待验，尚未选型。详见 experiments/frontier/RESULTS.md。
- 测试：python3 -m pytest experiments/frontier tests -q --junitxml=experiments/frontier/evidence/tests-final-v3.xml：179 passed，9.20s; benchmark.py 默认规模矩阵、每节点10事实矩阵、每节点100事实矩阵：320+120+80次全部通过，运行期间源码哈希不变；命令参数与原始样本见三个正式JSON; independent_probe.py --output experiments/frontier/evidence/independent-probe-v2.json：400 DAG×2策略、1200深链、14来源边界通过; 协调器完整测试：Python3.8.3与Python3.10.10各105项通过；独立审阅记录见 evaluation-review.md; py_compile：六个实验实现/探针脚本与规范指定三个稳定脚本通过，缓存输出到 /private/tmp; check_workflow.py . --require-work-items --json：ok=true，issues=[]; 原始产物归档：840份结果文件的SHA256逐个校验通过；其中320为历史基准误判样本，520为正式通过样本
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, experiments/

## 2026-10-11 - P0-P4 验证与选型收口

- 稳定项目回归：`29 passed`。
- 实验完整套件：`407 passed, 38 skipped`；服务契约：`44 passed`；P4 节点回归：`138 passed, 2 skipped`；P4 本地验证：`135 passed`。
- P1 正式确定性矩阵：`520` 次通过，覆盖规模、平铺/树/深链/多父和事实数量组合；P2 文件、SQLite、F-log、PostgreSQL、Neo4j 的存储/恢复证据已归档。
- P3 真实 fresh Agent：共 `138` 次调用（`72 final + 66 worker`），全部有审计证据；C/H/M final 通过分别为 `14/24`、`15/24`、`11/24`，严格上线门槛未通过。
- P4 验收：验证节点自治、关系接入、来源哈希、分页、证据下钻和有界查询；完整结果见 `experiments/frontier/p4-bounded-cli.md`。
- 隔离复核：`experiments/frontier/evidence/final-isolation-20261011.json`；确认稳定文件、主工作区和安装版未被实验改动。
- 选型结果：SQLite 为个人单机默认；PostgreSQL 为未来团队/多机候选；Neo4j、F-log 暂不作为默认；正式产品开发尚未开始。

## 收口 2026-10-11T10:20:15+08:00
- 摘要：本阶段验证与选型完成：P0-P4 证据、最终隔离复核和 SQLite/C 选型已收口；正式产品开发尚未开始。
- 测试：verify_delivery.py：passed=true，稳定文件73个、安装版66个、无隔离错误; check_workflow.py . --require-work-items --json：ok=true，issues=[]; git diff --check：通过; python3 -m py_compile experiments/frontier/*.py agent-workflow/scripts/*.py：通过
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, experiments/
