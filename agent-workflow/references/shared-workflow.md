# 多项目共享工作流

## 定位

多项目共享工作流是低频扩展能力，不能压过单项目体验。它用于管理上下游项目之间的契约、交接、变更清单、下游消费和发布顺序。

## 默认目录

```text
.agent-workflow-shared/
  README.md
  projects.md
  interaction-map.md
  contracts/
  handoffs/
  change-manifests/
  impact-tracking/
  records/
```

## 关键文件

- `projects.md`：项目清单、角色、仓库路径、上下游职责。
- `interaction-map.md`：接口、契约、数据流、发布顺序和影响方向。
- `contracts/`：稳定契约。
- `change-manifests/`：单次变更影响面。
- `impact-tracking/`：下游消费状态。
- `handoffs/`：当前功能交接。

## 与单项目关系

单项目 `.agent-workflow/` 只弱引用共享目录位置和参与关系，不复制共享规则。共享工作流不应写入单项目事实。
