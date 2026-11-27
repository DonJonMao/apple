# 本轮科学计算准备的等价优化

R06 的旧100k冷报告剖析实际出现627,527次 `flatten_record`（累计34.14秒）及10,879次指标执行。该基线是带剖析器的完整冷生成，不是正常产品延迟；原始记录见 [cold-generation-hotspots.json](../artifacts/followup_20261127/performance/baseline-100k/cold-generation-hotspots.json)。

本次只消除两处确定的重复，不改变77项指标定义、可比性或参考要求：

- `science/semantics.py` 的公开入口仍执行原规范化；内部已规范化辅助函数复用同一行。`analysis_task` 从2次规范化降为1次，`outcome_series` 从4次降为1次；两行比较从4/6次降为2次。没有增加全局缓存，不会在源记录变化后复用旧值。
- `analytics/v13.py` 已完成当前快照的可见性、修订及冲突筛选。普通任务的 STR-11 仍逐任务检查实际 `reference_rows`，包括显式参考ID和协议规则。确认没有参考时，`science/engine.py` 复用本请求第一次正常执行产生的“缺少预指定参考”模板；每项结果独立复制，并保留该任务的全部源ID、组数、场次数、回顾身份和审计信息。有参考或例外输入仍走原计算器。所有未知条件任务保持独立，没有合并成可比组。

验证使用原公开计算器逐字段比较科学结果；覆盖真实Repository普通任务、预指定参考、显式context参考ID、未知条件、修订/删除/冲突、未来可见性与回顾模式。另核对1000个未知条件任务仍有1000份独立来源结果，但缺参考指标只执行一次；修改其中一份输出不影响其他任务或模板。规范化保留助力方向、RIR=0、RIR区间与原始JSON，输入随后变化重新计算。

优化前4项重复准备断言失败保存在 [science-preparation-before.xml](../artifacts/followup_20261127/actions/science-preparation-before.xml)。优化后定向等价回归在 [science-batch-r1.xml](../artifacts/followup_20261127/actions/science-batch-r1.xml)。最终整个 `tests/science` 为 **559 passed（11.95秒）**，见 [science-suite-final.xml](../artifacts/followup_20261127/actions/science-suite-final.xml) 和 [原始输出](../artifacts/followup_20261127/actions/science-suite-final.txt)；Ruff和差异空白检查通过。测试集合重叠，不能相加成新的总测试数。

这些检查证明结果等价及重复计算被移除，不证明完整报告已经达到15秒或任何浏览器目标。两档原压力夹具、个人夹具和读取/审计路径的实测，以本轮总性能交付为准；原性能失败工件继续保留。
