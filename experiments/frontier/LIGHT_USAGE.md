# 轻量多项目实验入口

当前目标是：各项目照常本地工作，显式记录活动，上级按需汇总指定日期内的记录。入口只有 `connect`、`record`、`report`、`leave`，不需要手写 JSON/YAML，不启动服务。

这是隔离 worktree 的实验入口，尚未安装到日常 skill，也未开放真实项目自动写入。以下命令应先用于测试副本。由 Agent 执行时，用户可以直接说“接入这个项目”“记录这次工作”“汇总本周”，Agent 根据事实填写参数，不能替用户猜日期或结果。

以下示例从实验 worktree 根目录运行；替换示例路径与已有工作项 ID。

## 1. 接入项目

先接入上级，再接入下级。根节点显式选择 SQLite 文件，子节点自动沿用上级的关系库。每个目录需已经具有原有 `.agent-workflow` 工作流。

```bash
python3 experiments/frontier/light_cli.py connect --project /tmp/demo/projects/root --registry /tmp/demo/control/registry.sqlite
python3 experiments/frontier/light_cli.py connect --project /tmp/demo/projects/middle --parent /tmp/demo/projects/root
python3 experiments/frontier/light_cli.py connect --project /tmp/demo/projects/leaf --parent /tmp/demo/projects/middle
```

节点身份默认沿用已存在身份；首次接入默认使用目录名。同名目录可在首次接入时指定 `--node-id`。相同命令可重试，已存在的关系不会重复登记，也不会清空关系库。接入中断可重试同一命令；已配置的库丢失、损坏、不同库或非 SQLite 配置会明确拒绝，不自动创建替代权威。

接入只建立关联，不复制下级工作记录。第一版面向同一台机器；它不是跨机器权限或多用户系统。

## 2. 记录当前项目的一次工作

先按原有工作流记录实际验证证据，再引用其中明确的行号范围。无需加入网络，也不要求关系库可用。

```bash
python3 experiments/frontier/light_cli.py record \
  --project /tmp/demo/projects/leaf \
  --item W-example \
  --date 2026-10-15 \
  --summary "完成查询接口验证" \
  --status completed \
  --evidence .agent-workflow/30-records/work-items/W-example/validation-log.md \
  --line-start 8 --line-end 12
```

- 仅向该工作项 `.state.json` 追加一条 `activity_records`；不更新父节点、关系库或其他项目。
- 活动的 `--status` 只描述这次活动，不代替工作项生命周期。已有任务的开始、完成等操作仍走实验版原有 `task_context.py`。
- `--id` 可省略，程序使用日期、摘要、状态、证据路径和固定范围生成稳定 ID。重复相同内容返回 `unchanged`；同 ID 内容变化会拒绝覆盖。需要稳定业务身份时可显式给出 `--id`。
- 证据必须是项目 `.agent-workflow` 内的 `.md` 或 `.json`，不能引用 `.state.json` 自身。必须提供起止行；仅被引用行参与证据哈希。日志末尾追加不影响旧活动；改写或移动被引用行会产生缺口，不能伪装为有效证据。
- 活动摘要以本地记录为权威；报告是派生结果。程序验证来源一致性，不能证明自然语言摘要与真实业务完全相符。

本地并发保护适用于本机 macOS/Linux，以及本实验版的 `task_context.py` 和活动写入器。旧安装版写入器或手工覆盖不参与相同文件锁，不能同时写同一工作项。写入中断后可用原命令重试；成功前后的状态应以读回结果为准。

## 3. 按日期汇总当前节点和下级

```bash
python3 experiments/frontier/light_cli.py report \
  --project /tmp/demo/projects/root \
  --source-root /tmp/demo/projects \
  --start 2026-10-13 --end 2026-10-19 \
  --output /tmp/demo/reports/weekly.md
```

日期包含起止日。`--source-root` 是本次允许读取的目录边界；节点位于边界外会显示缺口。省略 `--output` 时输出到终端；报告文件必须在来源根目录之外，且不能覆盖关系数据库及其辅助文件。

报告包含活动摘要、状态、原工作项路径及哈希、证据路径及引用范围，并显示三类不足：

- 读取失败（failed）：节点拒绝访问、来源损坏或证据变化等。
- 被跳过（skipped）：超过 `--max-nodes` 或 `--max-depth` 预算；不会装作已读取。
- 缺少日期记录（unknown_date）：没有显式活动记录的工作项，不等于该项目没有工作。

`--deny leaf` 可在本次请求排除指定节点；`--max-depth 1` 只读取当前节点和直接子节点，但仍列出被跳过的后代。预算作用于节点读取，第一版尚未提供大型网络的严格总内存/总耗时上限。

退出码 `0` 表示计划范围内节点均已读取，`2` 表示操作失败或节点覆盖不完整。即使退出码为 `0`，仍需阅读 `unknown_date` 和事实口径；有记录不代表历史完整。程序不从 Markdown 日期、文件修改时间推断未记录活动，不会自动回填历史周报。

原 `light_report.py` 仍可使用：没有日期时保持原工作项状态摘要；同时提供 `--start`、`--end` 时生成活动摘要。默认均为确定性报告，不依赖 Agent 文本生成。

## 4. 退出关联，继续单独工作

```bash
python3 experiments/frontier/light_cli.py leave --project /tmp/demo/projects/leaf
```

退出保留项目工作流和所有本地活动，随后仍能使用 `record` 和原本的任务管理能力。关系库不可用时，本地禁用仍会执行，但提示关系清理未完成；这类状态需核查关系库和退出备份，不能当作完整清理成功。

## 验证范围

自动化验收使用临时副本覆盖：父子孙接入和重复接入、不同库保护、关系成环拒绝、跨周和起止日、重复收口与日志追加、证据改写冲突、失败/跳过/未知日期缺口、报告不写来源、退出后独立收口。

这些是本地实验验证，不等于真实项目长期试用、安装版升级、跨机器使用或完整子 Agent 分发已完成。
