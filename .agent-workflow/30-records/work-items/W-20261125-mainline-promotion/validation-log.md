# 验证记录

## 2026-11-25：主线切换前核对

- 远端 `main=31989c7`、实验分支 `0c79386` 与本地一致，实验提交直接基于原主线。
- v5 源码压缩包的 184 个受 Git 管理的文件与原提交逐字节一致，详见 `verification.json`。
- 原发行包、从实验源码重新构建的发行包与本机安装版完全一致（81 个交付文件及 manifest）。
- 发行包 SHA-256：`d85fdf8c0f82957b92dfd561f75e0812e8f45d65ed178cda193bb8e7031b59ea`。
- manifest SHA-256：`72426084805223bc4e7e20f609ab4491861179167474ea263938d3dffd2d023e`。
- 安装完整性检查：verified；版本 `1.1.0-beta.1`，模板结构 6。
- 命令 `python3 -B -m pytest tests experiments/frontier -q -p no:cacheprovider`：641 passed, 38 skipped，耗时 132.87 秒。
- 实验工作区工作流检查：ok=true，issues=[]。
- 已创建 `v5-20261125` 标签并完成 main 快进合并；远端推送结果后续追加。

## 2026-11-25：主线交付

- main 工作流检查：ok=true，issues=[]；git diff --check 通过。
- `git push --atomic origin main:main refs/tags/v5-20261125:refs/tags/v5-20261125` 成功。
- 远端 main 已由 `31989c7` 前进到 `0c79386`，v5-20261125 标签已建立；实验分支保持原提交。
- 本轮只增加主线说明、备份索引和工作项记录，不改变已验证的运行包源码；完整回归结果继续对应实际合入的实验提交。
- 远端只读回查确认 main 和实验分支均为 `0c79386739412ae956c353e430a3f6a4c1524a80`；备份标签解引用为 `31989c7b909529f0f36d04558bba657f9b913c2f`。
- 收口后工作流检查仍为 ok=true；4 处本地 Markdown 链接均有效；安装包再次校验 verified。
- 活动记录：`activity-aab5a0263aeec9bbd60f885f`，证据为本工作项 progress/001-mainline-promotion.md 第 5 至 9 行。
