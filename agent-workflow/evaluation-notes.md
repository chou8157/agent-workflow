# 评估记录

## 2026-07-04 - 基线评估与小优化

评估方式：干跑评估 + 本地前向测试。

### 测试 Prompt

详见 `test-prompts.json`。

### 基线分数

- 小优化前：84.2 / 100
- 主要缺口：中文触发词覆盖不足、记录模式缺少检查清单、半残缺 `.agent-workflow/` 的自检指导不够明确。

### 已完成优化

- 在 `SKILL.md` frontmatter description 中补充中文触发词。
- 在 `references/record-mode.md` 中补充记录检查清单。
- 在 `references/check-mode.md` 中补充半残缺 `.agent-workflow/` 的处理规则。

### 验证记录

- `python3.10 .../quick_validate.py agent-workflow`：通过。
- `python3 -m pytest /private/tmp/agent-workflow-tdd -q`：5 个测试通过。
- `python3 -m py_compile agent-workflow/scripts/check_workflow.py agent-workflow/scripts/scaffold_workflow.py`：通过。
- 前向测试 init：通过。
- 前向测试 migrate 映射且不迁移：通过。
- 前向测试 record 最小记录、验证和模块索引：通过。

### 残留风险

- 前向测试仍是本地模拟，不是独立子智能体实测。
- `record` 仍主要靠文档流程约束，暂未提供专门的记录生成脚本。

## 2026-07-06 - 中文化修复

背景：用户指出当前项目文件内容仍有大量英文，不符合“项目内容中文为主”的要求。

处理原则：面向 智能体或用户阅读的说明、评估记录、脚本帮助文本和脚本输出改为中文为主；代码标识符、文件名、命令参数和必要的模式名保持英文。
