# 评估记录

> 本文件保留历史评估；当前产品版本与能力边界以根目录 `README.md`、`CHANGELOG.md` 和工作流状态为准。

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

## 2026-09-14 - 版本 1.0.0 发布面复核

- 自动化测试：29 项通过。
- 脚本编译、工作流结构检查、自动收口自托管试用通过。
- 补充 delivery、capability、finalize、状态唯一源和发布门禁提示覆盖。
- 统一 `scaffold_workflow.py` 与 `capability_context.py` 的能力路径定义，避免启用能力生成空目录或错误目录。
- 旧的“未实现/未试跑”条目均视为历史基线，不代表当前状态。

### `test-prompts.json` 验证边界

- 已完成 11 条提示的 JSON、唯一 ID、必需字段和能力覆盖检查。
- 已用真实 CLI 流程验证脚手架、能力启用、工作项创建、`finalize` 帮助和结构检查。
- 当前仓库没有自动驱动 Codex 会话逐条执行这些自然语言提示的测试 harness，因此不能把上述静态检查称为 11 条提示的语义前向测试；后续如接入独立评测运行器，应逐条记录模型输出和判定结果。

## 2026-07-06 - 中文化修复

背景：用户指出当前项目文件内容仍有大量英文，不符合“项目内容中文为主”的要求。

处理原则：面向 智能体或用户阅读的说明、评估记录、脚本帮助文本和脚本输出改为中文为主；代码标识符、文件名、命令参数和必要的模式名保持英文。
