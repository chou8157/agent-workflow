# 验证记录

## 2026-09-11：当前项目自托管状态试用

- `python3 -m pytest tests -q`：`14 passed`。
- 工作项状态转换：`in_progress -> blocked -> in_progress -> completed -> in_progress`，通过。
- `blocked` 无原因拒绝：由自动化测试覆盖，通过。
- 重新打开已完成工作项：首次发现 `completed_at` 清理缺陷，修复后回归通过。
- 三个外部案例：本轮未修改，仅保留此前只读扫描结果。

## 2026-09-14：外部交付第一期试用

- 生成 `phase-report-20260914` staging 草稿：通过。
- 发布 `phase-report-20260914` published 版本：通过。
- 发布物元数据、内容哈希和内部泄露检查：通过。
- `python3 -m pytest tests -q`：`20 passed`。
- `check_workflow.py . --require-work-items --json`：`ok: true`。

## 2026-09-14：生命周期与五角色接入验证

- 临时项目完成 `draft -> approved -> published -> superseded -> archived`：通过。
- source snapshot、provenance 和内容哈希：通过。
- 发布物篡改、内部工作项 ID 和非法替代关系：均被检查工具拒绝。
- Memory 规则、Skill 路由、交付脚本和模板边界：已接入。
- 全量测试：`22 passed`。

## 2026-09-14：当前项目外部交付自托管试用

- 当前项目完成两个交付物的生成、批准和发布：通过。
- 已发布版本在来源文件变化后保持内容哈希不变：通过（Python `hashlib.sha256`）。
- 交付物替代、撤回和归档链路：通过。
- `check_workflow.py . --require-work-items --json`：`ok: true`。
- `python3 -m pytest tests -q`：`22 passed`。

## 2026-09-14：当前项目能力渐进自托管试用

- `capability_context.py suggest`：识别 `delivery` 能力。
- 启用 `core + work-items + delivery`：自动补齐 `evidence` 依赖，通过。
- 既有 `agent-workflow/SKILL.md` 哈希前后相同，未被覆盖。
- `check_workflow.py . --require-work-items --json`：`ok: true`。
- `upgrade_workflow.py . status --json`：版本 `5`，无待升级动作。
- `python3 -m pytest tests -q`：`26 passed`。

## 收口 2026-09-14T16:55:11+08:00
- 摘要：验证自动收口能力已在当前项目启用
- 测试：python3 -m pytest tests -q; python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json
- 变更文件：未检测到
