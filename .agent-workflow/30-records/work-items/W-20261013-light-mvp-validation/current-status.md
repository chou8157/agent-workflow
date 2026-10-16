# 当前状态

## 恢复摘要

- 最近更新：2026-10-16；生命周期以 .state.json 为准。
- 后续迭代：W-20261016-versioned-upgrade 已补齐连续升级并将原安装更新为同名 agent-workflow 1.1.0-beta.1；本页 0.1.0 安装和“原版未变”描述属于该阶段历史结果，日常入口以后续工作项为准。
- 当前结论：已交付并安装独立轻量首版 agent-workflow-frontier 0.1.0；本工作项验收范围完成，完整稳定正式版目标仍属于后续工作。
- 使用入口：新会话调用 $agent-workflow-frontier；独立目录为 /Users/yizhoucp/.codex/skills/agent-workflow-frontier。
- 已完成：SQLite 关系登记、父子孙聚合、本地活动幂等追加、协作写入锁、证据行哈希、显式缺口、日期窗口、固定报告、自然语言 skill 路由及独立安装包。
- 本轮补齐：单节点不依赖关系库的 self 汇总、本周/上周快捷日期、报告落盘、真实项目隔离副本回放和独立 Agent 实际使用验收。
- 实验仍在 codex/exp-frontier-workflow-20261009；main 干净，原安装版 68 个文件未变，真实项目未写入，未提交、推送或合并。

## 已确认的边界

- Agent 的自由文本不直接成为报告正文；程序从原事实重渲染。text_semantics_verified 仍为 false。
- 当前活动报告为确定性输出；Agent 适配层仍只展示工作项状态，尚未接入完整分层子 Agent 调度。
- 三个真实项目此前只读盘点为 25 个工作项、0 条 activity_records；feedbackserver 的 2 个工作项是旧格式待迁移，不能直接生成可靠历史周报。
- 并发与中断恢复已在本机临时副本验证；只覆盖 macOS/Linux 本地文件系统及本实验写入器，不能与旧安装版或手工覆盖同时写同一状态文件。不宣称跨机器、共享文件系统或真实断电保障。
- 新入口的行范围哈希允许日志末尾追加；引用行被改动或移位仍进入缺口。历史整文件哈希保持原行为；不自动迁移历史。
- 独立首版已安装，但原稳定版未集成；真实项目长期持续使用、大网络严格总耗时和内存上限尚未验收。默认 100 个节点、10 层，超出部分列为 skipped。
- 独立使用验收共一个样本，包含一次工具停滞后的受控恢复；不作为模型可靠率或无中断连续通过证明。运行代码与最终安装包一致。
- 汇总不改工作项和证据；SQLite 可能创建自己的 WAL/SHM 控制副文件。要求来源文件集合完全不变时，把关系库放在来源目录之外。
- 原始事实的语义准确性仍依赖本地收口和证据；哈希只能证明来源版本。
- 2026-10-16 升级专项核查：v5 项目可直接复用；独立安装器未实现原位更新/回滚。旧结构 apply-safe 存在迁移提示写成文件、缺状态却显示结构最新的缺陷；新旧写入器交错丢活动已在临时副本复现。尚未修复，详见 progress/018-命名与旧项目升级核查.md。

## 最新验证

- 最终实验回归：528 passed, 38 skipped；原有功能回归：29 passed。首次回归的 3 个旧 mock 签名失败已修复并保留原始输出；跳过项未当作通过。
- 真实项目隔离副本：3 个来源项目、25 个历史工作项，21 次 CLI 和 11 项检查通过；792 个原工作流文件前后哈希一致。
- 独立 Agent 完成初始化、接入、实际检查、记录和周汇总；主 Agent 读回确认任务仍在进行、仅一条活动、重复不新增、2 节点汇总及未知日期缺口保留。
- 安装后从独立目录运行记录和汇总成功；79 个交付文件完整性检查、skill 校验通过；原安装版全部 68 个文件未变。
- 既有多进程竞争、锁超时、SIGKILL、替换故障及幂等重试验证维持；不宣称真实断电或跨机器保障。

## 后续边界

1. 首版已可直接使用；首次在真实项目接入时，由用户明确项目路径和上下级，之后按需汇总。
2. 从现在开始记录实际活动；旧历史日期不足继续标未知，不自动补造或批量迁移。
3. 用户已明确本能力属于原产品迭代。后续优先统一 agent-workflow 入口、补安装更新/回滚与已有项目预检，修复升级专项发现；长期试用和完整分层调度另行推进。

## 证据入口

- 冻结输入与原始输出：../../../../experiments/frontier/evidence/mvp-light-agent-frozen-20261015/results.json
- 历史输出纠错：../../../../experiments/frontier/evidence/mvp-light-agent-blind-20261015-audited.json
- 本轮自动验证原始输出与代码哈希：../../../../experiments/frontier/evidence/mvp-light-entry-validation-20261015.json
- 最终回归：../../../../experiments/frontier/evidence/frontier-release-validation-20261015.json
- 独立使用：../../../../experiments/frontier/evidence/frontier-user-acceptance-20261015.json
- 安装验收：../../../../experiments/frontier/evidence/frontier-installation-20261015.json
- 用户使用说明：../../../../experiments/frontier/releases/agent-workflow-frontier-0.1.0.md
- 本轮收口：progress/017-独立可用版交付.md
- 升级专项核查：progress/018-命名与旧项目升级核查.md；../../../../experiments/frontier/UPGRADE_REVIEW_20261016.md
- 其他阶段历史：validation-log.md 和 progress/
