# agent-workflow

让智能体在接手、开发和交接项目时，有清晰的规则、任务上下文和可追溯记录。

这是一个 Codex Skill，以项目根目录的 `AGENTS.md` 为入口，将项目规则和工作记录保存在 `.agent-workflow/`，帮助不同会话继续同一项工作。

## 能力

- 初始化项目工作流，按需读取项目资料和任务上下文。
- 管理多个独立工作项，记录进展、验证、风险与交付。
- 检查工作流，补齐缺失项，并增量升级已有项目。
- 记录本地活动，按需汇总已关联的多个项目。
- 按项目需要启用知识、证据、文档交付等可选能力。
- 更新、恢复和回滚技能程序，同时保留项目资料。

默认从单项目和最小能力开始，无需数据库服务或额外 Python 运行依赖。支持 macOS/Linux、Python 3.8 及以上版本。

## 开始使用

安装完整发行包后，在新会话中使用：

```text
$agent-workflow 初始化当前项目
$agent-workflow 加载当前项目，继续指定的工作项
$agent-workflow 检查当前项目工作流
$agent-workflow 汇总当前项目本周的工作
```

已有 `.agent-workflow/` 的项目可以直接加载；需要升级时先检查升级计划。安装、更新与恢复步骤见 [使用与升级指南](docs/usage.md)。

## 版本与更新

当前版本见 [VERSION](VERSION)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。源码主线与已发布版本分别管理；使用正式版本时选择对应标签的完整发行包。

产品版本用于标识安装的技能程序，工作流结构版本用于判断项目是否需要迁移。更新技能不会自动升级全部项目，也不需要每次都重建工作流。

## 开发与验证

完整发行包由基础工作流和多项目模块组合构建，不能单独复制 `agent-workflow/` 目录作为完整安装。构建入口和版本规则见 [维护者发布指南](docs/releasing.md)。

```bash
python3 -B experiments/frontier/build_release.py check-release
python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider
```

- `agent-workflow/`：基础工作流、模板与脚本。
- `experiments/frontier/`：多项目运行模块及发行工具。
- `tests/`：工作流测试；发行与多项目测试位于 `experiments/frontier/`。
- `docs/adr/`：设计决策。
