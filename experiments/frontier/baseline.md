# 稳定版单节点基线

此记录只描述 `31989c7b909529f0f36d04558bba657f9b913c2f` 的现有能力，供前沿实验后续比对。原测试通过不等于网络自治验收通过。

## 已确认结果

- 审计日期：2026-10-10；实验分支：`codex/exp-frontier-workflow-20261009`。
- 产品版本：`CHANGELOG.md` 中的 `1.0.0`；模板结构版本：`WORKFLOW_VERSION=5`。
- 实际解释器：`/Library/Frameworks/Python.framework/Versions/3.8/bin/python3`，Python `3.8.3`；Python 平台报告为 `macOS-10.16-x86_64-i386-64bit`。
- `python3 -m pytest tests -q`：exit `0`，`29 passed in 0.80s`。运行时设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTEST_ADDOPTS='-p no:cacheprovider'`，避免工作树内缓存写入。
- 实验 worktree 的 `check_workflow.py --require-work-items --json`：exit `0`，`ok: true`，无问题。
- 补充执行 43 条命令，含环境读取、测试收集、7 个 CLI 帮助和隔离场景；43 条均获得预期 exit，17 项文件/状态观察一致。这不是 43 个新自动化测试，也不意味着所有命令 exit 为 `0`。
- `agent-workflow/`、`tests/` 和根 `AGENTS.md`、`README.md`、`CHANGELOG.md` 共 73 个文件已记录 SHA-256；逐文件与上述 HEAD 比较一致，审计前后内容不变。

机器证据见 [`evidence/baseline.json`](evidence/baseline.json)：包含命令参数、cwd、时间、exit、stdout/stderr、环境、原测试输出、测试收集清单、17 项观察和 73 个文件哈希。

本次无网络调用、无包安装、无 Git 写入，未修改稳定版 main 或安装版。除本记录及 JSON 外，全部写入 `/private/tmp/frontier-baseline-kgb6ps5w/`；审计辅助脚本位于 `/private/tmp/frontier_baseline_audit_20261010.py`，仅用于本次取证。

## 现有测试实际覆盖

已先阅读全部 4 个测试文件；写入均使用 `tmp_path`，`finalize` 内部最多执行只读 `git status --short`，没有真实外部项目或网络集成调用。共 26 个测试函数，参数化后 29 个用例。

| 测试文件 | 实际用例数 | 已覆盖行为 | 不能据此确认 |
| --- | ---: | --- | --- |
| `tests/test_capability_context.py` | 5 | 依赖闭包、minimum、保留既有文件、未知能力拒绝、scaffold/enable 路径一致 | 所有 profile 与 checker 一致、共享节点运行能力 |
| `tests/test_task_context.py` | 14 | 初始化入口、创建/查询/迁移状态、阻塞原因、归档不可重开、完成后重开、错误状态、入口修复、两种安全升级 | 多写入者冲突、崩溃恢复、真实旧项目迁移、跨项目因果一致性 |
| `tests/test_finalize_context.py` | 2 | 同一输入重复收口不再记录、不推断完成 | 测试真实执行、Git 变更精准归属、并发或中断时整组记录原子性 |
| `tests/test_delivery_context.py` | 8 | 独立正文/元数据、4 类内容拒绝、已发布正文不可覆盖、篡改检查、替代/撤回/归档 | 独立批准门禁、来源真实性、身份认证、跨节点发布幂等 |

原测试以 Python 函数调用为主；本次补充的 CLI 场景用于确认命令接口、exit code 和实际生成物，不能替代真实网络或外部项目验收。

## 单节点实际行为与接口

以下命令形状来自本次 `--help`；`<project>` 必须显式放在子命令之前。完整帮助保存在 JSON。

| 入口 | 当前可用接口 | 本次隔离实测 |
| --- | --- | --- |
| `scaffold_workflow.py` | `<project> [--profile minimum/standard/advanced] [--capability NAME] [--shared] [--shared-name NAME] [--overwrite]` | minimum 生成 core/work-items、版本 5；已有 AGENTS 保留并生成建议；advanced 的 checker 问题见下文 |
| `task_context.py` | `<project> create/list/show/set-status/migration-check/migration-apply` | 创建/列出；planned→in_progress→blocked→in_progress→completed→archived；缺少阻塞原因 exit 2；归档重开 exit 2 |
| `finalize_context.py` | `<project> <item_id> --summary TEXT [--test TEXT]` | 首次 recorded=true，重复 recorded=false；状态保留 in_progress；test 参数使用已实测 checker 结果 |
| `check_workflow.py` | `<project> [--require-work-items] [--json] [--fix-low-risk]` | minimum、工作项、发布物检查成功；待人工合并入口与 advanced 问题能够复现 |
| `upgrade_workflow.py` | `<project> status/plan/apply-safe [--json]` | 构造旧版 fixture；2 个安全动作、3 个建议文件；原入口逐字保留；版本更新到 5 后仍存在 review |
| `capability_context.py` | `<project> list/suggest/enable [CAPABILITY ...] [--profile NAME]` | 在 minimum 项目启用 delivery 及其 evidence 依赖 |
| `delivery_context.py` | `<project> generate/publish/approve/supersede/withdraw/archive` | draft 直接发布、拒绝原地覆盖、检查发布物、撤回、归档 |

`migration-check` 和 `migration-apply` 在当前源码的真实帮助中存在；其迁移行为由原测试覆盖。本次没有把其他版本或安装版接口当作当前事实。

## 已复现的不足及证据边界

1. **advanced 初始化后无法通过自检。** `scaffold_workflow.py:20` 将 `shared-workflow` 放入 advanced，但 `check_workflow.py:45` 的已知能力没有它，`check_workflow.py:107` 因此拒绝清单。隔离 fixture 的初始化 exit `0`，随后 checker exit `1`，首个问题为 `invalid_capabilities`，并回退为完整结构检查而产生额外缺失项。JSON 标签：`advanced_initialize`、`advanced_checker_schema_mismatch`。这是既有缺口，29 项原测试未覆盖。
2. **交付发布没有独立批准前置校验。** `delivery_context.py:96` 读取草稿并发布，`:107` 同时写入 `approved_at`。本次 draft 没有先运行 approve，publish 仍 exit `0`，随后 checker 通过。JSON 标签：`delivery_publish_without_explicit_approve`。批准时间只能证明字段被写入，不能证明真实批准事件发生。
3. **finalize 是记录器，不是验证执行器。** `finalize_context.py:40`、`:52` 直接接受并记录 `--test` 文本；执行过何种测试仍依赖调用者提供事实。其重复收口通过输入指纹处理；当前文件写入没有跨文件事务或并发协调。前者由源码和本次命令确认，后者为源码边界，未执行并发/故障注入。
4. **结构版本到 5 不代表升级闭环。** 本次 apply-safe 后，三个用户入口保持原文，status 的 `review_actions` 仍有 3 项，`up_to_date=false`，check 因入口未引用工作流而 exit `1`。这是安全升级的预期人工边界，不应被算作升级失败或全部完成。JSON 标签：`upgrade_remaining_review`、`upgrade_check_before_manual_entry_merge`。
5. **checker 只提供有限的本地一致性检查。** 它检查入口、启用能力对应文件、状态字段及发布物哈希；没有任务正确性、来源真实性、网络状态或跨节点一致性的证据。`ok: true` 仅说明本次本地检查范围通过。

## 对前沿实验的约束

- 当前稳定能力可作为单节点文件适配层：渐进初始化、状态约束、人工审阅升级、事实记录和本地交付生命周期。已有行为应保留明确兼容入口。
- 后续验证首先复跑 29 项原测试、minimum CLI 主路径及文件哈希比较；对有意修改的文件单独审阅差异。73 个哈希用于定位改变，并非禁止经过授权的演进。
- 新网络自治必须拥有独立验收：节点身份与信任、并发冲突、事件因果关系、离线重放、重试去重、崩溃恢复、权限与真实批准、跨项目副作用幂等、知识传播和证据链。
- 本次没有执行这些网络场景，也没有运行真实外部项目。将上面的本地测试计数计入网络自治通过率会混淆证据范围。
- advanced 自检与批准前置校验应列为已知基线问题；不能把它们当作前沿实验新引入的回归，也不能因原测试通过而忽略。

## 恢复指针

1. 阅读本文件与 `evidence/baseline.json` 的 `summary`、`observations`、`source_sha256`。
2. 需要原始命令时按 `commands[].label` 定位；临时 fixture 尚保留，但长期恢复以仓库内 JSON 为准。
3. 工作项与项目状态收口由主执行者统一完成，基线审计子任务不改写这些公共记录。
