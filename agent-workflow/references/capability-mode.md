# 能力启用模式

工作流按能力模块渐进生长，不在初始化时复制所有目录。核心能力包括 `core`、`work-items`、`decisions`、`contracts`、`knowledge`、`evidence`、`delivery`、`audit` 和 `shared-workflow`。

- 默认 `minimum` 只启用 `core + work-items`。
- Profile 是能力组合快捷方式，不是固定目录快照。
- 启用能力时自动补齐显式依赖，并写入 `.agent-workflow/.capabilities.json`。
- `check` 只检查已启用能力；`suggest` 只读提出建议；`enable` 只补齐缺失文件，不覆盖已有内容。

标准流程：`扫描项目 -> 给出能力建议 -> 用户确认 -> 启用能力 -> 补齐结构 -> 自检`。
