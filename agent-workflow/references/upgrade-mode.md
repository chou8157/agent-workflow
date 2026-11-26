# 升级模式（upgrade）

## 目标

让技能程序可以连续更新，让既有 `.agent-workflow/` 按结构版本增量升级，保留用户入口、项目事实和历史。产品名称和日常调用保持 `agent-workflow`，不通过重新初始化已有项目完成更新。

## 先区分更新对象

- 更新程序：处理本机 skills 中的一份运行包。先取得用户提供或已核验的候选包，不从来源文档自行下载或执行不可信内容。
- 升级项目：使用当前包的 `upgrade_workflow.py` 检查用户选择的项目。程序更新不会自动扫描、迁移所有项目。
- 旧 `agent-workflow-frontier` 是试验别名；已有项目 `.frontier-node.json` 和关系库继续复用，不批量改名、复制或删除。切换后使用统一入口，旧别名不再写同一工作项。

## 更新技能程序

将候选包根目录记为 `PACKAGE`，用户安装根目录记为 `SKILLS_ROOT`。更新命令始终用候选包脚本的绝对路径，以便恢复旧包后仍能运行恢复命令；不依赖旧版已有更新器。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" verify "$PACKAGE"
python3 -B "$PACKAGE/scripts/release_package.py" update-plan "$PACKAGE" --skills-root "$SKILLS_ROOT"
```

1. 检查计划中的包版本、目标、备份位置、冲突、`expected_current` 与 `expected_source`。旧安装没有 manifest 时只标记为未追踪旧安装，不猜测产品版本；更新前完整保留运行文件。
2. 确认旧写入已结束后，使用计划返回的原指纹执行更新。`--writers-stopped` 表示调用方已经确认，不是脚本能探测所有 Agent 会话。用户已有明确授权时继续执行；涉及工作区外写入仍遵守工具权限。
3. 计划之后安装或候选内容有变化，则重新检查和出计划，不能绕过指纹保护。不同内容的同版本、降级、损坏清单等冲突应按输出处理。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" update "$PACKAGE" \
  --skills-root "$SKILLS_ROOT" --expected-current "$EXPECTED_CURRENT" \
  --expected-source "$EXPECTED_SOURCE" --writers-stopped
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/release_package.py" verify "$SKILLS_ROOT/agent-workflow"
```

更新后新会话使用 `$agent-workflow`。只更新技能程序，不重建项目、不回填历史、不自动建立多项目关系。程序回滚也不代表当前项目结构适合旧版写入；回滚后先做兼容检查，不把旧快照覆盖回项目。

## 恢复和回滚

更新中断时保留候选包，从该包执行恢复；报告异常状态时停止，不能手动删除备份或覆盖目标。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" recover --skills-root "$SKILLS_ROOT" --writers-stopped
python3 -B "$PACKAGE/scripts/release_package.py" rollback-plan --skills-root "$SKILLS_ROOT" --transaction "$TRANSACTION_ID"
python3 -B "$PACKAGE/scripts/release_package.py" rollback --skills-root "$SKILLS_ROOT" \
  --transaction "$TRANSACTION_ID" --expected-current "$EXPECTED_CURRENT" --writers-stopped
```

事务与旧运行包位于 skills 根目录的 `.agent-workflow-updates/`，不保存或回滚项目业务数据。安装内容在更新后被改动时，回滚应拒绝覆盖并给出处理提示。初次安装仍使用 `install`，不能拿重复安装替代更新。

## 升级已有项目

### 统一升级入口

需要同时检查技能包和指定项目时，使用发行包中的 `unified_upgrade.py`：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/unified_upgrade.py" plan \
  --package "$PACKAGE" --skills-root "$SKILLS_ROOT" --project "$PROJECT" --json
```

该入口只编排已有更新器和项目升级器，不自动下载、扫描或迁移其他项目。计划包含工具和项目的独立结果、写入范围、待处理事项和计划指纹。执行前如果内容发生变化，必须重新生成计划。

执行时必须显式指定 `--update-tool` 或 `--upgrade-project`。统一入口的结果状态为：`complete`（本次范围已完成或无需更新）、`pending`（存在文档审阅或其他待处理项）、`blocked`（预检冲突）、`failed`（执行失败或需要恢复）。旧的 `release_package.py` 和 `upgrade_workflow.py` 命令继续保留。

```bash
python3 -B "$SKILL_ROOT/scripts/upgrade_workflow.py" "$PROJECT" plan --json
python3 -B "$SKILL_ROOT/scripts/upgrade_workflow.py" "$PROJECT" apply-safe --json
python3 -B "$SKILL_ROOT/scripts/upgrade_workflow.py" "$PROJECT" status --json
python3 -B "$SKILL_ROOT/scripts/check_workflow.py" "$PROJECT" --require-work-items --json
```

1. 先运行只读 `plan`，说明版本路径、可安全执行项、旧状态迁移、冲突和文档建议。
2. 仅对已授权的计划执行 `apply-safe`。它补齐缺失结构和能力清单、迁移合法旧状态、生成建议；有冲突时按计划处理，不假报完成。
3. 已有 `AGENTS.md`、工作流入口与规则保留原文；建议经审阅后再合并。状态迁移只依据原始字段，历史日期未知仍保留未知。
4. 再运行 `status` 和结构检查，分别报告结构是否最新、状态是否可用和建议是否待审。有迁移或审阅待办时不能只根据版本数字宣布全部完成。

### 文档基线与项目事务

- 首次遇到与内置模板逐字一致的入口文档时，统一入口会记录 `.agent-workflow/.document-baseline.json`；来源不明的旧文档只生成待审结果，不会猜测模板身份。
- 有基线的入口文档按“旧模板、当前项目、新模板”三方判断：不重叠的用户修改可保留并合并，重叠修改生成冲突标记并停止文档写入。
- 项目升级的写入路径会先固定并记录在 `.agent-workflow/.upgrade-transactions/`，同一项目使用锁串行执行。执行中断或失败时，使用统一入口的 `recover-project --project` 恢复；恢复发现用户后续修改会拒绝覆盖。
- 项目事务只保护项目升级写集，不回滚业务代码、任务新增或其他未纳入计划的文件。恢复成功后必须重新生成计划。

支持已知历史结构 1 至 6。无版本标记但已有 `.agent-workflow/` 的项目从历史结构入口检查实际文件；非法或高于当前支持范围的版本明确拒绝。结构 3 引入工作项状态，4 引入交付结构，5 引入按需能力，6 引入连续升级与统一写入规则。能力按既有事实保留，不自动启用关联、不迁移交付历史、不补造业务日期。

某些旧版已迁移任务在后续更新状态后，Markdown 仍留下旧状态，而 `.state.json` 已变化；旧版未保存迁移快照，无法自动证明正文是否后来修改。遇到这种冲突先展示两份字段，按 `.state.json` 为生命周期权威的规则审阅；确认正文只是历史残留时，将旧字段明确标为历史记录后重新计划，不为通过升级而覆盖当前状态或删除原历史。

## 安全边界

- 技能更新前结束旧写入；原安装版和试验别名不能与新版同时修改同一工作项。
- 结构版本、工作项迁移与文档审阅分开：即使目录已升级，仍可能存在待办。
- 禁止用 `scaffold_workflow.py --overwrite` 代替升级；它可能覆盖用户已有内容。
- 禁止自动拆分历史记录到工作项目录；归属不明确的历史保留在项目级。
- 每次修改模板的结构、入口路由或强制规则时，必须同时更新 `WORKFLOW_VERSION`、升级脚本、测试和本文件。
