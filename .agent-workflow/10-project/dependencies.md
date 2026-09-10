# 依赖与外部系统

## 内部依赖

- `agent-workflow/assets/templates/`：脚手架脚本的模板来源。
- `agent-workflow/references/`：`SKILL.md` 的渐进式披露内容来源。
- `agent-workflow/scripts/`：自检和脚手架生成能力。

## 外部依赖

- Codex skills 目录：`/Users/yizhoucp/.codex/skills/agent-workflow`。
- Skill 创建工具：`/Users/yizhoucp/.codex/skills/.system/skill-creator/scripts/quick_validate.py`。
- Python：本机 `python3` 和 `python3.10`。
- pytest：用于运行 `/private/tmp/agent-workflow-tdd` 中的测试。

## 环境与副作用

- 写入 `/Users/yizhoucp/.codex/skills/agent-workflow` 属于工作区外写入，需要确认或授权。
- 重启 Codex 后才会加载已安装的 skill。

## 共享工作流弱引用

- 当前项目不属于多项目共享工作流。
- 共享目录位置：无。
