# 912aefc 状态/能量/导入审查

基线：`912aefc93b9bd9c1cebf297a10728c69c827e266`。已读 AGENTS.md、CODEX_GOAL.md、DESIGN_SPEC.md、V1_3_GOAL.md。仓库只读，无源码修改；合成ZIP、数据库、脚本、输出都在仓库外 `review912/state/`。

## 原 R11–R14 状态

| 原编号 | 结论 | 实际实现和验证 |
|---|---|---|
| R11 跨日累计能量误标 kcal/day | 已修复 | `energy.py:213–215,231–232` 明确为累计 kcal，并提供独立完整日均值。真实XML导入2天结果为4400kcal/2200kcal-day。 |
| R12 不同日期/区间/设备分量拼总量 | 已修复 | `device_energy_days` 按当地日期、stream及支持区间配对；不同日期、互不重叠区间不合成总量，设备来源分开。 |
| R13 多晚睡眠累加冒充主睡眠 | 已修复 | 无明确main_sleep_episode返回insufficient；历史系列命名为按结束日期已观察睡眠，不再称主睡眠。 |
| R14 CSV秤来源丢失 | 已修复 | adapter与stream_key保留source；scale_A与scale_B独立，每流只有一点时无趋势。 |

定向命令：

`PYTHONPATH=src /workspace/scratch/a74a838d7f65/apple_review_0a943b4/.venv/bin/python -m pytest -q tests/integration/test_review_analysis.py -k 'r11 or r12 or r13 or r14'`

结果：5 passed, 5 deselected（1.15s）。未跑整套pytest。

## 新发现 1 — [P2] 未转换的原数值被贴上目标单位后作为有效指标

**定位**：`src/healthzip/normalize/__init__.py:122–124`；消费点 `src/healthzip/science/state.py:82–89`、`src/healthzip/science/energy.py:102–110`。

**场景**：用真实XML ZIP导入同一完整日的basal 6694.4 kJ、active 2510.4 kJ，以及一条SDNN=0.05 s。这是一份采用可换算单位的合成Apple格式ZIP，未声称所有Apple原生导出都会使用kJ或秒。转换关系确定；即使某单位暂不支持，也不能把原值重标为目标单位后当成有效数值。

**Actual**：导入completed、errors=0。数据库把原值6694.4/2510.4保存为normalized_unit=kcal；0.05保存为normalized_unit=ms，三条仅unit_status标unit_unverified。默认analyze不检查该状态，输出总能量9204.8 kcal、日均9204.8 kcal/day及SDNN 0.05 ms，均valid且exclusions为空。

**Expected**：支持的能量单位应精确转换为2200 kcal；SDNN应为50 ms。若尚不支持转换，保留原单位并返回不可比较/不充分，不得重标目标单位并参与计算。

**影响**：数值可被放大4.184倍或缩小1000倍，污染状态基线、趋势、能量报告和后续解释。修复R11的外层单位并不能修复原始单位归一化错误。

**验收**：真实ZIP中kJ/kcal等价输入应给相同能量；s/ms等价SDNN应相同；任意未知单位保持unknown并不进入数值聚合；同时核对unit_status与MetricResult缺失/排除信息。

## 新发现 2 — [P2] 仅提供inBed的手机来源阻断唯一真实睡眠来源

**定位**：`src/healthzip/science/state.py:44–53`；默认路径 `analytics.v13.analyze` 未指定primary_sleep_stream。

**场景**：过去24小时内导入两个正常SleepAnalysis记录：iPhone提供8小时inBed，Watch提供其中7小时asleep。没有两个相互竞争的asleep来源。

**Actual**：STATE-SLEEP-24H.value=null、incompatible，原因multiple_sleep_streams_primary_source_required。相同analyze结果的REPORT-STATE-SUMMARY正确得到Watch已观察睡眠420分钟。

**Expected**：对睡眠时长先限定相关asleep记录，再判断候选来源；仅inBed不参与睡眠时长，也不应制造asleep来源冲突。返回Watch观察到的420分钟并保留完整性未知，或按来源直接展示该已观察值。

**影响**：完整Apple Health ZIP同时含手机inBed与手表分期时，原本存在的睡眠信息在24小时卡片被标成不可用；外层图表却有相同睡眠量，界面互相矛盾。这里不要求猜测主睡眠或完整恢复，只要求不让不计入指标的记录阻断唯一相关来源。

**验收**：给单一Watch asleep数据追加任意iPhone inBed，应不改变asleep分钟数和相关来源可用性；真正两个asleep来源仍应分流/要求主来源，不能相加。

## 新发现 3 — [P2] 午夜半开窗口的睡眠覆盖率可使全部分析崩溃

**定位**：`src/healthzip/science/state.py:128–134`（分子取区间结束日期）；分母由同文件67–74行按半开日期域计算；最终触发 `science/contracts.py:204–205`。

**场景**：显式一天窗口 `[D 00:00,D+1 00:00)`，同来源睡眠记录为D日01:00–06:00及23:00–次日00:00。截止时间恰好为窗口结束午夜。脚本使用未来合成cutoff保证刚导入记录在cutoff之前已可见；这只是生成可复现as-of测试的手段，日期域错误与当前实际日期无关。

**Actual**：两个结束日期被计为2，elapsed_dates为1，result验证抛`ValueError: invalid_denominator`。异常从evaluate_all传播，整个`analyze()`失败，未能返回其他正常指标。

**Expected**：分子与分母遵循同一半开当地日期域；结束恰在排除边界的片段不可再贡献窗口外日期。指标应返回有界覆盖率/充分性说明，不能使整个分析终止。

**验收**：覆盖UTC及非UTC午夜，窗口边界精确相等、±1微秒、DST切换和跨午夜片段；保证`0 <= valid_dates <= elapsed_dates`且`analyze/evaluate_all`不因合法边界记录抛异常。

## 复现材料

`reproduce.py` 经 `import_apple_zip → Repository → analyze` 运行以上3项；`results.json` 包含原始存储字段、MetricResult及完整异常栈。运行：

`PYTHONPATH=src /workspace/scratch/a74a838d7f65/apple_review_0a943b4/.venv/bin/python /workspace/scratch/a74a838d7f65/review912/state/reproduce.py`

补充检查：Record子元素MetadataEntry当前存储结果确为metadata_json={}、source_record_id=null，脚本也保存了探针，但尚未把此项独立列为本轮高影响数值缺陷。全历史规模问题由主代理独立测量，避免重复。没有将缺少真人校准、未知初始平衡或缺失主睡眠声明本身计为bug。
