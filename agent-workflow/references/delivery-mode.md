# 外部交付模式（delivery）

外部周报、阶段报告、交付说明、验收报告和发布说明是独立交付物，不是内部 `progress` 的别名。

## 标准流程

```text
明确类型、周期、范围和受众
-> 生成 staging 草稿
-> 检查内部路径、工作项 ID、未确认判断和敏感信息
-> 审阅并批准
-> 固化 published 版本
-> 新版本替代、撤回或归档
```

生成器不得无范围扫描整个 `.agent-workflow/`。发布后的文档不能原地覆盖，内部追溯信息写入旁置 manifest，不进入外部正文。

## 目录边界

- `30-records/delivery/staging/`：可重生成草稿。
- `30-records/delivery/published/`：已批准的不可变交付版本。
- `30-records/delivery/archive/`：被替代、撤回或归档的版本。

Git 是可选的版本审阅增强，不是交付命令的运行前提。
