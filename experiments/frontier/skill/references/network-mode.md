# 活动记录和按需汇总

本文件中的 `SKILL_ROOT` 是当前 skill 根目录，`PROJECT` 是用户选择的项目根目录；命令参数由 Agent 根据当前任务填写，用户不需要编辑 JSON/YAML。只读查询不需要新建活动，写操作须属于用户当前授权。

## 接入与退出

先检查项目的 `AGENTS.md`、`.agent-workflow/README.md` 和当前状态。没有工作流时走本包原有初始化流程；不要覆盖入口。初次接入需要确定项目路径和上级；若用户尚未表达关系，先问这个关键问题。不是每个磁盘目录都必须成为节点。

根项目首次接入时，可把本地关系文件放在该项目的 `.agent-workflow/frontier/registry.sqlite`；已有 `.frontier-node.json` 则沿用配置，不重新建库。关系库不保存工作项正文，不需要加入 Git。子项目使用上级路径即可继承同一库。

只读汇总不会改写工作项和证据。SQLite 读取可能创建 `-wal`/`-shm` 控制副文件；若来源目录要求文件集合也完全不变，应将关系库放在来源目录之外的获准控制目录。

```bash
python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" connect --project "$PROJECT" --registry "$PROJECT/.agent-workflow/frontier/registry.sqlite"
python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" connect --project "$CHILD_PROJECT" --parent "$PROJECT"
```

接入支持父子孙；每个节点仍可有自己的工作项。同名目录可在首次接入时给出有意义的 `--node-id`。已有身份、不同库、成环或损坏配置会明确拒绝，不自动重置、迁移或覆盖。中断后可重试同一命令。

```bash
python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" leave --project "$PROJECT"
```

退出只解除关联并保留本地事实。若结果为 `partial`，说明本地已禁用但关系清理未完成，要如实说明；不要宣称完整退出。父节点退出会断开其关联边，原子节点仍可独立工作；不删除任何子项目。

## 记录一次实际工作

先按 `references/finalize-mode.md` 在选定工作项正常收口，保留本次实际验证的证据。然后追加一条代表本次收口的活动：

1. 确认工作项、业务日期、简短事实摘要和活动状态。当前发生的操作可使用当前本地日期；补记旧活动必须有用户或原始业务日期依据。多个工作项无法确定时先澄清。
2. 从本次收口文件中选择准确证据行，引用项目内 `.agent-workflow/` 下的 Markdown/JSON；禁止引用 `.state.json`。用行号工具检查被引内容，不凭记忆填写。
3. 执行记录命令，保留返回的活动 ID；同一操作失败后使用原参数重试，不另造 ID。摘要只描述证据支持的成果。

```bash
python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" record \
  --project "$PROJECT" --item W-example --date 2026-10-15 \
  --summary "完成本地接口验证" --status completed \
  --evidence .agent-workflow/30-records/work-items/W-example/progress/check.md \
  --line-start 4 --line-end 7
```

默认活动 ID 按规范化内容生成，原命令重试不重复；需要稳定业务标识可传 `--id`。`completed` 仅表示这次活动完成；如果整个任务仍在进行，保持任务 `in_progress`，通过本包 `task_context.py` 管理生命周期。

证据范围外追加日志不会使旧活动失效；引用行改写或移位会被报告为缺口。旧整文件哈希引用不自动转换。每次收口优先新增独立证据文件，不把原日志全部复制成第二套活动事实。

旧工作项缺少 `.state.json` 时，保留原有收口，不强行补造日期；按 `upgrade-mode.md` 先做只读项目升级计划，只有已授权升级时才执行迁移，不因一次汇总自动迁移。结构化记录失败时明确告知“本地工作已完成，活动记录待补”，不得把失败说成成功。

## 按需汇总

只查询当前项目时，使用 `--scope self`，不要求接入网络。多项目查询使用 `--scope subtree`，只遍历 `contains` 关系；不会把同一关系库中的无关根节点一并纳入。

`--source-root` 是用户项目所在的获准共同目录。优先采用用户给定或当前会话已确认的根路径；已明确登记的项目路径可以据此计算共同目录，不遍历其他未登记目录。不确定读取范围时澄清，不用 `/` 扩大范围。

```bash
python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" report \
  --project "$PROJECT" --source-root "$PROJECT" --scope self --week this --save

python3 -B "$SKILL_ROOT/scripts/frontier/light_cli.py" report \
  --project "$PROJECT" --source-root "$SOURCE_ROOT" --scope subtree --week this --save
```

- “本周”用 `--week this`，“上周”用 `--week last`，按本机日期计算周一至周日；输出会标明实际日期。用户指定日期时使用 `--start YYYY-MM-DD --end YYYY-MM-DD`，包含起止日，不能与 `--week` 混用。时区或周定义与本机不同则先按用户口径确定显式日期。
- `--save` 自动写入独立临时报告目录，终端只输出文件路径和覆盖统计。优先直接给用户可打开的报告链接；需要概述时按需读取报告，避免一次加载所有源文档。用户需要长期保留时用 `--output` 写到来源根之外的明确位置。
- 默认读取上限为 100 节点、10 层，超出会列为 skipped；可在用户需要时调整 `--max-nodes`/`--max-depth`。这是小规模本机版本，不宣称大型网络严格内存或耗时上限。
- `--deny NODE_ID` 可拒绝本次读取某个节点。目录不可读、证据变化、未知日期、被预算跳过都必须展示；报告没有活动不能推断用户没有工作。
- 返回码 `0` 仅表示节点读取完整，不代表历史活动完整。返回码 `2` 可能是已生成 partial 报告；先看 stdout 的报告路径和缺口，不要直接当作“没有结果”。没有报告路径且命令报错时才说明本次未生成。

汇总阶段不更新本地活动，不给父级维护第二套状态。可把报告作为派生材料，但它不是活动事实源，下一次汇总仍读取各节点原始记录。

## 使用边界

文件锁只覆盖参与同一锁协议的写入器。同一工作项的并发会话要使用当前统一版本，不能同时由旧脚本、试验别名或手工覆盖状态文件。升级前结束旧写入；关闭关联即可停止网络能力，不需要清空活动记录。既有 `.frontier-node.json` 与数据库路径保留，不因产品名称统一而重建关联。

本版不运行常驻服务，不自动分发工作给子 Agent，不远程读取其他机器。以上后续能力不影响第一版的本地记录与按需聚合。
