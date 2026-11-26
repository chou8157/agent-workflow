# 使用与升级

## 安装前准备

使用完整发行压缩包，解压后应包含 `SKILL.md`、`scripts/`、`assets/` 和 `release-manifest.json`。新版还包含 `VERSION`、`release-info.json` 与 `release-notes.md`。

选择正式版或明确需要试用的预览版。源码 main 是集成主线，不代表每个提交都已正式发布。当前更新工具接收本地已解压包，不自动查询、下载远端最新版。

以下命令中，`PACKAGE` 是解压后的 `agent-workflow` 目录，`SKILLS_ROOT` 是你的技能安装根目录，`PROJECT` 是需要检查的项目。使用真实绝对路径，并对路径加引号。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" verify "$PACKAGE"
```

校验会检查清单和文件内容。新版还会检查包版本、发行信息和模板结构的一致性。哈希校验不能替代下载来源的确认。

## 首次安装

```bash
python3 -B "$PACKAGE/scripts/release_package.py" install "$PACKAGE" --skills-root "$SKILLS_ROOT"
```

安装后在新会话中使用 `$agent-workflow`。已有不同内容的同名安装应按下面的更新流程处理。

## 更新已安装的技能

先获取更新计划：

```bash
python3 -B "$PACKAGE/scripts/release_package.py" update-plan "$PACKAGE" --skills-root "$SKILLS_ROOT"
```

核对版本、目标目录和备份位置，将输出的 `expected_current` 与 `expected_source` 分别保存为下面的 `EXPECTED_CURRENT`、`EXPECTED_SOURCE`。确认使用旧技能写入项目的会话已经停止，再执行：

```bash
python3 -B "$PACKAGE/scripts/release_package.py" update "$PACKAGE" \
  --skills-root "$SKILLS_ROOT" --expected-current "$EXPECTED_CURRENT" \
  --expected-source "$EXPECTED_SOURCE" --writers-stopped
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/release_package.py" verify "$SKILLS_ROOT/agent-workflow"
```

计划生成后内容有变化，应重新生成计划。相同版本不同内容、损坏的包和普通更新中的降级会被拒绝。`--writers-stopped` 表示调用方已确认停止写入，不是程序自动检测全部会话。

更新只切换技能程序。已有项目、任务和关联关系保留，后续使用新会话加载更新后的技能。

## 检查或升级项目

需要同时检查技能包和指定项目时，可以使用统一入口。它只处理明确传入的范围：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/unified_upgrade.py" plan \
  --package "$PACKAGE" --skills-root "$SKILLS_ROOT" --project "$PROJECT" --json
```

计划会返回工具和项目的独立结果、计划指纹以及待处理事项。计划生成后如果候选包、安装内容或项目内容发生变化，旧计划指纹会失效。

执行时必须明确选择范围。下面的示例只升级项目，不更新本机技能：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/unified_upgrade.py" apply \
  --project "$PROJECT" --upgrade-project --plan-fingerprint "$PLAN_FINGERPRINT" --json
```

工具更新仍要求先停止旧/新技能写入项目的 Agent，并显式传入 `--writers-stopped`。同时指定 `--update-tool` 和 `--upgrade-project` 时，结果仍按工具和项目分别报告；工具更新成功不代表项目升级也已完成。

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" plan --json
```

检查计划中的补缺、状态迁移、文档建议和冲突。确定执行范围后：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" apply-safe --json
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" status --json
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/check_workflow.py" "$PROJECT" --require-work-items --json
```

`apply-safe` 保留已有文档，并生成需要审阅的建议；它不会自动合并建议。处理后再次检查，只有 `up_to_date` 为真且相关检查通过，才能报告整个项目升级完成。结构版本变化或命令成功退出不代表文档已经处理完毕。

统一入口会在首次确认模板来源后保存文档基线。后续入口文档按三方内容判断，用户修改与新模板没有重叠时自动合并；存在重叠时保留冲突标记并等待审阅。没有可确认基线的旧文档不会被自动覆盖。

项目升级的写入范围会先记录为事务。若执行中断，可在确认没有其他写入者后运行：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/unified_upgrade.py" recover-project \
  --project "$PROJECT" --json
```

恢复完成后重新生成计划；如果项目在中断后被人工修改，恢复会停止并保留现场。

预览版转为同一目标的正式版，如果结构与规则不变，已有项目无需跟着改版本文字或重新初始化。需要迁移时按项目分别处理。

## 更新中断与回滚

保留候选包，使用其脚本恢复未完成的安装事务：

```bash
python3 -B "$PACKAGE/scripts/release_package.py" recover --skills-root "$SKILLS_ROOT" --writers-stopped
```

如需退回某次安装更新前的运行包，使用更新结果中的事务编号：

```bash
python3 -B "$PACKAGE/scripts/release_package.py" rollback-plan \
  --skills-root "$SKILLS_ROOT" --transaction "$TRANSACTION_ID"
python3 -B "$PACKAGE/scripts/release_package.py" rollback \
  --skills-root "$SKILLS_ROOT" --transaction "$TRANSACTION_ID" \
  --expected-current "$EXPECTED_CURRENT" --writers-stopped
```

回滚的 `EXPECTED_CURRENT` 必须来自本次 `rollback-plan`。事务与旧包保存在技能根目录的 `.agent-workflow-updates/`；后续人工修改会阻止自动覆盖。

运行包回滚不会回滚项目任务或关系库。恢复旧运行包后，需先确认它仍支持项目当前结构。项目文件的恢复另行处理，不能用旧运行包备份覆盖项目数据。
