# 008：能力渐进生成完成

## 已完成

- 新增能力模块模型、依赖闭包和 `minimum`、`standard`、`advanced` profile。
- 新增 `.agent-workflow/.capabilities.json` 启用清单及 `list`、`suggest`、`enable` 命令。
- 初始化默认使用 `minimum`，只生成核心结构和工作项能力。
- 检查工具只检查已启用能力，并兼容无能力清单的旧完整项目。
- 启用和升级只补齐缺失内容，不覆盖已有文档。

## 验证

- Profile 原型：`4 passed`；能力模块原型：`4 passed`。
- 完整项目测试：`26 passed`。
- 空项目默认初始化与检查：通过。
- 按需启用 `delivery` 并自动补齐依赖：通过。
- Python 脚本编译和 `git diff --check`：通过。

## 结论

第三个问题已完成实现和场景验证。项目结构以能力模块按需生长，Profile 仅作为快捷组合，升级建议不自动执行；三个外部案例未修改。
