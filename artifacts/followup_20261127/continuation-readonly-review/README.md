# 64cdd53 续查：工作流复用边界与冷页面

本次仅审查代码、已有测量和只读 SQL 解释计划；没有新增产品改动、数据库修改或压力运行。此前已完成的比较事实裁剪及其 187 项专项结果单列于 `../comparison-required-facts/README.md`。

## 不增加“普通任务 ID 相同即复用”的快捷路径

`continuation-64cdd53-profile-r1/cold-generation.prof` 中，三次工作流 `evaluate_subset` 合计 11.943 秒，但分别服务于本期、历史和本期未完整周期行动观察，不能把三次都称为重复计算。同一当前窗口里，现有全局指标与普通 inventory 的实际结果相同只说明该夹具相同，不能证明所有合法输入均可互换。

必须保留的真实差异：

1. `analytics/v13.py::_analyze_uncached` 的原始训练快照也向前覆盖比较／基线支持范围；`workflows/selection.py::_strength_inputs` 按工作流窗口读取。窗口外行仍会进入全局 STR 的 `input_snapshot_n` 和排除列表，仅比较选中来源或任务 ID 会遗漏它们。
2. ordinary inventory 只由当前可见且状态为 completed／aborted／in_progress 的实际记录发现。draft、skipped、无结束时点、未知可见性、冲突及其他未被选中的原始行，仍可能影响全局选择排除、计数或 STR-09。相同任务 ID 不证明完整输入相同。
3. 全局 `plan_snapshot` 保留原始计划全部槽位；scoped 路径按实际 rows 的 set UUID 筛选槽位。缺失或未执行槽位可能改变分母。`session_plans` 还参与无日期状态的恢复，不能只比较已完成记录。
4. `reference_inventory` 来自各自完整原始快照，不能由可见结果或普通任务身份重建。首个工作组协议必须保留没有实际观测时间的真实位置；参考声明、选择和 `evaluate_all` 的独立任务聚合也可能改变输出。
5. scoped 路径按 selected task IDs 筛选 recommendation outcomes；全局保留全部适用结果。未知 task ID 或其他任务的反馈及其可见性排除不会因 ordinary task IDs 相同而消失。
6. `evaluate_all` 先派生并限制 daily facts／energy context；其 context exclusions 会附到每个 STR。scoped STR 使用较窄 inherited context，因此即使训练数值相同，完整排除和来源仍可能不同。调用者提供的比较、校准、参考、选择或其他覆盖声明也必须纳入身份。
7. `REPORT-RECOMMENDATION-FOLLOWUP` 全局相关输入包含健康记录，scoped 只含训练记录；`source_record_ids`、计数及 numeric provenance 本来就可能不同。不能根据内部 STR-27/28 值相同复用整个报告指标。

严格复用至少需要生成时记录完整、带顺序的规范化原始训练输入身份，窗口／截止／时区／模式／数据和算法身份，以及实际受限上下文、计划、reference inventory、outcomes 和 context exclusions 的身份；还需拒绝不等价的参考选择／任务聚合，保留可变结果隔离。当前公开 analysis 没有完整提供这些输入证据。为压力特例增加维护一套科学依赖清单的 fast path 不值得；保留现有独立计算，优先处理已证实的复制与重复遍历成本。

## 冷详情／预览没有可扣除的固定等待

`tools/followup_page_benchmark.py` 按实际 DOM 点击记录起点，等待新 render identity、真实非空卡片、真实 Plotly 点、状态控件消失。没有固定 sleep。设置页准备位于计时前；`isolated_app` 的 0.1 秒健康检查轮询仅在服务就绪阶段，不进入运行中点击样本。

render marker 位于 `app.py` 页面渲染结束处，所以“首事实”是保守完成边界，不是卡片首次插入 DOM 的精确时刻。现有失败不能通过移除该身份检查或扣除前端时间改成通过。

已有 r5 样本可见真实前端首次成本（单位秒）：

| 运行中冷场景 | 服务端页面 | 事实＋趋势 |
|---|---:|---:|
| 个人详情周 | 1.318 | 3.091 |
| 个人详情月 | 1.407 | 3.162 |
| 100k 详情周 | 1.424 | 3.386 |
| 100k 详情月 | 1.483 | 3.549 |

所有三档预览的首次图通常比首事实晚约 1.35–1.46 秒；这是实际首次图表前端路径，不是驱动 sleep。上述差值并非已定位的可删除成本。

心率详情只调用 scoped RHR／SDNN／疲劳及所选范围普通心率分析；预览只计算所选周／月和其上期同期，训练调用 `history_summary_as_of`。没有隐式运行全部 77 指标、RAG 或冻结报告。`body_pages.py` 顶层导入 `plotly.express`，普通心率小图确实使用它；导入／渲染是否有可避免的秒级成本尚需独立剖析，当前不宣称收益。

另核查了 training event SQL：虽然内部 CTE 写成 `SELECT *`，但当前 SQLite 3.41.2 对原合成 100k 库的实际 summary 查询解释计划会内联 CTE，首分支直接使用 `training_event_session_versions` 索引；VM 临时表只保存 session/event ID 列表，没有物化完整 request/before payload。因此排除“CTE 必然先复制全部巨大 JSON”这一猜测，没有据此修改查询。

当前没有识别出可严格证明、仅删除冗余工作即可稳定节省 ≥1 秒的冷页面改动。保留 r5 冷详情／压力预览预算失败，后续若继续优化，应先采集当前源码的服务端阶段和浏览器图表装载剖析，不能以早期 master profile 替代。
