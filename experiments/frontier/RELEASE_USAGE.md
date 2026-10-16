# agent-workflow 1.1.0-beta.1 连续更新预览包

本包沿用 `agent-workflow` 名称、调用入口及项目 `.agent-workflow/` 数据。包含原单项目能力、轻量按需聚合，以及技能程序更新和项目结构升级。旧试验包 0.1.0 的已交付文件保留在 `releases/`，不原地修改。

## 构建与校验

```bash
python3 -B experiments/frontier/build_release.py build \
  --output /private/tmp/agent-workflow-1.1.0-beta.1 \
  --archive /private/tmp/agent-workflow-1.1.0-beta.1.tar.gz
python3 -B experiments/frontier/build_release.py verify /private/tmp/agent-workflow-1.1.0-beta.1
```

构建目录必须在开发仓库之外。输出已有不同内容时拒绝覆盖；开发中每次重建使用新的候选目录。包内附运行脚本、模板、说明、文件哈希清单，不包含测试、研究资料或真实项目数据。使用 Python 标准库，无额外服务，支持本机 macOS/Linux、Python 3.8+。

## 首次安装与连续更新

没有旧安装时执行 `install`。已有同名安装时使用 `update-plan` 和 `update`，不能用复制覆盖或重跑初始化替代升级。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" install "$PACKAGE" --skills-root "$SKILLS_ROOT"
python3 -B "$PACKAGE/scripts/release_package.py" update-plan "$PACKAGE" --skills-root "$SKILLS_ROOT"
```

计划会给出当前安装和候选包指纹；检查后，将返回值原样用于更新。`--writers-stopped` 只能在结束旧写入后使用，不代表程序能够探测所有运行中的 Agent。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" update "$PACKAGE" \
  --skills-root "$SKILLS_ROOT" --expected-current "$EXPECTED_CURRENT" \
  --expected-source "$EXPECTED_SOURCE" --writers-stopped
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/release_package.py" verify "$SKILLS_ROOT/agent-workflow"
```

路径应为真实绝对路径，拒绝经过符号链接；示例使用 macOS 的 /private/tmp，Linux 可使用真实 /tmp。安装根由调用方显式指定，无隐含个人路径。更新实际 Codex skills 目录属于工作区外写入，按会话授权与工具权限执行。旧版没有更新命令也可由候选新包执行更新；无 manifest 旧安装完整保留备份，不能假定它的准确产品版本。

## 中断恢复与回滚

事务和备份保存在 `<skills-root>/.agent-workflow-updates/`，保留候选包绝对路径以便调用恢复。运行包与项目数据分开；回滚不会删除或还原项目任务、活动和关系库。

```bash
python3 -B "$PACKAGE/scripts/release_package.py" recover --skills-root "$SKILLS_ROOT" --writers-stopped
python3 -B "$PACKAGE/scripts/release_package.py" rollback-plan --skills-root "$SKILLS_ROOT" --transaction "$TRANSACTION_ID"
python3 -B "$PACKAGE/scripts/release_package.py" rollback --skills-root "$SKILLS_ROOT" \
  --transaction "$TRANSACTION_ID" --expected-current "$EXPECTED_CURRENT" --writers-stopped
```

目标内容在更新后发生变化时，不覆盖用户修改；先核对冲突。回退旧运行包后，也应检查当前项目结构是否仍受旧版本支持，不得让旧写入器与新写入器并发操作同一工作项。

## 已有项目升级

更新技能只涉及一份运行包，业务项目不需要重新初始化。选择目标项目后：

```bash
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" plan --json
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" apply-safe --json
python3 -B "$SKILLS_ROOT/agent-workflow/scripts/upgrade_workflow.py" "$PROJECT" status --json
```

根据计划授权执行，仅补齐缺失结构、迁移合法状态并生成文档建议。保留原入口和历史，自定义内容不覆盖，日期未知不猜测。结构、状态迁移、冲突和待审建议分开汇报。已知历史结构 1 至 5 可升到 6，6 可重复检查与修复；未来或非法结构明确拒绝。

多项目关联保持可选。既有 `.frontier-node.json` 和数据库继续复用，不因产品名称统一而重建网络。日常使用新会话中的 `$agent-workflow`，无需用户手写 JSON/YAML 或命令参数。

## 验证边界

`test_release_package.py` 覆盖独立构建和使用；`test_release_update.py` 覆盖安装更新与恢复；`tests/test_versioned_upgrade.py` 覆盖项目历史版本和增量迁移。当前测试结果以本次工作项验证日志为准，不沿用旧交付测试计数。

完整性清单是哈希校验而非发布者签名；离线包来源由用户和交付渠道确认。不宣称远程自动分发、跨机器并发或真实断电已验收。
