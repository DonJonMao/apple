# v1.3 科学计算、验证与限制

> 计算语义在 1.3.1 审查修复中更新，逐项证据见 [review_science_repairs.md](review_science_repairs.md)：结构化测量协议和每动作任务、登记后才展示的趋势区间、以 kcal 标记的窗口能量累计、明确主睡眠片段及独立历史睡眠序列。旧 `artifacts/science/` 和 `artifacts/demo/` 保留为初版历史证据；新版复验在 `artifacts/review/`。

本模块实现执行包中的全部 77 项指标入口。数据可计算、软件测试通过、来源取得、理论审核和人体有效性是不同状态。下文的合成验收与校准不能赋予 `predictive_validated_for_scope` 或 `intervention_validated_for_scope` 身份。

逐项映射见 [science_traceability.json](science_traceability.json)，规范见 [执行包](../specs/v1.3/Codex_Execution_Pack_v1.3/README.md)。实际来源及 TheoryCard 审核状态由 [知识模块](knowledge_v1.3.md) 单独记录。

## 入口与返回合同

```python
from healthzip.science import evaluate, evaluate_all

metric = evaluate(
    "STR-03", records,
    cutoff_time="2026-11-11T12:00:00+00:00",
    window_start="2026-11-01T00:00:00+08:00",
    window_end="2026-12-01T00:00:00+08:00",
    context={"timezone": "Asia/Shanghai"},
)
```

`evaluate_all` 使用相同参数并返回以 metric_id 为键的 77 项结果。真实应用通过 `healthzip.analytics.v13.snapshot/analyze` 读取现有 Repository 与 TrainingService；UI、Markdown 和模型解释消费同一返回合同，不重新创造指标数值。

每项 `MetricResult` 至少含算法版本、计算时间、决策截止时间、半开窗口 `[start,end)`、数值与单位、数据状态、证据身份、有效/总计数、计数域、场次、覆盖定义、区间身份、假设、原因、来源记录 ID、文献引用 ID、参数与校准产物 ID。NaN/Infinity、倒置区间、错误分母及假定场景附带概率覆盖率均被拒绝。`valid` 只描述数据，不代表科学验证通过。

所有时间必须带时区。事件结束时间与 `available_at` 同时不晚于截止时间；晚到记录不会出现在历史决策中。未知可见时间默认排除，明确 `retrospective=True` 时才可描述，并附 `retrospective_snapshot_not_prospective`。同一逻辑记录先按截止时已知修订解决，再排除删除和冲突，避免旧版本复活；跨时区修订按 UTC 时刻排序。

普通观察按事件时间落入窗口；睡眠和能量按区间相交筛选。`STATE-SLEEP-24H` 的实际窗口始终为 `[cutoff−24h, cutoff)`，与页面展示范围无关。窗口内有未解决冲突时显式显示冲突。排除的理由及原始/可用输入数保留。

## 数据与 context

`science.semantics.flatten_record` 适配真实训练记录、condition/actual JSON 和旧字段。完成状态使用 `completion_state`，不能把传输成功的 `status=saved` 当作训练完成。负荷和物理条件直接复用 `training.semantics`，没有另一份独立的物理定义。

以下是可选上下文的主要用途。缺少推断所需输入会输出未知/不足，不填默认生理参数。

| 上下文 | 用途与边界 |
|---|---|
| `timezone`、`retrospective` | 本地日期及可见时间规则；不把回顾描述称为前瞻预测 |
| `plan_snapshot` | 每场开始冻结的计划槽；额外组不能改写原分母 |
| `reference_set_ids`、`reference_protocol_declared_at` | 参考组必须在观察前指定；实际训练服务保存逐组声明时间；同场多重矛盾指定不挑最好的一组 |
| `comparison_pair` | 显式可比对；仍接受截止时间筛选与物理条件核对 |
| `muscle_mappings` | 已审核且有版本的直接/间接肌群映射；两者分别计数 |
| `formula_id`、`formula_domain` | 冻结公式及次数/RIR/研究范围；没有声明适用域则不计算 |
| `repeat_pairs`、`repeat_design` | 已声明重复测量设计；不能用任意波动估个人测量误差 |
| `practical_equivalence`、`measurement_sd`、`look_allocation`、`calibration`、`scope` | 实用等效范围、独立误差依据、共享重复查看预算及匹配校准范围 |
| `progression_plan`、`reviewed_principles`、`allowed_trial_actions` | 明确计划、器械档位及已审核的具体数值候选能力；通用解释审核不授权数值建议 |
| `main_sleep_episode`、`primary_sleep_stream`、`sleep_episodes` | 用户/上游明确主睡眠边界、来源及跨时区片段；不能据此猜测未记录睡眠 |
| `baseline_daily`、`baseline_window`、`current_observation` | 基线与当前观察分离；必须同来源/协议，当前日不混入默认先前日基线 |
| `sessions` | 整场 RPE、采集时间、时长协议及暂停区间；组 RPE 不能替代整场 RPE |
| `mass_series`、`equilibrium_baseline`、`energy_parameters`、各 covariance | 条件化能量研究输入；权重与基线的协方差显式保留 |
| `composition_model`、`intake_baseline`、`energy_scenario` | 储能组成或独立摄入基线/场景；没有可识别约束不输出绝对摄入 |
| `prediction_target`、`b1_training_pairs`、`state_at_cutoff`、`previous_state` | 同条件目标、先前成对记录、训练前已可用的状态；B1 需要匹配真实校准 |
| `daily_metric_facts`、`energy_days`、`recommendation_outcomes` | 可由原始快照与服务记录生成；覆盖分母和未知反馈保留 |
| QAL 的检索、引用、主张及审核样本 | 审计已给定标签的分母与规则；这些标签必须由独立评审或明确合成夹具提供 |

`comparison_pair/mass_series/baseline_daily/b1_training_pairs/daily_metric_facts/energy_days/recommendation_outcomes` 通过同一 as-of 筛选。基线可使用独立历史窗口；当前状态必须给事件和可见时间。会话自身检查结束、可见时间及窗口。外部实验设计、来源审核标签、组成/摄入模型、睡眠片段边界不是从缺失健康记录自动推定的事实；调用者必须提供可追溯来源与协议。

## 计算语义

### 力量

负荷口径包含外部总重、每侧片重、每只哑铃、哑铃合计、单器械、机器刻度、自重、附加负荷、助力和弹力带。未知口径不自动匹配。每侧 30→32.5 kg 且双侧对称时，两侧片重增加 5 kg；有效杆重未知时总负荷及总负荷变化百分比未知。每只哑铃需要显式器械数量才能报告质量合计，不能当作等价杠铃任务。减少助力意味着任务更难。时长、距离和次数保持原测量身份。

工作组/热身/失败尝试和递减段分别计数。`kg×reps` 是按条件分组的记账值，不是机械功、训练刺激或增肌量。参考组在每场提前指定；同负荷次数、同次数负荷与同工作量 RIR 分别比较，不能互相替代。计划停止不说明能力已耗尽。

| 公式 ID | 固定表达式 | 身份 |
|---|---|---|
| `epley_n3_0.0333` | `w*(1+0.0333*r)` | N3 Table 1 复现身份 |
| `epley_r_over_30` | `w*(1+r/30)` | 独立代数版本，不声称与上式完全一致 |
| `epley_rir_over_30` | `w*(1+(r+RIR)/30)` | 实验性代理，不是已测最大力量 |

三者版本均为 1。实际 1RM 单独保存。没有完整负荷、适用域、有效整数次数或所需标量 RIR 时拒绝计算；不裁剪超域次数。测试中给定的域是合成测试条件，不能复制成对所有用户适用的生理阈值。

局部趋势使用真实经过天数、NumPy SVD 最小二乘和 SciPy Student-t 区间。零残差且没有独立测量误差依据时，区间未定义。置信区间包含 0 不能证明无实质改善；候选还需要实用等效范围、足够的进阶机会、匹配真实校准和重复查看预算。

STR-25/26 只有明确计划/档位、可比参考和具备 `progression_candidate` 或 `trial_candidate` 能力的已审核来源理论才产生数值候选；否则可显示物理档位和缺项。候选不保证成功，不自动生成完整计划。反馈仅在 `execution_state=executed` 时按被冻结任务核对负荷、单位、口径、次数、RIR与动作质量。未执行、未知、部分执行均保留 `success=null`，在全部建议分母及缺失结果数中保留；已完成且字段齐全的结果单列成功率分母。采纳率不等于个人疗效。

### 状态与训练负荷

睡眠仅合并 asleep 区间，排除 inBed，跨午夜/DST按真实经过时间计算。重复来源需要选择主来源；互斥阶段重叠显式冲突。观测时长不是完整睡眠保证，记录日期覆盖不是佩戴率。RHR 不使用任意心率替代，SDNN 不转换为 RMSSD；原始 NN 重算需明确清洗协议。

同协议先形成每日代表值，跨日等权。不同设备/协议独立；当前观察与基线分开。MAD 为零时不产生无穷 z 分数；MAD、偏离和序数自评不能映射成恢复总分或减重比例。

`user_elapsed_including_rest` 使用用户明确报告的 duration_seconds；命名事件时长协议使用起止时间和暂停区间并集。整场 RPE 的采集延迟保留，组 RPE 中位数不替代 sRPE。AU 是 `sRPE×minutes` 的内部负荷代理，不能与工作组负荷拼成所谓生理真值。

### 体重与能量

体重使用同来源/协议每日代表值及真实日期 Theil–Sen 趋势。设备 basal+active 分别聚合，不再叠加 workout，不乘 TEF。部分跨界能量区间不按时间均匀摊分；同流重叠显式冲突。完整日需要同来源、无重叠、覆盖完整本地日或明确平台完整元数据，DST以 UTC 时长验证。缺记录不补零，不把有效日均值外推为完整周总量。

Hall–Chow 线性算子明确保留 `ΔEI = ρβ + ε(estimated_W_end−W0)`、非等间隔时间及联合协方差。`ρ=9100`、`ε=22` 仅在 `hall_chow_2011_replication` 命名模型内使用，属于文献模型复现，不是个人校准，也不是固定组织能量密度。组成储能需要明确组成模型；绝对摄入需要独立已知基线或标注条件化场景。场景范围没有频率学覆盖概率。没有独立约束时，摄入与设备偏差不可同时识别。

### 预测与报告

B0 是同条件、已知的历史参考。B1 使用单状态的前向增量预测，两个模型共享完全相同的目标与分割，报告成对 MAE 差、预测区间覆盖与宽度。特征要在目标训练开始前发生且可见。跨用户留出中，B1 系数只由其他用户拟合；留出用户历史只用于其 B0。模拟中的增益不支持改变睡眠、饮食或负荷的因果处方。

周/月报告从当时原始快照推导每日状态、睡眠、完整日能量、整场负荷与反馈；不用周均值再次平均。`REPORT-STATE-SUMMARY.daily_facts` 提供相同截止快照的每日数值、单位、来源/协议、原始记录 ID 和睡眠完整性身份，图表可直接消费，无需另算口径。使用本地日历边界，尚未结束的周期显示 partial，不能直接与完整前期总量比较。无自评、无睡眠和无能量保持缺失。

## 参数和校准登记

`ParameterRegistry` 使用本地 SQLite；参数 ID+版本和校准产物不可原地改值，需新版本。参数种类区分定义、单位转换、用户计划、器械约束、产品设置、统计设计、文献模型与个人估计。每项带来源、位置、范围与验证身份。

重复查看在预声明 family 下分配 `alpha_total/[k(k+1)]`，同数据哈希与同指标重复查看幂等，不重复花预算。多个动作/指标共享 family；该联合上界仍要求每次区间自身有效，不能修补自相关下错误的区间。

真实 `validated_for_scope` 登记要求真实数据、授权范围、来源链、审核人、独立留出、互不重叠的训练/验证/留出窗口、验证前预注册目标及达标结果。输出再匹配指标、模型版本和适用范围。模拟产物硬性保持 `simulation_only`，不会因测试绿色而自动提升身份。

## 可复现命令与实际结果

在仓库根目录执行：

```bash
PYTHONPATH=src python tools/demo_v13.py --output artifacts/demo
PYTHONPATH=src python -m healthzip.science evaluate artifacts/demo/metric_snapshot.json --output .local/demo-metrics.json
PYTHONPATH=src python -m healthzip.science calibrate --output artifacts/science --seed 1300 --repetitions 300
PYTHONPATH=src python -m healthzip.science forward-evaluate .local/locked-prediction-snapshot.json --output .local/forward-results.json
PYTHONPATH=src python -m pytest tests/science tests/integration/test_v13_analysis_adapter.py -q --junitxml=artifacts/science/software-tests.xml
python -m ruff check src/healthzip/science tests/science tools/demo_v13.py
```

`evaluate` 输入为上文 API 参数组成的 JSON；演示已产生可直接执行的完整输入。`forward-evaluate` 输入具有 `observations`、`feature`、`split`，split 含预注册时间、train_end、validation_end、test_end和heldout_users；合成示例构造器为 `research.prediction_fixture`。真实训练/健康数据只能在用户本机路径保存，不提交进仓库。

当前固定种子产物见 [calibration_manifest.json](../artifacts/science/calibration_manifest.json)：

| 实验 | 实际结果 | 能说明什么 |
|---|---|---|
| 真实时间 OLS，独立高斯噪声，300 次 | 标称 95% 区间经验覆盖 96.0% | 所声明生成器下的计算核对 |
| 同模型，自相关 AR(1) 噪声，300 次 | 覆盖 56.0% | 独立误差假设失效，不能发布为个人有效区间 |
| 异方差噪声，300 次 | 覆盖 89.33% | 常规同方差区间存在覆盖不足 |
| 四舍五入次数，300 次 | 覆盖 95.67% | 单一合成场景，不能推广到全部计数过程 |
| 零残差、未知独立误差，300 次 | 300/300 区间未定义 | 未把无残差当作确定停滞 |
| Hall–Chow，已知高斯联合协方差，1000 次 | ΔEI≈−499 kcal/day；解析方差 10700.2624，经验方差 10345.6586；覆盖 95.0% | 验证含同样本基线协方差的传播，未验证个人生理模型 |
| B0/B1，无增量状态信号 | 60 个时间测试对、15 个跨用户留出对；测试 ΔMAE≈−0.00789 | B1 无改善，发布仍为 B0 |
| B0/B1，合成状态信号 | 同分母；测试 ΔMAE≈+0.77933 | 指定生成器有预测关联，发布仍为 B0；不构成因果效应 |

详细宽度、逐场预测、分割、种子和模型标识见 trend/energy/prediction_simulation.json。数据哈希绑定登记产物。重新运行不会把失败覆盖场景删去。

## 软件验收与尚缺证据

[software-tests.xml](../artifacts/science/software-tests.xml) 是实际 pytest 输出；[acceptance-results.json](../artifacts/science/acceptance-results.json) 将执行包 178 条 case ID 映射到已执行测试。120 条非 QAL 夹具包含物理语义、时间泄漏、统计失败及模拟检验；58 条 QAL 夹具使用显式合成裁定标签验证审计规则。部分目录用例复用包含多条断言的回归场景。测试 ID 全部存在并通过，不等于每条文字主张已被独立专业评审。

[合成端到端演示](../artifacts/demo/README.md) 从空库建模板，经历参考组预指定、30×10、下次草稿、候选缺项、用户自主32.5×8、双侧片重+5 kg、整场反馈及周报告。它使用真实服务接口，不伪造数值理论审核身份。Streamlit控件与离线浏览器验证由整体集成测试另外覆盖。

仍需实际完成的科学工作：经过同意的纵向参考组与训练前状态数据；同任务重复测量及个体误差设计；冻结的实用等效范围；预注册的时间外和跨用户留出目标；独立能量/组成/摄入基线与协方差依据；针对每个数值能力的文献全文、适用性和专业审核；真实检索主张的独立语义裁定。缺少这些证据时保留研究身份、未知或不可识别，并禁止数值因果处方。

当前没有声称完成百万条分析性能基准、人体前瞻实验、医疗诊断验证或个人训练最优策略验证。
