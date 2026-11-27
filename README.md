# agent-workflow

`agent-workflow` 是一个面向 Codex 的项目工作流 Skill。它把项目规则、任务上下文、进展记录和验证结果放在项目自己的文档目录中，让智能体能够稳定地接手项目、继续工作并完成交接。

当前源码主线版本是 `1.2.0`。`main` 是集成开发主线，正式安装请从 [Releases](https://github.com/chou8157/agent-workflow/releases) 选择已经发布的完整发行包；版本号本身不代表对应版本已经发布。

## 它解决什么问题

普通的智能体会话容易遇到几个问题：规则散落在不同文件中，任务上下文随着会话结束丢失，多个需求互相覆盖，验证结果和实际交付无法对应。`agent-workflow` 为这些内容提供固定入口和持续记录：

- 用项目根目录的 `AGENTS.md` 作为智能体入口。
- 用 `.agent-workflow/` 保存项目规则、理解资料、任务、风险和验证记录。
- 用独立工作项保存多个需求、缺陷或迭代，避免上下文互相覆盖。
- 在升级项目工作流时保留用户修改，识别来源不明文档和内容冲突。
- 用验证记录区分代码测试、文档检查、发行包校验和实际运行验收。

## 适用场景

它适合以下类型的项目：

- 新项目初始化，需要让智能体快速了解项目规则和当前阶段。
- 已有项目接手，需要从上次会话继续任务。
- 同时维护多个需求、缺陷或版本迭代，需要分别记录进展和验收。
- 需要把工作成果、风险、决策和验证过程留在项目中，方便后续交接。
- 已经使用旧版工作流，需要检查、升级、恢复或回滚工作流文件。
- 需要按项目生成独立交付文档，并保留事实来源和验证边界。

它不替代代码仓库、任务系统、部署平台或生产监控，也不会自动扫描和迁移所有项目。项目升级、技能更新和外部交付都需要明确指定范围。

## 安装

### 使用条件

- 支持 Codex Skill 的运行环境。
- macOS 或 Linux。
- Python 3.8 或更高版本。
- 基础工作流不需要额外 Python 包。
- 一个完整发行包。只复制源码中的 `agent-workflow/` 子目录，不能替代完整发行包。

### 让 Agent 自动完成安装

如果不想手动执行命令，可以把下面的提示词发送给支持终端和文件操作的 Agent。将其中的发行包地址或本地路径替换为实际值：

```text
请帮我安装 agent-workflow。

发行包来源：<完整发行包的下载地址、本地压缩包或本地解压目录>
安装目标：请优先检查 CODEX_HOME/skills 和 ~/.codex/skills；如果仍无法确认当前 Codex 使用的 skills 根目录，再询问我，不要猜测。

请直接完成以下流程：
1. 如果来源是下载地址，先下载到临时目录；如果是压缩包，先解压到临时目录。不要把 Git main、源码仓库或 agent-workflow/ 子目录当成发行包。
2. 确认发行包目录同时包含 `SKILL.md`、`scripts/release_package.py`、`release-manifest.json` 和 `VERSION`，检查 Python 版本后先执行发行包 `verify`。
3. 如果安装目标已有 `agent-workflow`，先生成只读 `update-plan`，核对当前版本、目标版本、来源指纹和备份位置；确认没有使用旧版或新版 Skill 写入项目的 Agent 会话后，再按更新流程执行，并携带所需的 `--writers-stopped`。不要用首次安装命令覆盖已有安装。
4. 如果目标不存在，执行首次 `install`。
5. 安装或更新后再次执行 `verify`，并检查实际安装目录中的版本和文件清单。
6. 最后用简短结果告诉我：发行包来源、版本、安装目录、执行的是首次安装还是更新、校验结果，以及是否需要重新打开 Agent 会话。

不要修改我的项目代码、项目中的 .agent-workflow/ 目录或其他技能；如果发行包校验失败、来源不明或发现冲突，请停止并说明原因。
```

Agent 应该把安装和项目升级分开处理。安装完成后，新建一个 Codex 会话，再使用 `$agent-workflow`。

### 手动安装（命令行）

从 [Releases](https://github.com/chou8157/agent-workflow/releases) 下载对应版本的压缩包，解压后将解压目录记为 `PACKAGE`，再执行：

```bash
PACKAGE="/path/to/agent-workflow"
SKILLS_ROOT="/path/to/codex/skills"

python3 -B "$PACKAGE/scripts/release_package.py" verify "$PACKAGE"
python3 -B "$PACKAGE/scripts/release_package.py" install "$PACKAGE" \
  --skills-root "$SKILLS_ROOT"
```

如果使用 Codex 的默认技能目录，`SKILLS_ROOT` 通常是 `~/.codex/skills`；实际路径以本机配置为准。

`verify` 会检查发行包清单、文件摘要、产品版本和工作流模板；校验通过后再执行安装。安装完成后新建一个 Codex 会话，使用 `$agent-workflow` 调用技能。

### 从源码构建安装包

源码仓库适合开发和维护者使用。构建完整发行包前先运行版本检查和测试：

```bash
python3 -B experiments/frontier/build_release.py check-release
python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider
```

构建时使用仓库外的输出目录：

```bash
python3 -B experiments/frontier/build_release.py build \
  --output "/path/to/package-output" \
  --archive "/path/to/agent-workflow.tar.gz"
```

构建完成后，使用上面的 `verify` 和 `install` 命令安装生成的完整包。维护者发布流程见 [维护者发布指南](docs/releasing.md)。

## 开始使用

安装后，在 Codex 中直接用自然语言调用：

```text
$agent-workflow 初始化当前项目
$agent-workflow 加载当前项目，继续指定的工作项
$agent-workflow 检查当前项目工作流
$agent-workflow 记录本次工作
```

已有 `.agent-workflow/` 的项目可以直接加载，不需要重新初始化。项目中通常会看到：

```text
AGENTS.md                         智能体入口和项目级规则
.agent-workflow/                  项目工作流目录
├── 00-core/                      核心规则和工作流
├── 10-project/                   项目理解、约定和依赖
├── 15-modules/                   按需启用的能力模块
├── 20-gates/                     任务、质量和安全门禁
└── 30-records/                   状态、工作项、进展和验证记录
```

工作流会从项目已有事实开始，不会为了填满目录而编造项目背景、历史日期或验收结果。

## 常用工作方式

### 接手项目

让智能体先加载项目，再指定要继续的工作项。它会优先读取项目规则、公共状态和目标工作项，避免从 Git 提交信息猜测当前任务。

### 开始一项新工作

明确说明需求、缺陷或版本迭代目标。多个工作项同时进行时，应指定目标工作项；工作完成后记录实际变更、验证结果和未完成事项。

### 检查工作流

检查会发现入口文件、核心目录、工作项状态和必要记录是否完整。检查结果中的“结构完整”不等于业务功能已经验收，仍需结合具体测试和运行结果判断。

### 升级技能或项目

技能程序更新和项目工作流升级是两个范围：

- 技能更新只替换安装的程序文件，并保留安装备份。
- 项目升级只处理明确指定的项目，并先生成只读计划。
- 计划绑定当前内容；计划生成后内容变化，必须重新生成计划。
- 已有入口文档会通过基线和三方合并保护用户修改；冲突需要人工审阅。
- 升级中断时可恢复项目事务，恢复后需要重新生成计划。

详细命令见 [使用与升级指南](docs/usage.md)。

## 版本规则

产品版本和项目工作流结构版本分别管理：

- 产品版本表示安装的 Skill 程序，例如 `1.2.0`。
- 工作流结构版本表示项目目录和规则是否需要迁移，例如结构 v6。
- 更新 Skill 不会自动升级所有项目，也不会强制项目重新初始化。
- 只有明确要求试验能力时才使用预览版本；正式版使用不带后缀的版本号。
- 已发布版本对应固定标签和发行包，不能用后续提交覆盖旧版本内容。

版本来源见 [VERSION](VERSION)，变化记录见 [CHANGELOG.md](CHANGELOG.md)。

## 文件和数据边界

项目工作流文件属于项目自己的资料，通常应随项目仓库管理。Skill 安装目录只保存程序、模板和脚本；更新 Skill 不会覆盖项目业务代码、任务历史或外部项目文件。

项目升级产生的文档基线、事务日志和恢复信息只服务于本次明确的升级范围。发生冲突时保留现场，不用旧模板强行覆盖当前项目内容。

## 文档导航

- [使用与升级指南](docs/usage.md)：安装、更新、项目检查、项目升级、恢复和回滚。
- [维护者发布指南](docs/releasing.md)：版本、构建、测试、发行包和正式发布检查。
- [变更记录](CHANGELOG.md)：各版本的功能和兼容性变化。
- [设计决策](docs/adr/)：项目规则和架构选择的背景。
- [多项目运行模块说明](experiments/frontier/README.md)：完整发行包中多项目能力的说明和验证边界。

## 开发与验证

完整发行包由基础工作流和多项目运行模块组合构建。提交代码前至少运行：

```bash
python3 -B experiments/frontier/build_release.py check-release
python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider
```

服务环境、PostgreSQL、Neo4j 或真实外部系统未执行时，会在验证记录中单独标明，不能用本地测试代替实际运行验收。
