# 分析核心逐项验收与操作合同

本文件对应 Prompt v2、配套 PDF 及两项验收澄清。实现起点 `a0377be`；主体交付 `d300a9a`；收尾修复采用 `analysis-workflows-1.6.1`。本文件与 [实施合同](analysis_core_design.md)、[交付说明](analysis_core_delivery.md) 共同使用。这里的“通过”是软件行为或现有资料集成的核对，不是新的专家审核、独立检索准确率或个人效果验证。

## 普通操作、补录与恢复

1. 在「力量」记录真实动作条件、原计划、参考组、实际负荷/次数/RIR、质量与停止原因；参考组事后指定保留回顾身份。健康 ZIP/CSV 从既有导入入口进入同一 Repository。
2. 在「分析→按问题分析」选择问题。W1 选择训练、动作与目标组；W4 先选择同条件训练任务或体重/RHR/SDNN 结果，再确认范围。其他流程不要求手选多个指标。
3. 「查看范围与已确认信息」可选择查看天数、时区关联设置、完整日历周/月、前瞻/回顾、适用人群，以及默认 28 日的描述基线/练前背景回看范围。W2 基线是截止日期之前已结束的本地日；当前日另列。它只限定描述，不判正常、疲劳或停滞。
4. 点击运行后，在六个页签查看事实、可比性、支持/相反观察及未知、下一步、依据、后来怎样。默认最多三个分项卡片，其余展开。图表只画实际记录点，来源/协议分组，不插值。
5. 按具体缺项去原入口补录。返回已保存分析，点击「补录后重新分析」：保留原任务、窗口设置、时区、模式、已确认上下文、选定结果和候选引用，更新截止时刻并建立 parent 关联。上方新任务控件不会静默覆盖历史请求。若明确勾选使用分析页新选择的睡眠/参考记录，服务另核对时区、截止时点及模式；不兼容会明确拒绝，不猜补。
6. 调整问题或范围后点击「运行分析」建立新的请求。历史运行及当时数值、来源、规则保留。执行候选前点击当前核对；新疼痛、记录修订、撤回或权限变化会限制当前使用。
7. 用户可采纳、修改、拒绝或不回应；选择不会自动完成训练。实际训练后记录执行情况并在结束后反馈，再生成后继运行。「后来怎样」分开显示采纳、执行、达标及后续观察，未知不移出原建议分母。

命令行复用服务：`python -m healthzip.workflows --db <合成或本人授权库路径> --workflow W2 --days 30 --baseline-days 28 --timezone Asia/Shanghai`。历史续算使用 `--resume <run_id>`；指定历史时间时必须提供含时区的 `--cutoff`。不接受客户端 MetricResult 或科学批准旗标。

schema 4→5 通过 Repository 的事务迁移追加工作流、候选幂等身份和 sRPE 采集时点；旧未知值不回填。升级前停止应用，调用 `healthzip.db.backup.backup_database(旧库路径, 新备份路径)`，其中 SQLite backup API 会包含已提交 WAL。恢复用 `restore_database(备份路径, 新目标路径)`，不覆盖运行中数据库。旧代码回退需要升级前备份。迁移/事务中断不应留下半个候选或孤立分析；本轮没有打开或迁移真实私人库。

## A1–A5 与实施阶段核对

|要求|已处理内容／边界|可复核证据|
|---|---|---|
|A1 评分身份|必需返回身份不能借 Gold 补全；缺 kind、None、类型错及定位/内容错不精确命中；1.5.1 拒绝无声重解释旧组语义，旧逐 Span 结果保留|`tests/knowledge/test_v15_evidence_group_scoring.py`|
|A2 用途边界|按具体来源版本/Span→主张→指标边/规则/发布追踪；没有以阅读相关性改生产权限|`production-dependency-trace-1.json`；下文用途表；N1/等效/冲突权限测试|
|A3 条件输入|直接 RIR 从本库 MetricResult 派生；整场 sRPE 的量表、采集时间和人群来自实际记录；工作流不接收伪造结果、临床用途或科学批准旗标|`test_v15_rir_version_scope.py`、`test_analysis_workflow_evidence.py`、`test_analysis_workflow_runs.py`|
|A4 时间/幂等|目标与条件按事件时点重放；候选创建不倒记；事务与唯一请求身份覆盖刷新、并发、修改和反馈重试|`test_analysis_advice_time.py`、`test_analysis_candidate_identity.py`；真实相同两组仍各计数|
|A5 名称|使用力量进阶、训练负荷与恢复背景、心肺观察、长期趋势与可能因素、体重与设备能量背景；内部 ID 兼容|`workflows/contracts.py::FUNCTION_NAMES`、五流程正常页面测试|
|P0|上述缺陷/依赖清单、参数用途登记；区分已复现缺陷与核对后无需修改项|实施合同、29 项参数清单|
|P1|S0–S6、不可变快照、当前使用、后继运行、事务恢复及同请求幂等|`test_analysis_workflow_runs.py`；schema 迁移与候选并发测试|
|P2|W1 两分支、不同动作/不同实际步长、真实页面选择/执行/反馈闭环|`test_analysis_w1_flow.py`；实际资料闭环回执|
|P3|W2/W4 正常事实、每条训练前背景、支持/反证/未知；历史续算保留设置，所选结果不借用别的指标|`test_analysis_long_term_review.py`、`test_analysis_scope_resume.py`|
|P4|W3 来源版本分段与未来修订排除；W5 完整日分母与不可识别性|`test_analysis_observation_flows.py`、`test_source_observations.py`|
|P5|T01–T28、77 用途分类、正常案例、方法/参数合同、整仓回归与发布|本文件及 `artifacts/analysis-core/` 的映射、验证回执；不重开独立科学研究|

资料收尾的 29 个逐任务缺项、145 个条件核对及 4 个追加关系修订已逐项读取。145 次未满足是那 29 个固定上下文中的五项主张条件，不是永久禁用；直接 RIR 与合格整场评分的正常路径均有实测。旧 1044 次比较、26 次解释检查仍保留“未执行”；四本取消教材不属于缺口。

|已知问题|精确生产依赖及处理|运行边界证据|
|---|---|---|
|N1 孤立行/拆断公式|三个既有版本的解释范围明确不激活公式/参数，无行动权限；未据此引入 HC/HAC 算法或覆盖率。现有 OLS 是独立命名的研究方法，假设与限制另列|`test_regression_covariance_contract.py::test_n1_scope_has_no_personal_model_or_candidate_authority`；方法正例仍可答；完整依赖版本/Span 见追踪 JSON|
|E8 累计差分符号冲突|当前只有测量定义引用，未绑定冲突累计差分单元；设备能量按已记录 basal+active 的定义计算，不采用冲突公式|追踪 `specific_issues`；T20/T21/T22 数值与边界测试|
|R2b 数值/组别冲突|未发现生产主张；不自行交换组别、推导数量效果或授权数值候选|追踪精确单元与零直接主张；完整组/显式指标边权限测试|
|R6 计划/感知强度|绑定 LOAD-SRPE/LOAD-SRPE-AU，未绑定采纳/随访方法；其整场测量定义正例继续可用|实际 sRPE 正反例；T26 分母测试|
|R3b HRV、Quer RHR 均值区间|R3b 当前边仅同协议测量/描述背景，不绑定 STR-22；Quer 未发现生产主张；不将均值 CI 变个人力量预测区间|追踪 JSON；SDNN/RHR 测量分离、缺校准及预测研究门禁测试|
|AWHS 正文/表格/SE|保留原问题记录和有限日志身份；工作流不调用周期观察，不引入其参数|`WORKFLOWS` 与本轮用途矩阵；原周期数据不删除|

## 新增验收组与正常案例

|验收组|具体检查位置|
|---|---|
|评分身份与旧语义保护|`test_v15_evidence_group_scoring.py`：缺字段/None/错类型、精确版本替代仅一次增益、旧逐 Span 分母、冻结语义拒绝|
|用途、残缺与冲突|上表；`test_v15_retrieval.py` 的无关主张不得借边、冲突在预算前检查、撤回不可被缓存恢复；`test_method_equivalence_contract.py` 保留有界方法解释|
|条件正反例|`test_v15_rir_version_scope.py` 直接/区间/换算/伪造 true；`test_analysis_workflow_evidence.py` 合格/错误量表/缺时点/提前时点；实际资料四例包含人群不匹配|
|局部继续|无睡眠仍有合法次数；缺个人校准仍显示描述；无行动权限仍有物理档位、记录和有界解释：W1/W2/W4 页面与方法测试|
|时间、幂等、失效|`test_analysis_advice_time.py`、`test_analysis_candidate_identity.py`、`test_analysis_workflow_runs.py`；事务失败/并发、相关修订与无关动作、撤销和历史不变|
|单位与不变量|`test_v14_science.py::test_f07_equivalent_exact_mass_units_share_series_without_losing_raw_values`；基线独立于查看窗；非力量结果不借用力量事实/权限；不补正常状态|
|隐私与输入边界|T28；工作流检索审计私人上下文/个人数值未发送；资料内容仅用于证据，不变成指令；synthetic_test 审核不授权生产环境|
|正常可用性与补录|W1 完整选择→训练→结束后反馈；W2–W5 从 Repository 写入的两条记录打开历史运行，补第三条后点击续算，验证 parent、窗口、模式、上下文、结果不丢失，旧运行不变|

五条可复现案例使用 pytest 临时合成私人库，命令如下；fixture 的批准只证明软件路径，生产权限另看实际资料回执：

- W1：`pytest tests/integration/test_analysis_w1_flow.py -q`。上斜史密斯机六次参考、8–12 原计划、实际档位 30/32.5、明确 RIR；验证未到上限不自动进阶、允许试验时能形成任务及完整反馈；另用不同动作和步长。
- W2：`pytest tests/integration/test_analysis_workflow_runs.py tests/integration/test_analysis_scope_resume.py -q`。观察睡眠片段、整场评分、独立完整日基线、MAD0 与缺当前日；有记录就呈现，不造恢复分。
- W3：`pytest tests/integration/test_analysis_observation_flows.py -k w3 -q`。真实写入 40→42 的同版本估计，后续版本/协议不同分段；服务结果进入正常页面。
- W4：`pytest tests/integration/test_analysis_long_term_review.py tests/integration/test_analysis_scope_resume.py -q`。联合负荷/次数/RIR，无改善触发每条训练前因素复核，候选反馈进入周/月；非力量结果只比较所选指标；完整周期与当前部分分列。
- W5：`pytest tests/integration/test_analysis_observation_flows.py -k w5 -q`。七日中四个完整设备能量日，各 1500+500 kcal，均值 2000、覆盖 4/7；已有 workout 不重复相加，体重 80→79 不推断热量缺口。

## 科学与方法合同

|方法/目标|输入、单位、协议与假设|依据/输出身份|不能支持、缺失行为|
|---|---|---|---|
|记录及负荷分量|UUID/修订/事件时间/可见时间；kg/lb、单边/总重/助力方向；相同动作/器械/ROM/侧别/参考协议|单位定义、实际器械和 MetricResult；确定性描述|杆重未知不算总阻力百分比；吨位不当肌肥大刺激|
|描述性未改善|预选周期，起点为首条可见、预指定可比参考；分别比较规范化负荷、次数、直接或区间 RIR；取舍不排序|`joint-record-review-1.6.1` 的记录谓词；支持/反证/未知各列|不称生理/统计停滞；不加固定次数/天数阈值；缺校准不阻断复核和独立行动|
|OLS 与等效/预测|实际时间、同任务参考，线性均值与独立同方差正态误差；单次区间需真实误差与匹配校准，重复查看需预声明家族|`ols_true_time_student_t_v1` 是既有研究方法；N1 的解释范围不授权其个人覆盖率|均值趋势 CI≠未来个体预测区间；宽区间含0≠等效；B1 模拟优势仍 research_only|
|RHR/SDNN 描述基线|每来源/设备/协议/版本分别按本地日代表值；W2 预选此前完整日；日等权，当前日排除；1.4826×MAD 是尺度定义|实际 n、日期、参考窗口、原记录引用；描述身份，协议非空不等于专业验证|RHR≠SDNN、SDNN≠RMSSD；MAD0或缺当前值z未知；不授恢复标签/重量建议|
|训练前因素|每条参考训练开始前的睡眠/RHR/SDNN/体重及适用自评；明确前瞻/回顾的可见时间|记录事实由计算产生；来源解释仅用适用完整主张及原文定位，支持/削弱/未知不投票|时序≠因果；旧观测沿用不是训练开始即时状态；睡眠片段≠实际总睡眠|
|整场 sRPE|实际整场量表、结束后采集时点、协议时长（分钟）、人群；不同量表/计时协议不合并|评分×分钟的内部负荷代理；Foster 解释须实际条件匹配|不以组评分/日疲劳补整场；Borg 保留记录但不计算 CR10 AU；AU≠生理剂量|
|行动候选|冻结用户目标/策略、真实档位、当前状态、可比参考与有效行动规则；次数/RIR来自计划或明确用户目标|ApplicationRule→Claim→SourceVersion/Span；个人记录/重量/次数/RIR来源分列|下一档不等于适宜；不能用解释权限替代数值规则；任务完成不保证个人最优或干预有效|
|VO₂观察|设备报告相对 VO₂（mL/kg/min）、来源/设备/版本/协议、事件/可见时间|OBS-VO2-REPORTED；已记录估计及同身份有界差值|不是气体分析实测，不反算真实绝对耗氧或减重因果贡献；未知协议不强行合并|
|体重与设备能量|同来源体重kg、完整日 basal/active kcal；无重复重叠、按本地日/版本核对|设备 total=basal+active；覆盖分母与完整日均值分别显示|不是 RMR/TEE；不加 workout/TEF；不从体重轨迹推断摄入|
|可识别性|明示模型 D=E+b、Q=I−E；I摄入/E真实消耗/b设备偏差/Q组织储能均需约束|变换 (I+c,E+c,b−c) 保持 D、Q，属代数非唯一性；体重不是已测Q|缺文献与数学不可识别分别说明；不输出个人热量处方|
|结果跟踪|冻结候选、选择、实际执行、质量/停止原因、约定随访窗；已到/未到/未知状态分别统计|分子、分母、未知和未到终点；计数无需因果试验证明|采纳≠执行≠达标≠有效；不在线学习或修改规则效力|

参数细表为 [`parameter-inventory.json`](../artifacts/analysis-core/parameter-inventory.json)，29 个身份包含 ID/版本、值或动态来源、单位、类别、来源、范围、验证状态、是否可参与个人行动及缺失行为，已在临时 `ParameterRegistry` 中验证结构。用户计划/器械仅可参与有规则授权的行动；产品窗口、浮点容差、检索预算和分页不会被解释成生理阈值。

## PDF T01–T28 映射

以下测试引用都是实际存在的函数或目录验收用例。完整机器映射见 [`acceptance-matrix.json`](../artifacts/analysis-core/acceptance-matrix.json)。T24 采用 Prompt v2 的最新规定：主动 lexical 不算降级。

|PDF|节点／普通入口|断言与代码|实际测试|生产身份|
|---|---|---|---|---|
|T01|S1；力量记录/导入|重传只计一次，真实相同两组分别计数<br>`src/healthzip/training/service.py`<br>`src/healthzip/science/strength.py`|`tests/science/test_contracts_and_strength.py::test_work_set_structure_and_retries`|事实/软件边界；科学限制保留|
|T02|S1/S5；力量进阶→候选|30→32.5每侧：配重+5，总阻力百分比未知<br>`src/healthzip/science/semantics.py`<br>`src/healthzip/advice.py`|`tests/science/test_contracts_and_strength.py::test_plate_load_and_assistance_semantics`<br>`tests/integration/test_analysis_w1_flow.py::test_smith_trial_normal_page_choice_execution_and_review`|现有规则正常路径实跑|
|T03|S2；分析→同条件任务|动作/器械/ROM/协议异同分段；未知不合并<br>`src/healthzip/science/semantics.py`<br>`src/healthzip/workflows/selection.py`|`tests/science/test_contracts_and_strength.py::test_reference_not_hindsight_best_and_effort_not_repetitions`<br>`tests/science/test_review_repairs.py::test_r02_protocol_identity_and_version_are_part_of_measurement_contract`|事实/软件边界；科学限制保留|
|T04|S1/S2；分析→参考组选择|事后最佳不冒充前瞻预指定参考<br>`src/healthzip/analytics/reference_selection.py`<br>`src/healthzip/science/strength.py`|`tests/science/test_contracts_and_strength.py::test_reference_not_hindsight_best_and_effort_not_repetitions`|事实/软件边界；科学限制保留|
|T05|S5；力量进阶→双重进阶|30×10未到8–12上限，不自动进阶<br>`src/healthzip/science/strength.py STR-25`|`tests/integration/test_analysis_w1_flow.py::test_smith_trial_normal_page_choice_execution_and_review`|现有规则正常路径实跑|
|T06|S5；练前建议→条件核对|到上限但缺RIR：保留记录、不授相关数值候选<br>`src/healthzip/science/strength.py STR-25`|`tests/science/test_contracts_and_strength.py::test_candidate_uses_plan_equipment_and_review_not_readiness_multiplier`|事实/软件边界；科学限制保留|
|T07|S5/S6；候选→选择→实际训练→反馈|满足真实档位/计划/权限恰好生成候选；不加组<br>`src/healthzip/advice.py`<br>`src/healthzip/ui/recommendation_page.py`|`tests/science/test_contracts_and_strength.py::test_candidate_uses_plan_equipment_and_review_not_readiness_multiplier`<br>`tests/integration/test_review_candidate_flow.py::test_visible_candidate_task_end_to_end`|现有规则正常路径实跑|
|T08|S4/S5；为什么/知识解释|解释权限不生成数值行动；有效背景仍可显示<br>`src/healthzip/knowledge/core.py`<br>`src/healthzip/knowledge/metric_retrieval.py`|`tests/unit/test_regression_covariance_contract.py::test_n1_scope_has_no_personal_model_or_candidate_authority`<br>`tests/integration/test_v14_bounded_discussions.py::test_discussion_uses_actual_plan_records_and_explanation_without_numeric_rule`|事实/软件边界；科学限制保留|
|T09|S2/S5/S6；长期复核→允许策略试验|无严格停滞也可按有效规则试验32.5×8；次数是用户目标<br>`src/healthzip/workflows/service.py`<br>`src/healthzip/science/strength.py STR-26`|`tests/integration/test_analysis_w1_flow.py::test_smith_trial_normal_page_choice_execution_and_review`<br>`tests/integration/test_analysis_w1_flow.py::test_other_exercise_equipment_step_and_new_pain`|现有规则正常路径实跑|
|T10|S5；候选→核对当前使用|新疼痛限制旧候选当前使用，旧快照不变<br>`src/healthzip/advice.py::current_use_status`|`tests/integration/test_v14_advice_flow.py::test_new_symptom_changes_current_use_without_rewriting_frozen_task`<br>`tests/integration/test_analysis_w1_flow.py::test_other_exercise_equipment_step_and_new_pain`|事实/软件边界；科学限制保留|
|T11|S2/S3；更新分析/长期趋势/报告|多次无改善触发具体因素复核；已有RIR实际使用，无生理次数阈值<br>`src/healthzip/workflows/longitudinal.py`<br>`src/healthzip/workflows/reports.py`|`tests/integration/test_analysis_w1_flow.py::test_existing_rir_improvement_is_used_instead_of_called_missing`<br>`tests/integration/test_analysis_long_term_review.py::test_joint_components_do_not_mislabel_load_or_rir_progress`<br>`tests/integration/test_analysis_long_term_review.py::test_all_training_backgrounds_include_middle_changes_and_missing_branch`|现有规则正常路径实跑|
|T12|S2；长期趋势→方法限制|宽区间含0不表示等效；缺误差/校准不输出确定停滞<br>`src/healthzip/science/statistics.py`<br>`src/healthzip/science/strength.py STR-22`|`tests/science/test_contracts_and_strength.py::test_real_time_regression_and_zero_error_do_not_imply_plateau`<br>`tests/science/test_metric_acceptance.py::test_metric_catalog[STR-22-T01]`|事实/软件边界；科学限制保留|
|T13|S2；恢复背景→描述基线|基线排当前日、日等权、MAD0时z未知；独立窗口<br>`src/healthzip/science/state.py`<br>`src/healthzip/workflows/service.py`|`tests/science/test_state_energy_prediction.py::test_daily_equal_weight_baseline_excludes_current_and_mad_zero`<br>`tests/integration/test_analysis_scope_resume.py::test_w2_explicit_completed_day_baseline_independent_of_display`|事实/软件边界；科学限制保留|
|T14|S4；恢复背景→SDNN依据|SDNN≠RMSSD、RHR≠其他心率，不跨测量授恢复行动<br>`src/healthzip/science/state.py`<br>`src/healthzip/knowledge/metric_retrieval.py`|`tests/science/test_state_energy_prediction.py::test_sdnn_not_rmssd_and_rhr_not_any_heart_rate`<br>`tests/unit/test_knowledge.py::test_offline_missingness_and_protocol_identity`|事实/软件边界；科学限制保留|
|T15|S1；分析→睡眠来源选择|同源并集、跨午夜实际时间、不计inBed、多源需选择<br>`src/healthzip/science/state.py`<br>`src/healthzip/analytics/sleep_selection.py`|`tests/science/test_state_energy_prediction.py::test_inbed_generic_overlap_stage_conflict_and_explicit_episode`<br>`tests/science/test_state_energy_prediction.py::test_sleep_coverage_elapsed_dates_and_source_choice`|事实/软件边界；科学限制保留|
|T16|S1/S3；恢复背景|3h仅为已记录时长，不认定实际只睡3h<br>`src/healthzip/workflows/facts.py`<br>`src/healthzip/ui/workflow_page.py`|`tests/integration/test_analysis_workflow_runs.py::test_observed_three_hours_remains_a_fact_without_recovery_classification`|事实/软件边界；科学限制保留|
|T17|S1/S4；结束训练→恢复背景|不以组RPE补整场；实际量表/时点/人群控制解释<br>`src/healthzip/science/state.py`<br>`src/healthzip/workflows/evidence.py`|`tests/science/test_state_energy_prediction.py::test_session_rpe_is_not_set_median_and_preserves_collection_delay`<br>`tests/knowledge/test_analysis_workflow_evidence.py::test_saved_session_prerequisites_and_revocation`|事实/软件边界；科学限制保留|
|T18|S1；心肺观察|未来修订不进入旧cutoff；不消费旧全历史卡<br>`src/healthzip/analytics/observations.py`<br>`src/healthzip/science/observations.py`|`tests/science/test_source_observations.py::test_revisions_availability_and_half_open_window_do_not_resurrect_previous_values`|事实/软件边界；科学限制保留|
|T19|S1/S2；心肺观察|单点展示设备估计；不同版本分段；不诊断适能下降<br>`src/healthzip/workflows/facts.py::vo2_segments`|`tests/integration/test_analysis_observation_flows.py::test_w3_single_unknown_and_known_segmented_estimates_reach_page`|事实/软件边界；科学限制保留|
|T20|S1；体重与设备能量背景|4/7完整日、完整日均值2000kcal/日；不补周总量<br>`src/healthzip/workflows/facts.py::energy_coverage`|`tests/integration/test_analysis_observation_flows.py::test_w5_four_of_seven_complete_days_do_not_infer_intake_or_fill_missing`|事实/软件边界；科学限制保留|
|T21|S1；体重与设备能量背景|basal+active，不重复加workout/TEF<br>`src/healthzip/science/energy.py`|`tests/science/test_state_energy_prediction.py::test_device_energy_no_workout_doublecount_no_tef_or_missing_zero`<br>`tests/integration/test_analysis_observation_flows.py::test_w5_four_of_seven_complete_days_do_not_infer_intake_or_fill_missing`|事实/软件边界；科学限制保留|
|T22|S2/S4；体重与设备能量背景→为什么|体重下降+设备稳定仍不能识别摄入/真实消耗；无热量处方<br>`src/healthzip/science/energy.py`<br>`src/healthzip/workflows/service.py`|`tests/integration/test_analysis_observation_flows.py::test_w5_four_of_seven_complete_days_do_not_infer_intake_or_fill_missing`<br>`tests/science/test_state_energy_prediction.py::test_energy_boundary_no_uniform_rate_assumption_and_nonidentifiable_intake`|事实/软件边界；科学限制保留|
|T23|S2；研究入口；普通工作流无预测行动|模拟B1优势保持研究身份，不能授真人处方<br>`src/healthzip/science/prediction.py`<br>`src/healthzip/science/registry.py`|`tests/science/test_state_energy_prediction.py::test_temporal_b0_b1_same_batch_and_current_srpe_leakage_excluded`<br>`tests/science/test_state_energy_prediction.py::test_reproducible_simulation_reports_conditional_failures`<br>`tests/science/test_contracts_and_strength.py::test_registry_versions_error_budget_and_simulation_gate`|事实/软件边界；科学限制保留|
|T24|S4；本地资料检索|主动lexical非降级；请求语义服务失败才degraded（Prompt v2覆盖PDF旧句）<br>`src/healthzip/workflows/evidence.py`<br>`src/healthzip/knowledge/metric_retrieval.py`|`tests/knowledge/test_v15_retrieval.py::test_unavailable_models_report_lexical_degradation`<br>`tests/knowledge/test_analysis_workflow_evidence.py::test_selected_longitudinal_outcome_uses_its_own_source_and_current_check`|事实/软件边界；科学限制保留|
|T25|S4/S5；核对当前适用性|撤销后新决策受限，旧结果不改；缓存不能恢复权限<br>`src/healthzip/workflows/dependencies.py`<br>`src/healthzip/advice.py`|`tests/knowledge/test_v15_retrieval.py::test_current_lifecycle_overrides_frozen_membership`<br>`tests/knowledge/test_v15_retrieval.py::test_revocation_during_remote_ranking_cannot_restore_authority`<br>`tests/knowledge/test_analysis_workflow_evidence.py::test_saved_session_prerequisites_and_revocation`|事实/软件边界；科学限制保留|
|T26|S6；候选→反馈→复盘|采纳未执行/未反馈success=null；保留分母<br>`src/healthzip/science/strength.py STR-27/28`<br>`src/healthzip/analytics/followup.py`|`tests/science/test_contracts_and_strength.py::test_nonexecution_and_unknown_execution_cannot_count_success`<br>`tests/science/test_contracts_and_strength.py::test_followup_targets_are_frozen_and_unknowns_keep_denominators`|事实/软件边界；科学限制保留|
|T27|S1/S3；长期复核→练前背景|仅每条训练开始前事件；训练后睡眠不进练前因素<br>`src/healthzip/workflows/longitudinal.py`|`tests/integration/test_analysis_long_term_review.py::test_all_training_backgrounds_include_middle_changes_and_missing_branch`<br>`tests/science/test_state_energy_prediction.py::test_temporal_b0_b1_same_batch_and_current_srpe_leakage_excluded`|事实/软件边界；科学限制保留|
|T28|S0/S4；知识/工作流请求边界|原文不是指令，不读他人资料；伪造MetricResult不入工作流<br>`src/healthzip/knowledge/retrieval.py`<br>`src/healthzip/workflows/contracts.py`|`tests/unit/test_knowledge.py::test_private_data_not_indexed_and_scope_does_not_expand`<br>`tests/knowledge/test_v15_retrieval.py::test_arithmetic_and_tenant_refusal_never_invoke_models`<br>`tests/integration/test_analysis_workflow_runs.py::test_forged_results_and_conditions_are_not_workflow_inputs`|事实/软件边界；科学限制保留|

## 77 项用途与生产证据状态

机器映射逐项列出原 77 个 ID、标题、PDF附录位置、执行模块、节点、用途类别、工作流消费者、真实测试 case ID 与生产证据状态。STR 的研究/设计项、ENERGY 条件推断、PRED 和 QAL 分别保留受限研究或审计身份；不为凑数量塞入每个流程。原周/月 REPORT 仍由汇总入口消费，其组成事实复用工作流。VO₂ 扩展单列，周期观察不在本轮使用。

W4 选择 RHR、SDNN 或体重时仅消费所选结果；不借用全局力量可比性、未改善触发、候选或随访分母。W4 选择力量任务时才使用相应 STR/STATE/BODY/REPORT 背景。普通数据定义不需要文献证明“用户记录过几次”；解释/行动另外核对适用证据，研究缺口不抹去记录事实。

真实资料集成使用公共知识库的可丢弃备份及合成私人库。现有规则正常闭环达成，RIR/SDNN 有适用的有限解释；STR-12/19、睡眠、RHR 的该次查询仍有适用性或充分性限制，未包装为全链科学充分。没有新增批准、修改发布、重建向量或改变旧评测分母。最终命令、代码输入哈希、通过/失败数量、实际资料回执与推送身份见最新验证和发布回执；旧 `final-verification.json` 保留 `d300a9a` 那批事实。
