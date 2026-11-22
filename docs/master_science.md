# 本轮科学方法、数据接通与验收

本说明对应 `HealthZIP_Codex_Master_Redesign_Prompt_20261122.md`，以本轮代码和合成验收回执为准。数据均为合成数据；软件正确性、资料核查、模拟校准、真实人体效度是不同状态。这里没有将前两者升级为疾病判断、个人干预有效性或因果结论。

## 实现身份与正常入口

`analytics/body_metrics.py` 的 `analyze_body_metric` 是身体详情的正常入口，算法身份为 `typed-body-facts-1.2`；`analytics/body_questions.py` 的 `body-questions-1.3` 接通 W1–W8 和 E。继续使用 Repository、`source_revision`、`MetricResult`、现有训练事件和缓存。不存在第二套健康数据库。

事实身份包括工作区、字段/问题、所选实际起止/截止、前期、前置参考、时区、来源筛选、修订依赖、算法版本和可选变化证据。原始记录 ID、来源、设备、版本、协议/情境、原始时间与偏移、样本数、观察日数、排除原因继续保留。页面只对日期完整的日作默认期间比较；日期完整不代表全天佩戴或完整测量。

`artifacts/master_redesign/science/field-census.json` 从真实流式 ZIP 导入 761 条合成记录，761 条写入、0 导入错误，逐项调用正常 MetricResult 入口，覆盖本轮 57 个指标身份。`question-census.json` 逐一调用正常问题入口。训练组另走已存在的 TrainingService 和组序比较合同，不计入这 57 个健康字段。

## 观察单位与统计目标

| 类型 | 实际计算 | 边界 |
|---|---|---|
| 日 RHR、SDNN、体重及其他日型值 | 同来源/设备/协议日代表值；期间对有记录日等权取中位数、四分位数，保留样本数和原始值 | 不把期间中位数写成 mean；SDNN 不接受 RMSSD 身份；不补零、不均衡删样本 |
| 普通/运动 HR、呼吸、SpO₂、步态等样本 | 原始观测点和记录日分布；运动 HR 限实际 Workout 区间，稀疏夜间样本与睡眠事件关联 | 不是全天/整场时间加权均值，也不能从稀疏 SpO₂ 重建整夜低氧 |
| 睡眠 | 同来源连续注释形成观察事件，asleep 区间并集减去明确 awake，UTC 求实际时长，按结束本地日归属 | 不跨来源拼一夜、不把卧床当睡眠、不用短时长自动判午睡；记录结束不是已证实醒来 |
| 睡眠分期 | 分期冲突留未知；总时长、已分期分钟、未知分钟及已知分期内比例分别保留 | 未分期不是零深睡；分母明确 |
| 活动、距离、时长、能量、跌倒计数 | 同来源同表示的非重叠增量求和；明确同起点累计快照取最后值；期间总量和典型记录日分开 | 混合累计/增量、无法解开的重叠不猜测分配；负数计数不接受；高值不凭人为医学线删除 |
| 低频估计 | 保留每个真实发布点、支持窗口、方法、版本、重叠/重复发布、校准和已知上限 | 不插值造日值、不强套日趋势、不把共享支持窗口当独立测试 |
| 站立 | 类别小时只计实际 stood 的唯一小时；站立分钟单列；ActivitySummary 的站立小时为独立日期摘要 | 达标小时不是连续站立时长，也不能从中反推坐姿时长 |
| 环境/耳机声级 | 对同口径不重叠区间计算 `10 log10(Σ duration × 10^(dBA/10) / Σ duration)` | 两种暴露独立；不算普通 dB 平均，不把缺测当安静 |
| 饮食/水/咖啡因 | 已记录份量和时点；旧 nutrition_day 的 complete/partial/unknown 状态保留 | 一餐不推全天；没有日志不推零摄入或能量缺口 |
| 周期、症状和通知 | 展示实际日志/通知类别、来源、事件日期；允许单次事实 | 不补周期相位，无通知不排除风险；跌倒 count 是记录数量，非通知数量或严重度 |

前期周/月按相同已过日历长度比较。28 日前置参考、7 日展示、6 小时时段分组、训练前后 24 小时配对窗口均为明确产品选择，不是普适科学门槛。用户选择的来源继续生效；条件未知保留未知。采样组成敏感性提供“全部已记录日”与“两期共同有记录的星期”的差值，说明范围收窄，不能证明漏记随机。

问题文案中的训练、运动和通知日期先转成分析时区；原始事实时间保持原值。跨午夜的睡眠保持完整事件；23:50 与 00:10 的时点用圆周统计。跨日累计区间和声级不能凭总量推出各日分配，保留原始区间和排除理由；结束恰在午夜的单日累计记录归属刚结束的一日，并保留原始终点。

## 替代导出结构、时态与回补

`db/observation_ledger.py` 为 WorkoutStatistics、WorkoutEvent、ActivitySummary、nutrition_day、cycle_event 添加同一 `source_revision` 账本；Repository 追加迁移修订号为 **5**。旧行从迁移时起可见并标为 `observed_at_migration_historical_visibility_unknown`，不伪造早年的可见时间。新增、修改和物理删除追加快照/墓碑，查询先决定截至时点的最新修订，再按类型/日期筛选。已有冻结结果内容不重写。

`analytics/alternate_observations.py` 在正常单项和问题入口使用这些结构：

- Health sample、Workout statistic、ActivitySummary 分为不同表示流；各有自己的值、覆盖和协议，不跨流求一个重复累计的总数。
- Workout 中相同整场统计只使用一份；整场摘要存在时不再加入其子区间。Workout 距离头只在相应类型的距离统计缺失时使用。普通 `totalEnergyBurned` 不能擅自重新定义为活动能量；已有 Workout 清单保留其“Workout 总能量字段”身份。
- ActivitySummary 和 nutrition_day 是日期快照，取同来源/日期最新可见发布，保留完整性状态。删除最新快照不会重新激活同记录的旧版本。日期只有日精度，索引时间锚点不作为真实测量时刻。
- ActivitySummary 原始字段/单位保存于 metadata；旧数据缺单位时保持不可比较。再次提供相同原 ZIP，可只回补缺失 ActivitySummary/Workout 元数据或新支持 Record 类型；第三次导入幂等返回 already_imported。不会搜索或伪造已不存在的原文件。
- cycle_event 与同指纹 health_sample 不重复计数；独立旧周期日志可用。饮食摘要仍然不是强制饮食记账平台。

迁移为追加结构和触发器，不删除用户数据。旧版本程序会拒绝更新后的迁移修订号；回滚应恢复升级前备份的数据库和对应程序，不能仅将修订号手改回旧值。无原 ZIP 时，缺失的旧字段、原始时间或单位无法凭空恢复。

## 趋势模型与诊断

实现为 `science/calendar_trend.py`，`calendar-gap-ar1-reml-profile-1.1`。只有连续日/夜型量才进入候选；原始点始终保留。

模型从 `y = α + β × 实际经过天数 + e` 开始；可预设唯一因素 `sleep_hours`，但不全字段扫相关或选最大关联。整数日历间隔 Δ 使用 `ρ^Δ` 以及对应创新方差 `1−ρ^(2Δ)`，缺日不压成连续日。估计搜索正负 ρ，使用受限似然和对 ρ 不确定性的剖面区间；输出每日斜率单位、期间估计变化、系数区间、适用日期、残差诊断和模型条件均值。条件均值与页面描述性中位数分别显示。

工程诊断包括：至少 `2k+4` 个日期（k 为参数数）、存在相邻日以辨认一日相关、无重复日期、有限数值、可识别设计矩阵；预设因素在前后时段有共同水平、睡眠变幅不低于输入的一分钟分辨率；相关参数不在边界。还检查明显曲率/中段阶段差、残差波动随时间变化、白化创新次序残留相关、杠杆和单个创新影响。条件数 100、相关边界 0.975、残差诊断显著性/影响度界限是工程回退规则，不是临床阈值，也不是“满多少条就可以分析”。

估计不稳、近常量因素、共同趋势但无条件重叠、非线性或稀疏记录局部回退到实际观察/幅度/覆盖，不隐藏其他指标。不对不规则力量组、低频 VO₂max/6MWD、计数、比例或等级强套此线性模型。

方法背景见附件 M4/M5/M6、J1/J2/J3；资料取得与逐用途审阅以 [master_knowledge.md](master_knowledge.md) 和 `artifacts/master_redesign/knowledge/reviewed-uses.json` 为准。开放教材或纵向方法原则支持建模结构，不授予本实现真实世界预测或诊断效度。

声学计算由能量对数定义与时长积分导出；本轮合法取得并核读 NIOSH 98-126 印刷 pp.26、29–30，来源用途为 `MASTER-NOISE-ENERGY`，不将职业噪声风险限值套用于全部个人设备。详见知识库的原文/hash/用途回执。

## 睡眠规律性、联合问题与三种变化

SRI 明确区分测得 asleep、测得 awake、未知和冲突。相隔真实 24 小时的已测状态对贡献有效配对分钟；报告可配对总分钟、小时覆盖和未配对范围。完整 SRI 只在整个所选配对范围均可判定且两种状态均出现时报告；仅睡眠片段不会把其他时段补成清醒。部分有效状态对的条件统计另外标识。只有夜间片段时，时长和圆周时点仍可查看。S2 的测量定义和记录长度讨论不等于本产品获得了医疗睡眠分类效度。

W1/W2 使用实际动作、器械、侧别、负荷口径和组位匹配，保留休息与 RIR；RIR 缺失不挡实际重量×次数展示。W3 新增同来源/设备/运动类型/记录距离的真实两场用时与对应心率样本对照，已知路线/协议分组；努力或路线未知不能声称同负荷进步。W5 同时展示实际外部负荷、次数、此前同日体重和比值，体重下降造成的比值变化不当独立力量进步。W7 对共同日期的活动量与步速分别陈述。W8 保留实际周期/症状事件与相邻训练的完整组记录，再按真实动作分别对照相邻重复事件对应的组位、负荷、次数、RIR及休息。不同动作的交错场次不会阻断同动作对照；同一单次事件连到两场训练不能冒充重复事件。条件未知仍展示实际重量和次数，不计算可比差值，不补相位。W3/W7 的联合页面继续保留每次低频发布点、支持窗口、重复发布/窗口重叠及已知版本上限；相同500m不能被升级为能力停滞。

E 从正常入口读取实际主观症状（包含文字、部位与动作影响）及训练，不再仅列设备通知。通知/症状有时刻时，显式关联训练开始前后24小时或区间相交；只有日期的日志仅连同一本地日期，日内先后仍未知。保存原始事件起止、训练起止、实际组和来源ID，设备事件与本人日志保持不同身份。所选窗口外、截止前的相邻训练可作为事件支持；没有匹配不代表没有训练。

W4 读取截止时点可见的目标修订、已选行动和最新执行反馈。行动基线保持原冻结JSON；后续观察起点为行动选择时刻、长度沿用冻结基线时长，并截于当前结束/截止。按冻结来源、时区、设备/协议/版本/单位与动作条件匹配实际后续记录；旧基线缺记录身份或动作条件未知时说明不能自动匹配。目标方向不等于独立数值目标，执行状态来自本人反馈，实际差值不写成行动因果效果。显式目标/行动签名和所有冻结指标依赖进入缓存键，反馈或目标变更可及时更新；晚于历史截止的反馈/目标不会改写历史结果。实现不递归调用行动followup。

W6 预设问题为“睡眠时长与随后同条件 SDNN 的条件关联”。先核对睡眠结束早于测量，同条件设备/协议、时段和睡眠来源分组，再估计同时控制实际时间趋势的系数；展示所有组和局部回退，不挑最大的关联。源输入重叠、作息和训练的共同影响仍可能存在，所以不写因果比例。

训练→随后睡眠和睡眠→随后训练分别配对，不把同日邻近当作方向。训练范围之外、截止前已经可见的支持睡眠可进入独立配对；查询前看 24 小时、后看最多 48 小时用于取完整已观察事件，匹配规则仍是相应方向 24 小时。没有结束时间/没有方向匹配分别说明原因。

三种变化分开：个人参考四分位数是生活记录的分布；匹配设备/协议的重复测量误差证据才产生“超过重复性界限”；独立预设目标尺度才产生“达到目标幅度”。`change_evidence` 必须匹配当前流的 `comparison_identity`、单位、来源、正阈值和证据 basis。任一缺失，那个判断保持未知，已有绝对差仍可显示。正常入口和缓存已验证该路径，不能把生活记录 SD 自动换算 MDC，也不能把超过误差等同临床重要。

## 模拟结果

`tools/master_science_acceptance.py` 先生成完整 120 日平稳高斯 AR(1) 过程，再独立随机移除观测；每场景 200 次。`simulation.json` 为 seed 74031；`simulation-independent.json` 为调整完成后的独立 seed 192047。两份是两个随机种子，不能相加当作真实参与者。

下表为独立种子结果，覆盖率分母是通过工程诊断的模型；误报率分母是全部 200 次零效应试验。回退数量、RMSE、区间宽度和估计相关参数都保存在 JSON。

| 真值（每日趋势；因素系数） | 日误差ρ | 随机缺日 | 成功/200 | 接受模型系数偏差 | 95%区间覆盖率 | 零效应全试验误报率 |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0% | 199 | −0.000017 | 96.98% | 3.0% |
| 0.03 | 0 | 0% | 198 | +0.000174 | 93.94% | — |
| 0 | 0.65 | 0% | 198 | +0.000492 | 94.95% | 5.0% |
| 0.03 | 0.65 | 0% | 199 | −0.000664 | 94.97% | — |
| 0 | 0.65 | 30% | 200 | +0.000048 | 95.00% | 5.0% |
| 0.03 | 0.65 | 30% | 199 | −0.000248 | 95.48% | — |
| 0 | −0.4 | 30% | 199 | +0.000007 | 95.98% | 4.0% |
| 0.02；睡眠因素2.5 | 0.6 | 30% | 199 | 因素−0.008891 | 97.49% | — |

每场景仅 200 次，约 95% 覆盖率的蒙特卡洛标准误约 1.5 个百分点。结果只覆盖所列线性、平稳、高斯、独立缺日和有条件重叠的合成设计；非随机漏记、非平稳生理过程、设备误差、真实个体重要变化与干预效应尚未得到该模拟验证。原始发展种子的覆盖结果不能取代独立种子或扩大到未模拟场景。

## D01–D25 验收映射

| 编号 | 本轮实现/证据 | 结论边界 |
|---|---|---|
| D01 | `test_health_fact_comparisons`：RHR 64 对 59，差 +5，真实覆盖和前置参考 | 不是固定值或疾病阈值 |
| D02 | 同文件 sparse periods，2 天与20天完整保留；weekday sensitivity | 没有均衡删样本或假设随机缺失 |
| D03 | 同文件 dense SDNN day：20条与1条，日代表值等权 | 保留21条来源与各日n |
| D04 | `test_state_energy_prediction`、`test_health_fact_comparisons`：普通HR/SDNN/RMSSD身份 | 不由普通HR推造RHR |
| D05 | 同文件 protocol/context/device分组；新旧设备不同流 | 不因主动测量增多宣称恢复改善 |
| D06 | DST实际时长、午夜边界、`test_master_science`圆周时点、`test_alternate_observations`午夜累计 | 真实工作/轮班类别只有明确记录才可分组 |
| D07 | 父子/awake/分期冲突/多来源测试，分期未知仍有总量 | 不拼完整夜，不把未知分期算零 |
| D08 | `test_master_science` SRI实际测得状态与未知配对范围 | 只有睡眠片段不报完整SRI |
| D09 | `test_alternate_observations`：50样本、50整场、500活动环为3个独立流，重复整场/子区间不再加；历史删除 | 未合成600的重复总量；总能量字段不冒充活动能量 |
| D10 | `test_master_science`、`test_question_context`：真实2个6MWD发布点，单项及W3/W7均保留支持窗口重叠、显式Apple-2021方法500m上限 | 没有对应版本时不套28日/500m |
| D11 | 同文件：SpO₂ .97、腕温35.6℃、呼吸紊乱3，真实夜间关系 | 不是整夜低氧/核心体温/AHI |
| D12 | 同文件：步数下降、共同日期步速1.2稳定，W7同时呈现 | 活动量与能力分开 |
| D13 | 同文件：stand1小时与7分钟分开、MET3.2、70/80dBA声能平均 | 不换成RIR，不普通dB均值 |
| D14 | 既有组序/训练验收及 `training/exercise-progress.json` | 达目标停止与未见PR不自动判停滞 |
| D15 | W1/W2调用实际 `compare_work_sets`；组位/休息/RIR和具体下一步 | 休息变化作为条件，不归因肌肉损伤 |
| D16 | W6只匹配睡眠先于SDNN，W7只用共同日期，双方向训练配对 | 不倒置先后、不跨月份拼同步变化 |
| D17 | `test_master_science`近常量睡眠、时间共趋势无因素重叠局部回退 | 不制造睡眠因果效应 |
| D18 | 同文件与W5：体重下降同时展示40kg×8绝对组、负荷/体重 | 比值受分母影响 |
| D19 | 正常ZIP350kcal部分餐、旧nutrition_day partial；W8重复实际事件及同动作8→10，未知条件不算差 | 主要分析可用，不补全天能量缺口/周期相位 |
| D20 | availability声明及无导入/无可见记录/无效测试；8类实际事件/计数、E真实症状/训练先后及未来症状排除 | 已知关闭/不支持须有来源声明，无通知仍未知 |
| D21 | 既有 source_revision 类型/日期/删除/冻结测试；新增辅助表迁移、更新、删除、回补幂等测试 | 旧历史不可见时不回填过去 |
| D22 | 两随机种子的8场景模拟JSON，非线性/边界/因素回退测试 | simulation_only |
| D23 | `pages/acceptance/browser.json` 的长期正式模型、联合模型、稀疏回退；对应390/1440截图 | 真实浏览器读取计算值和图点；不是仅后端测试 |
| D24 | `test_master_science`晨练/午睡/晚练/跨夜；`test_alternate_observations`正常问题入口跨所选训练范围取先后支持事件 | 两方向和未匹配原因独立 |
| D25 | `test_master_science`三层独立；`test_alternate_observations`正常MetricResult+cache的匹配误差3、独立目标5、实际差4 | 超过误差=True、达到目标=False；无证据不升级 |

页面实际验收位于 `artifacts/master_redesign/pages/acceptance/browser.json`；该回执覆盖六宽度、两种正式模型、稀疏局部回退、行动保存/反馈、报告返回。57项字段的流式导入/事实覆盖不等同57项每项都有单独浏览器截图。训练流程和性能的本轮回执分别见 `artifacts/master_redesign/training/` 和 `artifacts/master_redesign/performance/`，不能把科学pytest耗时当产品性能。

## 实际运行与尚未验证项

本轮最终科学/导入/迁移/缓存回归命令：

```bash
.venv/bin/python -m pytest tests/science tests/integration/test_import_and_analysis.py tests/integration/test_csv_import.py tests/integration/test_v13_repository_gate.py tests/integration/test_v14_science_import.py tests/integration/test_repository_open_concurrency.py tests/integration/test_health_change_cache.py tests/integration/test_master_report_performance_contract.py tests/integration/test_master_actions_profile.py -q --disable-warnings --maxfail=3 --junitxml=artifacts/master_redesign/science/finish-tests.xml
.venv/bin/python -m tools.master_science_acceptance --census-only
PYTHONPATH=src:. python -m tools.master_science_acceptance --replicates 200
PYTHONPATH=src:. python -m tools.master_science_acceptance --replicates 200 --seed 192047 --simulation-only
```

科学范围 Ruff 使用 `.venv/bin/ruff check` 对本轮 science、body analytics、alternate_observations、observation_ledger、normalization/importer、Repository/temporal 和对应测试执行；结果为通过。本次广域回归为 **571 passed / 0 failures / 0 errors**，pytest墙钟输出27.30秒；最终数量以同目录 `finish-tests.xml` 为准，重复运行不累加。新增 `test_question_context.py` 通过正常服务验证E症状与真实训练先后、W8交错场次中的完整/未知条件、低频支持身份、W4空库/可见目标/冻结时区与来源/实际反馈/历史截止/动态指标缓存依赖；目标和反馈测试未调用递归followup。独立模拟先以完整入口运行生成字段清单后将seed192047回执保存为 `simulation-independent.json`；上列带 `--simulation-only` 的命令可复现同一模拟。

明确未验证：真实不同Watch/iPhone/地区/系统版本是否均产生这些字段；真实人体纵向模型效度；任一设备的个人重复测量误差、重要变化尺度、预测效度或干预因果效应；非随机缺失下的趋势区间校准；未获原文的受限章节及未逐主张审阅的内容（以知识库交付清单为准）；缺原文件时的历史字段回补。上述限制不关闭已有事实、描述、已通过诊断的条件模型和实际行动复评。

## 逐项字段目录

下表来自本轮实际 field-census；每项均有真实导入记录且进入正常事实入口，单位、统计类型、对应问题及限制由 `body_catalog.py` 定义。逐项“可生成/可导出/可解析/可计算/可解释/可展示”状态详见同一 JSON；导入合成Record证明解析和事实路径，不证明全部真实设备支持。

| 指标身份 | 名称 | 单位 | 观察类型 | 问题 | 有效记录 |
|---|---|---|---|---|---:|
| `heart_rate_bpm` | 普通心率 | count/min | samples | W3 | 36 |
| `workout_heart_rate_bpm` | 运动心率 | count/min | samples | W3 | 1 |
| `resting_heart_rate_bpm` | 日静息心率 | count/min | daily | W3 | 153 |
| `hrv_sdnn_ms` | 心率变异性 SDNN | ms | daily | W3 | 172 |
| `walking_heart_rate_bpm` | 步行平均心率 | count/min | daily | W3 | 1 |
| `heart_rate_recovery_1m` | 一分钟心率恢复 | count | estimate | W3 | 1 |
| `vo2_max_ml_kg_min` | 来源报告 VO₂max | mL/(kg·min) | estimate | W3 | 1 |
| `sleep_stage` | 睡眠事件、时长与分期 | min | sleep | W6 | 221 |
| `respiratory_rate_bpm` | 呼吸率 | count/min | samples | W6 | 1 |
| `oxygen_saturation_fraction` | 血氧饱和度 | fraction | samples | W6 | 1 |
| `sleeping_wrist_temperature_c` | 睡眠腕温 | degC | daily | W6 | 1 |
| `sleep_breathing_disturbances` | 睡眠呼吸紊乱 | count/hr | estimate | W6 | 1 |
| `steps` | 步数 | count | sum | W7 | 118 |
| `distance_walking_running_m` | 步行和跑步距离 | m | sum | W7 | 1 |
| `distance_cycling_m` | 骑行距离 | m | sum | W7 | 1 |
| `exercise_minutes` | 运动分钟 | min | sum | W7 | 1 |
| `stand_hour` | 站立小时 | h | stand | W7 | 1 |
| `stand_minutes` | 站立分钟 | min | sum | W7 | 1 |
| `flights_climbed` | 爬楼层数 | count | sum | W7 | 1 |
| `physical_effort_met` | 活动强度 MET | MET | samples | W7 | 1 |
| `six_minute_walk_m` | 六分钟步行距离 | m | estimate | W7 | 2 |
| `stair_ascent_m_s` | 上楼速度 | m/s | samples | W7 | 1 |
| `stair_descent_m_s` | 下楼速度 | m/s | samples | W7 | 1 |
| `walking_speed_m_s` | 步行速度 | m/s | samples | W7 | 118 |
| `walking_step_length_m` | 步长 | m | samples | W7 | 1 |
| `walking_double_support_fraction` | 双支撑时间比例 | fraction | samples | W7 | 1 |
| `walking_asymmetry_fraction` | 步态不对称比例 | fraction | samples | W7 | 1 |
| `walking_steadiness_fraction` | 步行稳定性 | fraction | estimate | W7 | 1 |
| `body_mass_kg` | 体重 | kg | daily | W5 | 118 |
| `height_cm` | 身高 | cm | samples | W5 | 1 |
| `body_fat_fraction` | 体脂比例 | fraction | samples | W5 | 1 |
| `lean_body_mass_kg` | 瘦体重 | kg | samples | W5 | 1 |
| `active_energy_kcal` | 活动能量 | kcal | sum | W5 | 1 |
| `basal_energy_kcal` | 静息能量 | kcal | sum | W5 | 1 |
| `dietary_energy_kcal` | 已记录饮食能量 | kcal | intake | W5 | 1 |
| `dietary_protein_g` | 已记录蛋白质 | g | intake | W5 | 1 |
| `dietary_carbohydrates_g` | 已记录碳水化合物 | g | intake | W5 | 1 |
| `dietary_fat_g` | 已记录脂肪 | g | intake | W5 | 1 |
| `dietary_water_ml` | 已记录饮水 | mL | intake | W5 | 1 |
| `dietary_caffeine_mg` | 已记录咖啡因 | mg | intake | W5 | 1 |
| `daylight_minutes` | 日照时长 | min | sum | W6 | 1 |
| `environmental_audio_dba` | 环境声音暴露 | dBASPL | sound | W6 | 2 |
| `headphone_audio_dba` | 耳机声音暴露 | dBASPL | sound | W6 | 1 |
| `menstrual_flow` | 经期流量日志 | 次 | event | W8 | 1 |
| `intermenstrual_bleeding` | 经间出血记录 | 次 | event | W8 | 1 |
| `cervical_mucus_quality` | 宫颈黏液记录 | 次 | event | W8 | 1 |
| `ovulation_test_result` | 排卵测试记录 | 次 | event | W8 | 1 |
| `menstrual_cramps` | 经期腹痛日志（既有来源字段） | 次 | event | W8 | 1 |
| `abdominal_cramps` | 腹痛或腹部痉挛日志 | 次 | event | W8 | 1 |
| `number_of_times_fallen` | 已记录跌倒次数 | count | sum | E | 1 |
| `sleep_apnea_event` | 睡眠呼吸暂停通知 | 次 | event | E | 1 |
| `high_hr_event` | 高心率通知 | 次 | event | E | 1 |
| `low_hr_event` | 低心率通知 | 次 | event | E | 1 |
| `irregular_rhythm_event` | 心律不齐通知 | 次 | event | E | 1 |
| `walking_steadiness_event` | 步行稳定性通知 | 次 | event | E | 1 |
| `environmental_audio_event` | 环境声音通知 | 次 | event | E | 1 |
| `headphone_audio_event` | 耳机声音通知 | 次 | event | E | 1 |
