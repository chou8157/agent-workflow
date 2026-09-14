# 009：当前项目能力渐进自托管试用

## 实际操作

- 执行 `capability_context.py suggest`，识别已有交付能力。
- 执行 `capability_context.py enable core work-items delivery`，自动补齐 `evidence` 依赖。
- 读取 `.capabilities.json`，确认启用清单为 `core、work-items、evidence、delivery`。
- 对既有 `agent-workflow/SKILL.md` 做哈希前后比较，确认启用过程未覆盖已有文档。

## 验证结果

- 当前项目工作流检查：`ok: true`。
- 升级状态：版本 `5`，无待升级动作。
- 全量测试：`26 passed`。
- 既有 Skill 文档哈希未变化。

## 结论

能力清单可以在已有完整项目中安全建立；依赖自动补齐、检查按启用能力执行、已有文档保持不变，符合预期。
