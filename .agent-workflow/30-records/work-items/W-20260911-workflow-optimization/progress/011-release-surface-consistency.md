# 011 - 发布面一致性复核

日期：2026-09-14

## 事实

- 全面复核发现入口 README、模板入口、行为提示、版本说明和若干历史状态未同步到结构版本 5。
- `capability_context.py` 与 `scaffold_workflow.py` 的能力路径定义不一致，可能导致新项目启用能力时生成空目录。
- 已统一能力 schema，新增 1.0.0 变更记录，扩充 delivery、capability、finalize 和发布门禁提示，并关闭已验证的旧未知项。

## 验证

- `python3 -m pytest tests -q`：29 passed。
- `check_workflow.py . --require-work-items --json`：通过。
- Python 脚本编译和 `git diff --check`：通过。

## 边界

- 本轮未写入 `/Users/yizhoucp/.codex/skills/agent-workflow` 安装版；该操作需要独立授权。
- 外部案例项目仍未迁移或试跑，不将本项目验证冒充外部兼容性验收。
