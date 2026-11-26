# 维护者发布指南

## 版本来源与规则

根目录 `VERSION` 是产品版本的唯一人工输入。构建时自动生成包内 `VERSION`、manifest 版本、发行信息与发布说明。README 引用版本文件，不重复维护当前版本文字。

- 修复兼容问题使用补丁版本，新增兼容能力使用次版本，破坏受支持契约时评估主版本。
- 预览版本使用 `-beta.N`，需要冻结候选验证时可使用 `-rc.N`；正式版移除预发布后缀，生成新的发行包。
- 已发布版本与标签不可换内容。保留 beta 原包，不通过改文件名或修改其 manifest 将旧包冒充正式包。
- 工作流结构由包内模板 `WORKFLOW_VERSION` 管理。项目结构、入口路由或强制规则变化才需要相应迁移；产品发版不会自动迁移所有项目。
- 历史 CHANGELOG、测试中的历史版本样例和原始证据保留当时版本，不全仓替换。

源码 main 是集成主线，发行标签采用 `v<产品版本>`。发布渠道由版本后缀派生为 `preview` 或 `stable`；包内 stable 只表示版本类型，不证明包已经发布。

## 准备候选

修改 VERSION，并在 CHANGELOG 首个“未发布”章节记录本次变化及升级影响。正式发布时将该章节改为“产品版本 - YYYY-MM-DD”，日期填写实际发布日期。

```bash
python3 -B experiments/frontier/build_release.py check-release
python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider
```

构建输出放在源码仓库外，用 `PACKAGE_OUTPUT` 和 `ARCHIVE_OUTPUT` 指定新的绝对路径：

```bash
python3 -B experiments/frontier/build_release.py build \
  --output "$PACKAGE_OUTPUT" --archive "$ARCHIVE_OUTPUT"
python3 -B "$PACKAGE_OUTPUT/scripts/release_package.py" verify "$PACKAGE_OUTPUT"
```

普通构建允许制作本地候选。`release-info.json` 记录源码提交、是否有未提交内容，以及实际交付内容摘要；没有可识别的 Git 来源时提交和状态为 null。没有嵌入构建时间或本机绝对路径，同一输入可重复构建。

候选包必须在独立临时技能目录验证：首次安装、旧包到新包的 update、重复执行、rollback 和项目核心能力。检查结构与状态前后保持预期，禁止使用真实安装目录充当测试目录。

## 正式发行检查

准备精确的发布提交，确认本次变更和验证证据已经纳入审查。以待发布标签作为 `RELEASE_TAG`，再从干净提交构建：

```bash
python3 -B experiments/frontier/build_release.py check-release \
  --require-clean --expected-tag "$RELEASE_TAG"
python3 -B experiments/frontier/build_release.py build \
  --require-clean --expected-tag "$RELEASE_TAG" \
  --output "$PACKAGE_OUTPUT" --archive "$ARCHIVE_OUTPUT"
```

源码脏状态、未知 Git 来源或标签与 VERSION 不一致会阻断这一构建。发布前另确认 CHANGELOG 已填写真实日期，当前代码未自动发布标签或 Release。

完整包继续由 `agent-workflow/` 和 `experiments/frontier/` 组合生成。manifest 维持 v1 协议，新增发行信息作为普通交付文件纳入清单；旧包没有这些文件仍可校验。

## 发布与读回

完成发布授权后，建立与已验证提交一致的标签和 Release，附完整压缩包、摘要及包内生成的 `release-notes.md`。预发布标志应与版本后缀一致。

下载实际发行资产，重新校验摘要、包版本、结构版本及源码提交。核验通过后再更新对外的稳定发行入口。中断重试仅复用内容一致的既有资产，不覆盖不一致的已发布内容。

发行包准备、公开发布和本机安装是三个分别可验证的步骤。发布之后若需要更新本机，使用[安装更新流程](usage.md)，并单独核验结果。

## 持续集成

仓库的发行检查工作流执行版本检查、自动化测试、构建、独立包校验，并保存候选压缩包与摘要供审查；它不会创建正式 Release 或更新用户安装。

声明支持的系统与 Python 版本通过矩阵验证。跳过项和尚未执行的远端矩阵仍需如实记录，不能用一次本机通过代替全部环境验收。
