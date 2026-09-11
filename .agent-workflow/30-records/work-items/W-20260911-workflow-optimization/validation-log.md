# 验证记录

## 2026-09-11：当前项目自托管状态试用

- `python3 -m pytest tests -q`：`14 passed`。
- 工作项状态转换：`in_progress -> blocked -> in_progress -> completed -> in_progress`，通过。
- `blocked` 无原因拒绝：由自动化测试覆盖，通过。
- 重新打开已完成工作项：首次发现 `completed_at` 清理缺陷，修复后回归通过。
- 三个外部案例：本轮未修改，仅保留此前只读扫描结果。
