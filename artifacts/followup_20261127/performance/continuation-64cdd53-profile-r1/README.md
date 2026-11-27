# 当前冷路径续查结论

本目录是固定 64cdd53 源码、原合成 100k 夹具备份的插桩诊断，不能用 172.49 秒插桩耗时替代未插桩验收。`generation-source-manifest.json` 保存源码身份；`raw-table-integrity.json` 保存原始表完整性检查。压力冷报告、冷详情和冷预览预算仍未达到。

三次 `workflows.selection.scoped_metrics` 内的 `evaluate_subset` 合计 11.943 秒，分别服务于本期、历史和本期未完整周期行动观察，不能笼统称为三次重复全量。全局与普通 inventory 在该夹具当前窗口的 STR 结果相同，仍不足以直接复用：

- 全局快照向前包含比较／基线支持记录，scoped 快照按工作流窗口读取；窗口外行、draft／skipped／未知可见性等仍影响计数和排除。
- 计划原始槽位、reference inventory、参考声明／选择／任务聚合、按任务过滤的 outcomes 和受限 context exclusions 都可能不同；相同 task IDs 不证明完整输入相同。
- 全局 `REPORT-RECOMMENDATION-FOLLOWUP` 还包含健康来源及 numeric provenance，不能直接替换为训练子集结果。

因此不为压力特例增加复杂快捷路径。若今后复用，须先由生成时完整输入身份严格证明等价，并保留隔离；完整差异见[只读审查](../../continuation-readonly-review/README.md)。

冷页面驱动没有可扣除的固定延迟：`followup_page_benchmark.py` 从真实点击等待新 render identity、实际卡片、真实图点和状态完成；服务启动轮询及设置页准备在计时外。预览首次图比首事实晚约 1.35–1.46 秒，是真实首次前端成本，尚未证明可删。详情只跑 scoped 分析，预览仅所选周期及其对照，不隐式跑全量分析／RAG／冻结。

另以只读 [SQLite EXPLAIN 回执](summary-sql-explain.json)排除“summary 外层投影前，CTE 必然物化全部巨大 JSON”的猜测：当前 SQLite 3.41.2 内联 CTE，使用 session index，临时表仅存单列 session/event ID。没有执行业务查询或读取实际结果，也未据此改 SQL。

下一次诊断应分别量化当前 `history_summary_as_of` 的候选查询／JSON 投影／replay，详情首次 `plotly.express` 导入，以及浏览器 Plotly 资源加载／执行／绘图；不能使用早期 master profile 或驱动扣时来宣称秒级收益。本轮只读结论无新 src/tests/tools 修改。

已证实的次级比较优化另见[required facts 证据](../../comparison-required-facts/README.md)：187 项专项通过，纯内存阶段配对中位 0.7018 → 0.2845 秒，完整输出相等；这不是原压力夹具的完整报告验收。
