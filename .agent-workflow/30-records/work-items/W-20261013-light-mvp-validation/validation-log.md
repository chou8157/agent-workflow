# 验证记录

## 2026-10-13 - 轻量 MVP 第一轮

- `python3 -m pytest experiments/frontier/test_mvp_light.py -q`：`2 passed`。
- `python3 -m pytest experiments/frontier/test_sqlite_store.py -q`：`13 passed`。
- `python3 -m pytest experiments/frontier/test_node_workflow.py -q -k 'three_real_work_items_have_fixed_identities_and_completion_semantics or evidence_links_hashes_lines_and_observation_time_match_original_documents or denied_leaf_is_gap_and_not_successful_empty'`：`9 passed, 131 deselected`。
- 独立临时网络实测：SQLite 注册 root/middle/leaf 三节点，完整聚合 `full`，覆盖 3/3，事实 3 条；拒绝 leaf 时返回 `partial` 和显式缺口；重复运行事实集合一致；源文件哈希不变。
- 示例报告已生成：`experiments/frontier/evidence/mvp-light-report-20261013.md`。
- 重要限制：middle/leaf 的 `completed_at` 为 `unknown`，因此当前资料不能可靠回答“本周发生了什么”；只能回答已登记工作项状态。未执行真实 Agent 表达层验证。

## 2026-10-13 - 日期语义第二轮

- `python3 -m pytest experiments/frontier/test_mvp_light.py -q`：`3 passed`。
- 从现有 `progress/validation-log` 显式日期格式提取 `9` 条记录；`2026-07-15` 至 `2026-07-21` 窗口命中 `4` 条；`2026-10-13` 至 `2026-10-19` 窗口命中 `0` 条。
- 日期窗口报告会区分“有记录但不在窗口”和“没有可识别日期”，不会把窗口内无记录写成“没有工作”。
- 结论：显式日期提取可行，但现有日期主要表示验证/记录事件，没有统一业务活动语义；`business_week_filter_ready=false`。真实 Agent 表达层仍未执行。

## 2026-10-13 - Agent 边界契约

- `python3 -m pytest experiments/frontier/test_mvp_light.py -q`：`4 passed`。
- 新增确定性草稿校验：Agent 必须为每个段落提供已核验 `fact_refs`，未知事实、重复引用和未说明的遗漏均被拒绝。
- 该测试只证明程序可以约束 Agent 输出边界，不代表真实模型已经通过；文本是否准确表达事实仍需真实 Agent 试用和人工盲审。

## 收口 2026-10-13T17:25:09+08:00
- 摘要：轻量 MVP 第一轮完成：SQLite 关系登记、确定性三节点聚合、来源与缺口验证通过；时间范围筛选尚不具备，真实 Agent 表达层未验证。
- 测试：test_mvp_light.py：2 passed; test_sqlite_store.py：13 passed; node_workflow 定向测试：9 passed，131 deselected
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, .agent-workflow/30-records/work-items/W-20261013-light-mvp-validation/, experiments/

## 2026-10-14 - 轻量 MVP 边界审计

- `python3 -m pytest experiments/frontier -q`：`411 passed, 38 skipped`。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：`ok: true`。
- `python3 -m py_compile experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py experiments/frontier/sqlite_store.py`：通过。
- 从 3 个固定节点提取 9 条显式日期记录；记录均来自 `validation-log.md`，未发现统一的业务活动日期标记，故 `business_week_filter_ready=false`。
- 构造状态为 `in_progress` 的合成事实，提交“已完成并已上线”的 Agent 草稿；当前 `fact_refs` 校验接受该文本，说明它只能校验引用范围，不能校验自然语言与事实状态一致。
- 证据：`experiments/frontier/evidence/mvp-light-boundary-audit-20261014.json`。
- 结论：确定性聚合基础通过；业务周筛选和真实 Agent 表达层未通过，工作项继续保持 `in_progress`，不进入正式开发。

## 2026-10-14 - 第一阶段只读报告入口

- 新增 `experiments/frontier/light_report.py`，支持从上级节点生成派生 Markdown 报告。
- 完整三节点运行返回码 `0`，报告包含 root/middle/leaf；拒绝 leaf 时返回码 `2`，仍生成报告并保留明确缺口。
- 尝试把报告写入授权来源目录时被拒绝；完整运行前后 40 个来源文件哈希一致。
- `python3 -m pytest experiments/frontier/test_light_report.py experiments/frontier/test_mvp_light.py -q`：`6 passed`。
- `python3 -m pytest experiments/frontier -q`：`413 passed, 38 skipped`。
- `python3 -m py_compile experiments/frontier/light_report.py experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py`：通过。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：`ok: true`。
- 证据：`experiments/frontier/evidence/mvp-light-report-cli-20261014.json`。
- 结论：第一阶段基础可用性达到；未改变节点自治和原始事实边界，下一阶段进入业务活动日期设计。

## 2026-10-14 - 第二阶段结构化业务活动日期

- 新增实验规范：`experiments/frontier/ACTIVITY_SCHEMA.md`。
- `.state.json` 可选 `activity_records` 要求唯一 `id`、合法 `date`、`summary` 和 `status`；普通日志日期不会进入时间窗口。
- 固定节点无结构化活动时，窗口不返回普通日志日期；加入 middle/leaf 结构化记录后准确返回 2 条活动，root 标记为日期未知。
- 非法日期使节点进入 `partial`，缺口保留具体 `activity_records` 错误。
- `python3 -m pytest experiments/frontier -q`：`415 passed, 38 skipped`。
- 证据：`experiments/frontier/evidence/mvp-light-activity-schema-20261014.json`。
- 结论：程序日期边界通过实验验证；真实项目尚未迁移，暂不宣称真实周报已可用。

## 2026-10-14 - 真实项目只读快照试用

- 只读复制 `agent-workflow`、`support-service`、`feedbackserver` 三个项目的工作项目录到临时目录，未修改原项目或安装版。
- 关系库登记 3 个节点，发现 25 条工作项事实；2 个节点完整读取，1 个节点因原始工作项文档缺失或损坏显式失败。
- 三个项目均没有 `activity_records`，结构化业务活动记录为 0；不能据此生成真实“本周工作”报告。
- 688 个临时快照来源文件聚合前后哈希一致。
- 证据：`experiments/frontier/evidence/mvp-light-real-snapshot-20261014.json`。
- 结论：读取和缺口处理在真实文档上具备可用性，但正式迁移前需要先做文档质量和活动字段 dry-run。

## 2026-10-14 - Agent 结构化声明契约

- 新增 `experiments/frontier/AGENT_CLAIM_CONTRACT.md`。
- Agent 段落必须提供 `fact_refs` 和 `claims`；程序逐项校验 `title`、`status`、`completed_at` 和 `completed_at_status`。
- 合法声明通过；将已完成事实声明为 `in_progress` 的合成草稿被拒绝。
- `python3 -m pytest experiments/frontier/test_mvp_light.py -q`：`7 passed`。
- 证据：`experiments/frontier/evidence/mvp-light-agent-claim-contract-20261014.json`。
- 边界：尚未调用真实 Agent，当前只证明程序可以拒绝不一致声明。

## 2026-10-14 - 第三阶段回归

- `python3 -m pytest experiments/frontier -q`：`416 passed, 38 skipped`。
- `python3 -m py_compile experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py experiments/frontier/light_report.py`：通过。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：`ok: true`。
- `git diff --check`：通过。
- 主分支保持干净；实验改动仍只存在于 `codex/exp-frontier-workflow-20261009` worktree，未提交、未推送、未同步安装版。

## 收口 2026-10-14T11:30:26+08:00
- 摘要：轻量 MVP 边界审计完成：确定性聚合基础通过，但业务活动日期语义和 Agent 自然语言一致性未通过，工作项保持进行中。
- 测试：python3 -m pytest experiments/frontier -q：411 passed，38 skipped; python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json：ok true; python3 -m py_compile experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py experiments/frontier/sqlite_store.py：通过
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, .agent-workflow/30-records/work-items/W-20261013-light-mvp-validation/, experiments/

## 收口 2026-10-14T18:16:52+08:00
- 摘要：第一阶段只读报告入口已实现并通过完整回归；完整聚合可用，部分结果明确降级，来源文件不变。日期语义和 Agent 表达层仍留待后续阶段。
- 测试：python3 -m pytest experiments/frontier -q：413 passed，38 skipped; python3 -m py_compile experiments/frontier/light_report.py experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py：通过; python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json：ok true
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, .agent-workflow/30-records/work-items/W-20261013-light-mvp-validation/, experiments/

## 收口 2026-10-14T18:47:30+08:00
- 摘要：第二阶段结构化业务活动日期已实现并通过实验回归；三个真实项目只读快照显示现有数据尚无 activity_records，且一个项目存在工作项文档缺失，尚未进入真实周报或 Agent 阶段。
- 测试：python3 -m pytest experiments/frontier -q：415 passed，38 skipped; python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json：ok true; python3 -m py_compile experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py experiments/frontier/light_report.py：通过
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, .agent-workflow/30-records/work-items/W-20261013-light-mvp-validation/, experiments/

## 收口 2026-10-14T18:59:29+08:00
- 摘要：第二阶段日期边界和第三阶段 Agent 结构化声明契约已实现并通过完整回归；真实项目只读快照仍显示需要活动字段迁移，真实 Agent 调用尚未开始。
- 测试：python3 -m pytest experiments/frontier -q：416 passed，38 skipped; python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json：ok true; python3 -m py_compile experiments/frontier/mvp_light.py experiments/frontier/node_workflow.py experiments/frontier/light_report.py：通过; git diff --check：通过
- 变更文件：.agent-workflow/30-records/work-items/W-20261009-frontier-workflow/, .agent-workflow/30-records/work-items/W-20261013-light-mvp-validation/, experiments/

## 2026-10-15 - 活动迁移 dry-run 与覆盖边界

- `python3 -m pytest experiments/frontier/test_activity_migration_dry_run.py -q`：`21 passed`。
- `python3 -m pytest experiments/frontier/test_mvp_light.py experiments/frontier/test_activity_migration_dry_run.py -q`：`29 passed`。
- `python3 -m pytest experiments/frontier -q`：`438 passed, 38 skipped`。
- `python3 -m pytest tests -q`：`29 passed`；稳定版测试未被本轮实验改动破坏。
- `python3 -m py_compile experiments/frontier/activity_migration_dry_run.py experiments/frontier/coordinator.py experiments/frontier/mvp_light.py`：通过。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：`ok: true`。
- 三个真实项目只读扫描：25 个工作项、0 条结构化活动记录、300 处候选日期位置；686 个来源文件扫描前后哈希一致；没有写入真实项目。
- `feedbackserver` 的两个工作项均标记为 `legacy_unmigrated_candidate`，不作为文档损坏处理；候选日期不会自动写入 `activity_records`。
- 证据：`experiments/frontier/evidence/mvp-light-migration-dry-run-20261015-v3.json`。
- 边界：扫描是有界近似盘点，不是原子快照；历史候选日期的业务语义、稳定版模板写入和真实 Agent 调用尚未验证。

## 2026-10-15 - 单节点收口与按需聚合

- `python3 -m pytest experiments/frontier/test_activity_closeout.py -q`：`7 passed`。
- `python3 -m pytest experiments/frontier -q`：`445 passed, 38 skipped`。
- `python3 -m pytest tests -q`：`29 passed`。
- `python3 -m py_compile experiments/frontier/activity_closeout.py experiments/frontier/node_workflow.py experiments/frontier/mvp_light.py`：通过。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：`ok: true`。
- 实验 fixture 验证：活动收口只写目标工作项 `.state.json`；相同活动重复提交返回 `unchanged`；删除节点身份后仍可本地收口。
- 三节点按需聚合验证：完整读取为 `full`；拒绝叶节点为 `partial` 并保留失败原因；`max_nodes=2` 明确跳过叶节点；证据文件哈希变化使对应活动进入缺口。
- 证据：`experiments/frontier/evidence/mvp-light-closeout-aggregate-20261015-v2.json`。
- 边界：当前写入器只验证单进程实验副本，未验证并发收口、进程中断恢复、稳定版 CLI、真实项目写入和真实 Agent。

## 2026-10-15 - 固定事实包 Agent 盲测

> 本节为早期调试记录。其 fact_package 是事后构造，不能证明实际输入字节。当前结论以末尾“原始证据纠错与最终回归”为准。

- `python3 -m pytest experiments/frontier/test_agent_blind_eval.py -q`：`7 passed`。
- 构造只暴露确定性字段的事实包，不提供原始文档、来源正文、路径或关系控制面；事实包 SHA-256 为 `609b35f8654890f50688f2239ebf59f26e54606179e1a06f179b4922eae8a8ac`。
- 两个独立 fresh Agent 均正确返回了段落级 `fact_refs` 和字段值，但每条 `claims` 均缺少必需的 `fact_ref`；程序按契约拒绝，结果为 `0/2` 通过。
- 未对缺失引用做自动推断或补齐，避免把事实与声明错误绑定；自然语言 `text` 仍标记为 `text_semantics_verified=false`。
- 证据：`experiments/frontier/evidence/mvp-light-agent-blind-20261015.json`。
- 结论：固定事实包和确定性拒绝边界有效，但当前 Agent 输出模板/提示不足以稳定满足声明契约；只能继续做实验分支提示优化，不能进入稳定版或真实项目迁移。

## 2026-10-15 - 提示模板与未知字段边界复测

> 本节原 1/2 结论已作废：v3 手工重建改写了原始输出；原始回放为 0/2。不同组提示不同，不能合并统计。

- 在实验事实包中加入逐条 `claims[].fact_ref` 示例模板后，两个新的独立 Agent 均通过结构化契约，证据为 `evidence/mvp-light-agent-blind-20261015-v2.json`。
- 追加盲测发现一个 Agent 在每个段落中额外输出未定义的 `omitted` 字段；初始校验器会忽略该字段，暴露了严格 schema 缺口。
- 收紧根对象、段落和声明的字段集合，并新增未知字段测试；复测结果为 `1/2`，额外字段被明确拒绝，证据为 `evidence/mvp-light-agent-blind-20261015-v3.json`。
- 结论：提示模板能改善声明格式，但 Agent 仍可能输出未定义字段；严格拒绝边界已补齐，仍需更多重复样本和自由文本矛盾测试，不能宣称表达层稳定。

## 2026-10-15 - 自由文本权威边界

- 新增 `render_verified()`，先通过结构化契约，再只依据事实包中的已核验字段生成展示文本。
- 构造 `status=in_progress` 事实但让 Agent 自由文本写成“已完成并上线”；结构化声明仍可通过，但程序重渲染结果保持 `in_progress` 和“未记录”，不采信矛盾自由文本。
- `python3 -m pytest experiments/frontier/test_agent_blind_eval.py -q`：`8 passed`。
- 结论：Agent `text` 只能作为待审表达，最终汇报必须由程序根据核验字段重渲染；自然语言语义自动验收仍未解决。
- 证据：`experiments/frontier/evidence/mvp-light-agent-render-boundary-20261015.json`。

## 2026-10-15 - 原始证据纠错与最终回归

- 从原生会话提取六份 final_answer，逐字核对 task_complete，保存原始文本和 SHA-256。a/b、c/d、e/f 当前契约回放分别为 0/2、2/2、0/2；旧 v3 重建的 e/f 文本与 f 字段不符合原始输出，1/2 已作废。旧文件保留并标记 superseded_by_raw_audit。
- 原生日志中的旧任务提示已加密，旧事后构造 fact_package 哈希不作为输入证据；不把不同提示三组结果合并为模型可靠率。
- 新一轮调用前冻结输入、summary 和代码哈希；两个 fresh Agent 的实际文件读取内容均与冻结字节相同，原始 final 均通过，结果 2/2。报告保留进行中状态、未知日期和拒绝节点；text_semantics_verified=false。
- 新一轮证据：experiments/frontier/evidence/mvp-light-agent-frozen-20261015/results.json；旧输出复核：experiments/frontier/evidence/mvp-light-agent-blind-20261015-audited.json。
- 独立只读审查发现并修复未知 omitted 注入和空 partial 结果丢失缺口；复查通过。
- 端到端定向测试：单节点活动 created/unchanged、父节点不自动同步、拒绝 leaf 的按需聚合、日期窗口及非法 JSON 的固定格式降级均通过，来源哈希不变。
- python3 -m pytest experiments/frontier/test_agent_blind_eval.py experiments/frontier/test_mvp_light.py -q：33 passed。
- python3 -m pytest experiments/frontier -q：470 passed, 38 skipped。
- python3 -m pytest tests -q：29 passed。
- 阶段结论：可推进有确定性降级的实验版最小集成；不是稳定版交付、真实项目迁移或自然语言语义自动验收。
- 最终静态检查：修改模块及稳定版核心脚本 py_compile 通过；check_workflow.py 返回 ok: true；冻结输入/代码/原始 final 哈希一致。实验文件尚未跟踪，另直接检查本轮 11 个源码与记录文件，无行尾空白。

## 2026-10-15 - 最小入口与本地写入加固

- `python3 -m pytest experiments/frontier/test_activity_closeout.py experiments/frontier/test_write_reliability.py -q`：26 passed。
- 子 Agent 执行入口定向 `python3 -m pytest experiments/frontier/test_light_cli.py experiments/frontier/test_light_report.py experiments/frontier/test_mvp_light.py -q`：21 passed。
- `python3 -m pytest experiments/frontier -q`：499 passed, 38 skipped，97.82 秒。跳过项不算通过。
- `python3 -m pytest tests -q`：29 passed，0.56 秒。
- `python3 -m py_compile` 检查 task_context/check_workflow/scaffold_workflow 及 activity_closeout/node_workflow/light_cli/light_report/mvp_light：通过。
- `python3 agent-workflow/scripts/check_workflow.py . --require-work-items --json`：ok: true，issues 为空。
- 原始命令、退出码、输出和代码哈希由验证脚本自动写入 `experiments/frontier/evidence/mvp-light-entry-validation-20261015.json`；source_unchanged_during_checks 为 true。
- 多进程验证覆盖不同活动并发、同 ID 竞争、状态/活动两种先后、锁超时、持锁/替换前 SIGKILL、刷盘及替换故障、结果待确认后的重复确认。当前作用域仅本机临时项目，未模拟真实断电。
- CLI 临时副本验证覆盖父子孙接入与重试、关系库保护、跨周端点、日志追加后重试、引用行变更冲突、失败/跳过/未知日期缺口、报告不写来源及退出后独立记录。
- 独立审查发现直接 API 自引 `.state.json` 会“创建即失效”，已下沉拒绝并新增回归；复验状态字节不变。
- `git diff --check` 通过；另外直接检查 13 个源码、测试和说明文件，无行尾空白。main 状态未变，未同步安装版或写真实项目。

## 2026-10-15 - 独立可用版交付与安装验收

- 最终实验回归 528 passed, 38 skipped；原有功能回归 29 passed，修改脚本编译及工作流检查通过。首次全量 3 failed, 522 passed, 38 skipped，原因为旧 mock 签名与新增参数不匹配；修复后完整重跑通过。失败历史保留在 frontier-release-validation-20261015.json。
- 真实项目隔离副本回放：21 次 CLI、11 项检查，父子孙活动数 3/2/1；来源 792 个文件哈希未变。历史 25 个工作项的 0 条活动及缺状态文件事实均保留，无历史自动迁移。
- 独立 Agent 实际使用含一次工具停滞后的恢复；最终初始化、接入、执行检查、记录和周汇总完成。主 Agent 读回并实跑重复记录，确认只有一条活动、任务仍在进行、报告保留缺口、源文件不变。
- 发布包 79 个文件，quick_validate 和 release_package verify 通过。验收包与交付包运行代码相同，只有说明及对应清单不同。
- 已获工作区外写入权限并新增安装 /Users/yizhoucp/.codex/skills/agent-workflow-frontier，install 返回 created。安装路径下 record 重试返回 unchanged、report 正常生成、使用后 verify 与 skill 校验通过。
- 原安装版全部 68 个文件（含既有缓存）集合和 SHA-256 不变；main 保持干净；最终源码哈希仍与完整回归一致。
- 压缩包 SHA-256：427a18566c9b71c7ade876b686a4e55ba037765355735469126381ea04b739fa；安装 manifest SHA-256：4440dc1951300aff42e8a31eec618e2c5a14fce65de07cd47168b64d6cac5e5b。
- 证据：experiments/frontier/evidence/frontier-release-validation-20261015.json、frontier-user-acceptance-20261015.json、frontier-installation-20261015.json。
- 未验收：长期真实项目持续使用、真实断电、跨机器、完整分层 Agent 调度和大网络严格资源上限。跳过项和独立单样本均不折算为可靠率。

## 2026-10-16 - 已有项目兼容性与升级专项分析

- 当前已安装原版生成 v5 临时项目，加入自定义文档后，新安装版直接 show/check/record/report 成功；没有重复初始化，原状态字段和自定义入口保留；重复活动 unchanged。
- 原版顺序 set-status 保留新增活动，但不遵守新写入锁。受控交错“旧读取 -> 新追加 -> 旧写回”实际复现活动数 1 -> 2 -> 1；仅临时副本受影响。
- v2 旧格式项目的 plan 只读；apply-safe 将迁移提示句子误作当前目录文件名，升级标记到 5 后返回 up_to_date=true，工作项状态仍缺失。独立 Agent 分别复现相同缺陷。单独 migration-check/apply 可保留正文并将未知日期明确保留。
- 独立安装器审查：首次安装成功；已存在不同合法内容拒绝覆盖；下一版本清单被当前验包器拒绝。未实现更新/回滚，不能把拒绝覆盖当升级完成。
- 两版实际安装目录均未改动；原版 68 个文件与前次基线一致，新版 verify 通过。main 保持干净。未修改运行源码，未重跑全量测试，发现尚未修复。
- 可复核证据：experiments/frontier/evidence/frontier-upgrade-audit-20261016.json；分析与整改边界：experiments/frontier/UPGRADE_REVIEW_20261016.md。
