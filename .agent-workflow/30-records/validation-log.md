# 验证记录

## 记录规则

- 只记录真实执行过的测试、命令或人工验收。
- 未验证时写明原因和建议补验动作。

## 记录

### 2026-07-04 - 脚本 TDD 验证

- 验证对象：`check_workflow.py` 和 `scaffold_workflow.py`。
- 验证方式：`python3 -m pytest /private/tmp/agent-workflow-tdd -q`。
- 结果：`5 passed`。
- 未覆盖风险：测试目录在 `/private/tmp`，不是项目内长期测试套件。

### 2026-07-04 - Skill 基础校验

- 验证对象：`agent-workflow/` skill 结构。
- 验证方式：`python3.10 /Users/yizhoucp/.codex/skills/.system/skill-creator/scripts/quick_validate.py agent-workflow`。
- 结果：`Skill is valid!`。
- 未覆盖风险：只校验基础格式，不代表真实项目效果。

### 2026-07-04 - 本地前向测试

- 验证对象：初始化、迁移映射、记录沉淀三个典型场景。
- 验证方式：使用 `/private/tmp` 中的模拟项目执行脚手架、自检和手工记录流程。
- 结果：init、migrate、record 三类本地模拟均通过。
- 未覆盖风险：不是独立子智能体实测，也不是真实业务项目。

### 2026-07-06 - 中文化修复验证

- 验证对象：中文化后的本地版和安装版 `agent-workflow`。
- 验证方式：
  - `python3.10 .../quick_validate.py agent-workflow`
  - `python3 -m pytest /private/tmp/agent-workflow-tdd -q`
  - `python3 -m py_compile agent-workflow/scripts/check_workflow.py agent-workflow/scripts/scaffold_workflow.py`
  - 对安装版执行英文主体复扫。
- 结果：skill 校验通过，测试 `5 passed`，脚本编译通过，安装版未发现明显英文说明段落残留。
- 未覆盖风险：仍保留必要英文文件名、目录名、命令参数和代码标识符。

### 2026-07-06 - 当前项目工作流自检

- 验证对象：当前项目 `AGENTS.md` 和 `.agent-workflow/` 结构。
- 验证方式：`python3 agent-workflow/scripts/check_workflow.py . --json`。
- 结果：通过，输出 `ok: true`，`issues: []`。
- 未覆盖风险：自检只验证结构完整性，不验证真实项目试用效果。

### 2026-07-15 - 多工作项与升级能力验证

- 验证对象：任务块、版本化升级脚本、当前项目工作流结构和 skill 格式。
- 验证方式：
  - `python3 -m pytest tests -q`
  - `python3 -m py_compile agent-workflow/scripts/check_workflow.py agent-workflow/scripts/scaffold_workflow.py agent-workflow/scripts/task_context.py agent-workflow/scripts/upgrade_workflow.py`
  - `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`
  - `python3 agent-workflow/scripts/upgrade_workflow.py . status --json`
  - `python3.10 /Users/yizhoucp/.codex/skills/.system/skill-creator/scripts/quick_validate.py agent-workflow`
- 结果：测试 `7 passed`；脚本编译、严格结构自检、升级状态和 skill 格式校验均通过。
- 未覆盖风险：未在真实业务项目试跑任务切换、升级建议人工合并和 Git/worktree 适配。

### 2026-07-16 - 安装版同步验证

- 验证对象：Codex skills 安装版 `agent-workflow`。
- 验证方式：安装版 `quick_validate.py` 与排除 `__pycache__/` 的本地/安装版目录对比。
- 结果：安装版格式校验通过，目录内容无差异。
- 未覆盖风险：重启 Codex 后的真实项目试跑尚未执行。

### 2026-09-10 - GitHub 基线与接手验证

- 验证对象：Git 仓库状态、项目测试、工作流结构、工作流版本和 skill 格式。
- 验证方式：
  - `git status --short --branch`、`git remote -v`、`git log -1`
  - `python3 -m pytest tests -q`
  - `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`
  - `python3 agent-workflow/scripts/upgrade_workflow.py . status --json`
  - `python3.10 /Users/yizhoucp/.codex/skills/.system/skill-creator/scripts/quick_validate.py agent-workflow`
  - 排除缓存目录后对比本地 `agent-workflow/` 与 Codex 安装版
- 结果：`main` 跟踪 `origin/main`；测试 `7 passed`；严格结构自检通过；工作流版本为 2 且已是最新；skill 格式有效；接手更新前源码与安装版无差异。
- 未覆盖风险：尚未执行真实业务项目的完整闭环试跑。
