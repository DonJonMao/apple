# 本轮科学计算准备的等价优化

R06 的旧100k冷报告剖析实际出现627,527次 `flatten_record`（累计34.14秒）及10,879次指标执行。该基线是带剖析器的完整冷生成，不是正常产品延迟；原始记录见 [cold-generation-hotspots.json](../artifacts/followup_20261127/performance/baseline-100k/cold-generation-hotspots.json)。

本次只消除两处确定的重复，不改变77项指标定义、可比性或参考要求：

- `science/semantics.py` 的公开入口仍执行原规范化；内部已规范化辅助函数复用同一行。`analysis_task` 从2次规范化降为1次，`outcome_series` 从4次降为1次；两行比较从4/6次降为2次。没有增加全局缓存，不会在源记录变化后复用旧值。
- `analytics/v13.py` 已完成当前快照的可见性、修订及冲突筛选。普通任务的 STR-11 仍逐任务检查实际 `reference_rows`，包括显式参考ID和协议规则。确认没有参考时，`science/engine.py` 复用本请求第一次正常执行产生的“缺少预指定参考”模板；每项结果独立复制，并保留该任务的全部源ID、组数、场次数、回顾身份和审计信息。有参考或例外输入仍走原计算器。所有未知条件任务保持独立，没有合并成可比组。

验证使用原公开计算器逐字段比较科学结果；覆盖真实Repository普通任务、预指定参考、显式context参考ID、未知条件、修订/删除/冲突、未来可见性与回顾模式。另核对1000个未知条件任务仍有1000份独立来源结果，但缺参考指标只执行一次；修改其中一份输出不影响其他任务或模板。规范化保留助力方向、RIR=0、RIR区间与原始JSON，输入随后变化重新计算。

优化前4项重复准备断言失败保存在 [science-preparation-before.xml](../artifacts/followup_20261127/actions/science-preparation-before.xml)。优化后定向等价回归在 [science-batch-r1.xml](../artifacts/followup_20261127/actions/science-batch-r1.xml)。最终整个 `tests/science` 为 **559 passed（11.95秒）**，见 [science-suite-final.xml](../artifacts/followup_20261127/actions/science-suite-final.xml) 和 [原始输出](../artifacts/followup_20261127/actions/science-suite-final.txt)；Ruff和差异空白检查通过。测试集合重叠，不能相加成新的总测试数。

这些检查证明结果等价及重复计算被移除，不证明完整报告已经达到15秒或任何浏览器目标。两档原压力夹具、个人夹具和读取/审计路径的实测，以本轮总性能交付为准；原性能失败工件继续保留。

## f863e2e 后的冷计算准备优化

最新100k完整冷报告诊断仍为210.34秒（开启cProfile，非验收延迟）。其中 `evaluate_all` 四次累计35.35秒，497,127次规范化累计28.71秒，100,000次负荷分量计算累计10.95秒。原始剖析保存在 [f863冷报告](../artifacts/followup_20261127/performance/f863-100k/cold-generation.prof)，未覆盖原失败结果。

本次在既有执行器内继续消除重复：

- `select_as_of` 在一次调用中解析窗口边界一次，同一可见时间的解析同时用于截止检查与修订排序。DST、半开边界、晚到修订、删除、冲突和未知可见性规则不变，不在记录上增加准备标记。
- 仓库分析复用该快照已为参考库存规范化的训练行；全局77项、任务发现和普通任务使用同一份准备结果。调用者显式传入的参考声明仍单独保留，不被默认库存替换。
- 科学执行器向力量计算传递已规范化的行，直接调用语义函数仍执行原规范化。负荷计算只传递实际使用的对称装载、有效杆重和器具数量，避免反复复制整行原始JSON和来源字段。
- 同一请求、同一组选定记录的负荷显示、记录量计算和公式估计复用负荷分量算术。缓存随本次调用结束，记录修改后的新请求重新计算；公开结果的可变原因列表另行复制。
- 行动后续报告中的STR-27、STR-28及其内部调用复用一次参考准备；各自结果仍保留原来的记录计数域和完整来源ID，没有借用来源域不同的全局指标。

固定微诊断比较空数据、1000个普通未知条件训练组、23条混合参考/负荷/可见性记录。每个场景均计算全部77项；仅排除生成时钟 `computed_at` 后，完整序列化输出逐字一致，包含所有数值、快照hash、任务、分组、来源和限制。1000组样例的规范化次数从13,000减到2,000，时间解析从43,208减到22,250，负荷算术从4,000减到1,000；带剖析器时间由1.781秒变为1.180秒。混合场景由1.404秒变为1.353秒，空数据基本不变。它们是小规模诊断，不能替代原10万/百万健康记录＋1万训练组的完整报告验收，也不是P95。

可复核脚本、每阶段源码hash、完整压缩输出、剖析器文件及逐字段比较见 [science-compute](../artifacts/followup_20261127/science-compute/equivalence-and-profile.json)。4个新增边界测试的修复前失败保存在 `selection-before.xml`；最终科学与报告消费者专项575项通过，另有包含新增缓存隔离用例的7项通过，两组重叠，不相加。[575项回执](../artifacts/followup_20261127/science-compute/science-final-r6.xml)、[7项回执](../artifacts/followup_20261127/science-compute/selection-load-final.xml)及所有中间失败日志均保留。Ruff与差异检查通过。本次源码范围为 `analytics/v13.py` 和 `science/{contracts,engine,reports,semantics,strength}.py`；完整报告与页面预算仍由后续实测单独判定。
