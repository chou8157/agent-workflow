# 工作项入口

恢复此工作项时，按以下顺序读取：

1. 项目根 `AGENTS.md` 和 `.agent-workflow/README.md`。
2. 本目录的 `current-status.md`。
3. 本目录的 `work-item.md`。
4. 如涉及代码状态，读取 `code-state.md`；如需追溯细节，再按需读取 `changes/`、`progress/` 和局部日志。

生命周期状态以本目录的 `.state.json` 为唯一机器事实源。`work-item.md` 保存需求和背景，`current-status.md` 保存阶段、进展、阻塞和下一步，不重复维护生命周期状态。

本目录只记录当前工作项的事实，不复制项目公共规则、架构或其他工作项的进展。
