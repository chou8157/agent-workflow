# 002：当前项目自托管状态试用

## 试用范围

- 项目：`/Users/yizhoucp/Documents/agent-workflow`
- 工作项：`W-20260911-workflow-optimization`
- 目标：验证状态写入、读取、转换和校验是否形成闭环。

## 实际操作

1. 列出当前工作项并读取目标工作项状态。
2. 执行 `in_progress -> blocked`，提供阻塞原因。
3. 执行 `blocked -> in_progress`，验证恢复。
4. 执行 `in_progress -> completed`，验证完成时间写入。
5. 执行 `completed -> in_progress`，验证重新打开。

## 发现与修复

第一次试用发现：重新打开已完成工作项后，`completed_at` 未清理，导致状态文件校验失败。

已修复 `task_context.py`：非 `completed` 状态统一清理 `completed_at` 和 `completed_at_unknown`，并补充回归测试。

## 结论

修复后状态转换链路通过；当前项目可以继续进行检查和升级验证。三个外部案例未修改。
