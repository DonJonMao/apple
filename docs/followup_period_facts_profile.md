# 周期报告本期事实阶段：单阶段剖析与待选优化

下述剖析只诊断原有 `period_facts`，没有在剖析期间修改科学计算代码，也没有生成整份报告。随后实施的窄范围优化单独记录在末节。冻结源码为 `/tmp/healthzip-followup-final-source-r3`；原 `synthetic-100000` 经 SQLite backup 复制到新的合成工作区。实际库有 100,001 条健康记录、10,000 个训练组和 100 场训练，未改变日期分布、条件或组数。调用使用 2026-11-21 16:00 UTC 截止、Asia/Shanghai 时区、本周、空选择上下文及非回顾模式，并保留真实报告已有的 `shared_report_inputs` 和普通任务仅请求 STR-11 的合同。

原始证据：[receipt.json](../artifacts/followup_20261127/performance/period-facts-profile-r1/receipt.json)、[调用及环境](../artifacts/followup_20261127/performance/period-facts-profile-r1/run.txt)、[可重放驱动](../artifacts/followup_20261127/performance/period-facts-profile-r1/driver-source.py)、[完整热点与调用方](../artifacts/followup_20261127/performance/period-facts-profile-r1/hotspots.json)、[cProfile 二进制](../artifacts/followup_20261127/performance/period-facts-profile-r1/period-facts.prof)、[10,000 个任务 ID](../artifacts/followup_20261127/performance/period-facts-profile-r1/task-identities.json)。驱动使用固定的新路径并拒绝覆盖已有回执或工作区；重放应选择新的路径。

受 cProfile 插桩影响，本次单次耗时 **40.943 秒**。这是诊断样本，不是冷验收、热 P95，也不能替代未插桩的约 25 秒事实阶段。Python 自动 GC 始终开启；执行前后冻结源码一致，结果保留全部 77 个指标及 10,000 个互异任务 ID。峰值 RSS 为 1,362,436 KiB；运行于共享 192 逻辑 CPU 的 aarch64 主机，初始 load average 为 19.15/24.04/24.62，不能代替普通个人设备结果。任务清单证明任务数量和独立 ID，不单独声称对完整任务数值做过前后等价验收。

| 本次调用路径 | 调用数 | 累计秒数 | 含义 |
| --- | ---: | ---: | --- |
| `period_facts` | 1 | 40.943 | 唯一受测入口 |
| 主科学引擎 `evaluate_all` | 1 | 19.753 | 全部 77 指标，含其子调用 |
| `select_as_of` | 38 | 8.243 | 跨所有调用方，不能与父项相加 |
| `report_comparison` | 1 | 2.501 | 三个支持窗口及其派生 |
| 上项内的 `select_as_of` | 3 | 1.657 | 同截止时间重新解析全部输入 |
| 上项内的 `derive_report_context` | 3 | 0.698 | 最终只消费 RHR、SDNN、观测睡眠 |
| 全部 `prepare_strength` | 5 | 0.778 | 部分准备已被引擎复用 |
| 报告行动复评内的 `prepare_strength` | 1 | 0.287 | 对 STR-27/28 并非必需 |
| `_ordinary_reference_result` | 10,000 | 6.472 | 保留各普通任务的独立结果，主要成本来自深复制 |
| `snapshot` | 1 | 5.684 | 包含训练事件还原 |
| `events_as_of` | 1 | 4.617 | 上项中的训练事件历史读取 |
| `_bounded_context` | 3 | 0.001 | 已共享，继续优化收益很小 |

上述累计时间存在父子包含，不能相加估计可节省时间。旧 `compute-r1-profile` 对应的 `analytics/v13.py`、`science/engine.py`、`science/contracts.py`、`science/reports.py`、`science/strength.py` 五份源码与当前文件 SHA256 一致；但旧 profile 覆盖四次分析及整报告，不应直接用于宣称本次单阶段收益。

## 建议一：只在比较函数内复用支持窗口的修订解析

当前 `science/reports.py::report_comparison` 对 current/previous/reference 三个窗口分别调用 `select_as_of`，每次都扫描所有标准化输入（含 10,000 训练组），随后调用通用 `derive_report_context`，最后丢弃 RHR、SDNN 和睡眠以外的所有派生事实。

可先对三个有效窗口的联合范围以相同 cutoff 和 overlap 规则执行一次完整 `select_as_of`，保留其输出顺序、`_source_id`、修订身份与事件边界，再从已经解析完修订的记录按各窗口原有重叠条件选取实际输入，局部只派生这三类比较事实。完整可见睡眠历史仍单独按原规则提供给各窗口，不跨窗口预聚合睡眠事件。另一种较小方案是按真正相关逻辑 ID 保留其全部修订后再选择，但须保留缺失 ID 行的原始位置身份。

**不能在修订解析前直接按 canonical type 删除记录。** 早期 RHR 改成另一类型、已知删除、未来事件修订、冲突记录等都可能使旧 RHR 失效；先过滤会复活旧记录。缺 ID 时 `select_as_of` 使用原位置生成来源 ID，缩短列表也可能改变身份。这里的复用限定在同一函数、同一截止时间，不引入跨请求缓存，也不缩减其他 77 指标、实际任务库存或 MetricResult 的输入。

必要等价验证包括：跨类型修订、删除/冲突/未来事件、晚到及未知可见性、缺 ID 原位身份、多个来源/协议、跨午夜和跨窗口睡眠、部分周期，以及空窗口。比较完整输出与既有实现（含来源 ID、顺序和窗口），再核对完整 77 指标和全部 10,000 独立任务。该路径本次仅占 2.501 秒；实际可节省量尚未测定，不能宣称它解决剩余约 25 秒的全部成本。

## 建议二：行动复评不准备未消费的力量集合

`report_metric("REPORT-RECOMMENDATION-FOLLOWUP")` 每次先 `prepare_strength(rows, context)`，再把结果交给 STR-27/28。实际 STR-27 分支只读取 `recommendation_outcomes`；STR-28 使用相同反馈及 STR-27 的结果，递归传递 `work/refs` 但不消费它们。可在这条窄路径去掉未使用的准备（或仅对这两个分支延迟准备），继续向 `result` 传递原 `rows`，保留原来源、计数域、执行状态、分层和反馈身份。不要把 REPORT overlap 选择结果与 STR 选择结果未经核对混用。

验证应覆盖全部执行/反馈状态、多个策略/任务分层、空反馈及原行来源/计数，精确比较 STR-27、STR-28 和报告复评嵌套结果。该准备本次只有 0.287 秒，属于小范围清除重复工作，不能作为达到完整报告 15 秒目标的依据。

更大的既有成本（10,000 份独立 STR-11 结果的深复制、训练历史还原、其他选择调用）仍明确保留；本次未以共享可变输出、减少任务身份或跳过全部指标来压低时间，也未将这些诊断写成已完成优化。

## 随后实施与验证

仅实施建议一的共同修订解析部分：[reports.py](../src/healthzip/science/reports.py) 以三个有效窗口的联合范围对全部原始 `rows` 执行一次 `select_as_of`，再用已经解析的事件边界做各窗口相同的 overlap 过滤。没有按 canonical type 缩减 `derive_report_context` 输入，没有改通用 `select_as_of`、其他指标入口或算法版本。所有窗口仍消费全部适用实际行，睡眠保留原完整可见历史。建议二尚未实施。

[新等价测试](../tests/science/test_followup_report_comparison_preparation.py) 保留原函数算法作为 oracle，并另断言实际值、来源身份、修订失效和选择次数。14 项覆盖跨类型修订、删除、未来事件、冲突、修订移出联合范围、晚到修订、无 ID 原位、未知可见性及 retrospective、跨午夜与 DST offset 睡眠、独立前期窗口、空结果/零长度前期，以及全部 77 指标值（只排除运行时 `computed_at`）。完整原行选择次数由 3 次变为 1 次；其他指标输入与输入记录内容不变。

必要回归共 **63 passed，2.09 秒**；范围包括新增测试、健康事实比较、状态/能量/预测、选择准备和参考批处理。Ruff 通过。回执及源码身份见 [comparison-preparation/receipt.json](../artifacts/followup_20261127/comparison-preparation/receipt.json)，原始测试记录见 [targeted-r2.txt](../artifacts/followup_20261127/comparison-preparation/targeted-r2.txt)。

失败证据原样保留：[before.txt](../artifacts/followup_20261127/comparison-preparation/before.txt) 为优化前 3 次完整选择的预期失败；[targeted-r1.txt](../artifacts/followup_20261127/comparison-preparation/targeted-r1.txt) 为新测试误把 11 月 2 日上午记录放进从该日中午开始的部分前期，精确 oracle 比较已通过但独立预期值不成立。测试日期修正至 11 月 3 日后重跑，未改变任何产品时间规则。

本次没有重新运行 10 万/100 万压力夹具，也没有新的浏览器耗时或 10,000 任务前后数值等价证据。前述 40.943 秒属于修改前插桩诊断，不能作为修改后的性能结果；当前只证明重复选择消除与上述正确性回归，实际整体收益须另测。
