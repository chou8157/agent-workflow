# Agent 结构化声明契约

实验定位：Agent 可组织已读取事实的顺序和分组；程序负责事实、节点覆盖与最终展示。当前适配层只展示工作项状态，不代表业务活动周报或完整子 Agent 调度已经接入。

## 输入与输出

输入只含事实引用、标题、状态、完成时间与时间是否已知。完整输入超过 16 KiB 时拒绝启动，不静默截断。模板从实际输入的第一个事实生成，不带固定的示例项目。

输出必须是原始 JSON，不加代码围栏：

```json
{
  "sections": [
    {
      "fact_refs": ["project/W-example"],
      "claims": [
        {"fact_ref": "project/W-example", "field": "status", "value": "completed"}
      ],
      "text": "此文本不直接用于最终事实展示。"
    }
  ],
  "omitted": []
}
```

## 确定性校验

- 根对象、段落和声明的字段必须与上述层级一致；拒绝缺字段和额外字段。
- 允许声明 title、status、completed_at、completed_at_status；值和类型须与本次原事实相等。
- 每个引用事实至少有一个声明，不允许重复事实引用、重复字段声明或重复事实身份。
- omitted 必须是本次已知且唯一的事实引用；与已覆盖事实不重叠，所有事实都必须被覆盖或显式省略。
- 原始 JSON 超过 16 KiB、重复键、非法常量、无效 JSON 或过深嵌套均拒绝；不修补模型输出。

## 展示与失败路径

使用 agent_blind_eval.render_with_fallback(summary, raw_draft)：

- 合法草稿只提供顺序，render_verified() 重新从原 summary 取事实；Agent 的 text 从不成为展示正文。
- 聚合状态、失败/跳过节点与显式省略由程序展示，空事实不等于没有工作。
- 非法草稿返回 deterministic_fallback，固定展示全部已读事实和原有缺口；保留拒绝原因，不伪装成 Agent 通过。
- 来源字段按字面值转义。事实的语义真实性仍依赖节点内权威记录；这里不证明源文档一定正确。
- text_semantics_verified 始终为 false。这条路径避免使用未核验自由文本，没有实现自由文本语义自动核验。
- 未接入稳定版 CLI；活动日期窗口仍走 mvp_light.activity_window()，本适配层不声称提供周报。

## 当前证据

- 早期三组调试经原始日志复核为 0/2、2/2、0/2；提示不同，不合并计算稳定成功率。旧 v3 的 1/2 来源于错误重建，已作废。
- 冻结输入的两次 fresh 调用为 2/2，输入读取字节、原始 final、独立会话和展示缺口均已核对。
- 证据入口：evidence/mvp-light-agent-frozen-20261015/results.json。
- 两个固定输入样本不足以证明一般模型可靠性；当前结论仅支持继续集成有固定格式降级的实验版本。
