# agent-workflow-frontier 0.1.0

这是可独立使用的轻量首版：各项目保留自己的工作流和活动记录，按需汇总当前项目或多层子项目。它与原有 `agent-workflow` 并存，使用 Python 标准库和本地 SQLite，不需要启动服务。

2026-10-15 已完成本机安装和安装后验证，可以开始使用。原有 `agent-workflow` 的 68 个文件逐项核对未变。

## 日常怎么用

新开会话，选择需要操作的项目，调用 `$agent-workflow-frontier`。可以直接说：

> 使用 $agent-workflow-frontier 继续当前项目，结束时记录这次实际工作。

> 使用 $agent-workflow-frontier，只汇总当前项目本周的工作。

首次需要多项目汇总时，说明一次具体关系，例如：

> 使用 $agent-workflow-frontier，把 /path/project-b 接到 /path/project-a 下面。

以后在上级项目中说：

> 使用 $agent-workflow-frontier，汇总当前项目和所有下级项目本周的工作。

Agent 会处理关系登记、证据行号、日期参数和报告保存。你不需要手写 JSON/YAML。节点可以继续包含下级节点；不接入关联也可独立记录和汇总。

## 会得到什么

- 每次实际开发或验证收口后，活动只记录在本项目，不自动同步父级。
- 汇总报告包含日期、成果、活动状态、来源与证据，以及读取失败、超出预算和历史日期未知等缺口。
- 相同记录重试不重复；记录与任务状态同时更新有协作锁；日志正常追加不使旧证据失效。
- 报告可直接打开，默认放在独立临时目录。需要长期保存时，告诉 Agent 保存到来源目录之外的指定位置。
- 退出关联后，本地任务与活动记录仍保留。

## 使用时需要知道

- 历史工作项没有结构化活动日期时，会显示未知；首版不会自动猜测或批量补造过去的周报。从现在开始记录的工作可以持续汇总。
- “本周/上周”按本机日期、周一至周日计算，也支持指定日期。
- 当前覆盖本机 macOS/Linux、Python 3.8+。默认上限为 100 个节点、10 层，超出部分明确列出；尚未交付跨机器、多用户和完整子 Agent 任务分发。
- 同一工作项的并发会话使用本版脚本，避免同时用旧安装版或手工覆盖状态。其他项目仍可照常使用原有版本。
- 汇总不会改写工作项与证据；SQLite 可能生成自己的 `-wal/-shm` 控制文件。若来源目录要求文件集合完全不变，把关系库放在来源之外。

## 交付与完整性

- 独立安装目录：`/Users/yizhoucp/.codex/skills/agent-workflow-frontier`。
- 可重新解压安装的交付包：同目录的 `agent-workflow-frontier-0.1.0.tar.gz`，约 85 KiB。
- 压缩包 SHA-256：`427a18566c9b71c7ade876b686a4e55ba037765355735469126381ea04b739fa`。
- 本次包 manifest SHA-256：`4440dc1951300aff42e8a31eec618e2c5a14fce65de07cd47168b64d6cac5e5b`。

校验安装内容：

```bash
python3 -B /Users/yizhoucp/.codex/skills/agent-workflow-frontier/scripts/release_package.py verify /Users/yizhoucp/.codex/skills/agent-workflow-frontier
```

需要停止使用时，切回原 skill 即可；需要解除项目关联时明确要求退出。移除实验 skill 目录不会代替关系清理，也不应删除任何项目数据。

本次最终实验回归 528 项通过、38 项跳过，原有功能 29 项通过；真实项目隔离副本和独立 Agent 使用验收均已完成。独立 Agent 验收包含一次工具停滞后的恢复，未据此计算模型可靠率。安装后的记录、汇总、文件完整性和 skill 校验均通过。长期业务使用仍需要在后续使用中观察。
