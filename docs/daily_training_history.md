# 日常训练：最近一次全组事实与可选建议

本轮基线为 `d48d26b7606f5b1ff31e9aa9578500cac5e962a4`。2026-11-18 用户合同替代“日常训练须先自动预指定某一参考组”：普通实际记录直接成为下一次日常事实基础。身体事实、近期同部位训练、最近一次同动作实际训练分开取数；专项统计继续遵守自身方法条件。旧设计、审核、实际记录、明确反馈及冻结结果保留历史身份。

## 被替代与保留的合同

|旧行为或合同|本轮处理|
|---|---|
|普通创建计划组、改目标、重排或替换动作时自动指定／撤销／重选研究参考|取消。普通组不补 `reference_set`，不伪造 `reference_declared_at`；有无计划均可记录|
|日常 STR-25/26 调用须先经 `reference_rows` 找到预指定参考|日常改用独立业务输出，按最近实际会话的全部组逐项判断；共用计算但不冒充旧科学指标|
|d48d26b 已保存的系统参考来源与历史手动参考|保留原身份、来源和事件；修改计划不把旧系统来源改为用户手选|
|特定测量、误差、预测校准、严格统计方法的实际前提|保留。普通记录不会自动取得专项测量资格|
|旧采纳／执行反馈、旧 STR-27/28 分母|保留原语义；正常日常路径不写这两类反馈|
|记录、建议、客观对照、身体—力量联合周月报告|继续通过真实服务及原页面使用；用户可保持原重量或自由调整|

主流程为：选部位或已有计划 → 确认动作 → 自动查看三类事实、适用解释、可选安排及缺项 → 自由记录实际 → 下一次读取新实际。用户不需要指定参考、采纳建议、补填旧数据或为正常训练先建模板。实际不同不推断拒绝、失败或执行状态；无日志不代表没训练。

## 本轮资料与条件核对

仅核对现有四条应用规则及绑定的 `CORE-CLAIM-PROGRESSION@1.4.3`，未重开资料库复核、教材获取或科学 Gold 验收。只读公开知识库得到的具体元数据见 [规则用途核对](../artifacts/analysis-core/daily-training-rule-scope.json)。仓库内 `core_rules.json` 的 draft 只是设计登记，不能单独授权数字；运行仍读取当前有效且审核匹配的知识权限。

现有来源主张的范围是健康成人、群体、多周项目中的一般渐进训练与个体化原则；不会提供本用户的公斤数、起始水平、唯一最优处方或一次训练所有组的加重结论。四条已登记应用规则的 `application_logic` 明确是 bounded single task，且说明来源不规定该确切算法或个人重量。规则的审核身份仍为 AI 辅助，非独立专家审定。

|条件类别|相关条件|本轮用途|
|---|---|---|
|来源／已审核应用规则|当前有效规则、主张与 span、用途权限、许可、实际适用档案（年龄、健康自报范围、训练目标、经验）、允许的具体 strategy|继续通过真实知识服务核对；缺失／撤回不给数字，解释权限不升级为行动权限|
|应用规则的单任务范围|明确用户计划目标、真实器械可用档位、数字的计划／器械出处、退出／复核与效果未知|每条普通组分别提供一个待开始目标组的可选安排；不产生整场统一处方|
|实际数据与可比性|动作定义版本、器械实例／设置、单位与负荷口径、侧别、ROM、次数语义、实际时间、工作组完成状态、质量／疼痛等|保留。缺项不妨碍事实展示和自由记录；只限制依赖该条件的计算|
|现有代码额外施加的日常选择门槛|预先 `reference_set`、`reference_declared_at`、固定首组及含位置的研究 task 身份|从日常路径移除；没有将这些旧代码条件宣称为教材要求|
|专项统计条件|所用方法确实需要的协议、误差与校准等|仍由原科学方法执行，不因日常取普通组而放宽|

原规则 payload 中的 `comparable_reference`、`measurement_protocol`、`candidate_choice` 等概括性输入组名称保留原文。这里没有通过清空真实器械或 task 身份来让旧方法通过：日常物理可比性有单独版本映射，真实已声明的规则条件仍由权限服务检查；若规则确实要求 `user_choice=requested_strategy_review`，自动路径的 `user_choice=null` 不能通过。可选方案也不会被写成用户已经选择了任务。

## 三个数据范围与最近一次选择

`daily-exercise-history-1.0.0` 先按截止时点可见事件重放，发现当前动作的终身历史，再定位最近一次实际会话，最后读取该会话中该动作的全部组。30 日展示／分析窗口和旧 365 日候选窗口不截断这一搜索。

- 身体背景沿现有 `body_context` 和各指标自己的窗口、单位、来源、覆盖及缺失合同读取，包含睡眠、RHR、SDNN、体重与实际自评。数值进入适用性／解释核对，不自动换算公斤、组数、恢复百分比或疲劳原因。
- 近期同部位训练保留动作、日期、组和表现，只作相关训练背景；别的动作重量不换算成本动作重量。
- 当前动作历史按稳定动作身份发现。最近一次若器械、口径、侧别、ROM 等已变化，仍显示其真实最新事实和逐组不可比原因，不回退旧好成绩冒充“上次”。

日常物理身份复用既有 `condition_snapshot` 的动作定义、设备、设置、负荷、侧别、幅度、次数语义及确认信息。研究参考协议不属于这个事实用途的身份；原研究 `task_id` 不清空、不重写，映射及匹配版本逐条冻结。动作在整场中的位置变化不使日常历史消失。同场重复动作实例保留各自实例 ID、组 UUID、原顺序和对应条件。

排序用实际发生时间，录入／可见时间仅控制该记录当时是否已知。当前父会话排除出“上一场”，同日更早的另一会话保留独立身份；纯草稿不算实际。较近的中止、失败或下降不能被筛掉后改用较好成绩。存在无法排序的实际记录时仍显示已知事实，但不产生依赖“最近一次”顺序的数值。相关实际存在未解决冲突时也拒绝数值，不把某一冲突版本当成确定值。缺少组时间而父会话实际开始已知时，以该真实会话时间标示日期，同时保留组时间未知；时间无法排序、同刻多会话或旧记录可见性未知时保留事实与限制，不借用导入时间。

选中的全组事实保留父会话／实例／组身份、类型及顺序、负荷／单位／口径、次数、RIR／区间及记录方式、质量／疼痛／停止原因、完成／中止／跳过／删除／缺失状态、实际／可见时间及修订。工作组按方法判断，热身或失败不被改写为成功工作组。删除会话不再参与有效最近选择；若采用较早会话，冻结其实际日期和删除排除原因。撤销删除恢复唯一记录，不重复计数。

## 全组如何进入决策

业务版本为 `current-training-2.0.0`；逐组规则输出为 `DAILY-SET-OPTION` / `daily-set-options-1.0.0`。`daily_history` 冻结最新会话及全部记录；`daily_decisions.input_record_ids` 对应全部组，每组都有事实用途、限制检查和对当前目标组的规则评估。每条数值选项保存本次全部输入、实际计算组、其他组用途／未用于此算式的原因、来源规则／版本、身体／近期训练背景、当前目标和 UUID。

当前应用规则只支持单任务选项。本轮没有新增“任意一组达标则所有组加重”“全部组达标”“连续两次达标”、均值／最大值、加权分或代表组。对每个尚未开始的目标组，分别评估每个历史工作组的资格和对应规则。某历史组不参加某条单组算式，不代表其疼痛、质量、失败等限制被忽略：相关已观察组与本场实际共同进入 `candidate_applicability`。后续组更正会改变事实、限制和冻结依赖；不要求每次变化都机械改变公斤数。

|可选安排|规则作用范围与满足条件|重量／次数／RIR 来源及缺失处理|
|---|---|---|
|按用户计划上沿核对（共用 STR-25 算术）|单条完成工作组。质量／症状适用、物理条件和单位可比；已达到明确计划次数上沿，实际 RIR 落在明确计划范围内；当前规则授予 double_progression，且存在实际更难档位|下一可用更难档位；次数为本目标组计划下限；RIR 为实际计划目标。没有目标、实际 RIR、质量或档位时不计算该数值|
|更难档位／较低次数试验（共用 STR-26 算术）|单组可选试验。当前规则独立许可 heavier_lower_reps；计划次数下限是正整数且低于该历史组实际次数；有真实可用更难档位；质量／症状等适用|重量来自实际档位，次数来自计划下限。缺 RIR 可保留未知，明确不能声称余力匹配；不保证可完成，不需先判定严格停滞|
|同负荷增加次数试验（共用 STR-26 算术）|单组可选试验。规则许可 repetition_progression，明确计划上限高于该组实际次数，其余条件适用|重量为该组真实记录负荷，次数为本组计划上限；不是把历史次数重命名为本次目标|

普通路径调用独立输入选择及结果版本，再复用 `progression_candidate` 算术和实际权限核对。旧 STR-25/26 仍是原科学结果，旧参考、协议、输出语义不被新业务结果替换。器械档位另存明确单位；页面支持未知、kg、lb、level、stack_level，未知或与记录不符时，不生成依赖新档位的加重数字，不能把历史单位猜作档位单位。同负荷次数试验只使用该组真实负荷与单位，不额外要求器械档位单位。不使用固定 2.5 kg、比例衰减、安全重量公式或由器械最小档位单独证明该加重。

合成完整页面例：上次三组为 **55 kg×10／RIR2、55 kg×9／RIR1、50 kg×11／RIR2**，三条均为从未预指定的普通记录，没有研究参考协议。当前明确目标 8–12 次／RIR2，实际档位 50／55／60／65。在隔离既有许可夹具中，单组试验分别核对 55→60 或 50→55 与 8 次；不会声称“三组都完成55×10”或整场应统一60。用户自由记录55×12／RIR2并结束，下一次最新会话及组 UUID 自动改为该实际，合法单组试验为60×8／RIR2；无需参考按钮或采纳反馈。数字只证明该合成输入及许可下的软件行为。

久远例：**500 天以前**的同动作三组仍能显示真实日期及全部表现，不显示“从未训练”；页面提示当时观察不等于今天能力，不凭间隔衰减重量。无历史例：显示“暂无该动作的个人训练记录”，不生成个人起始重量；没有模板／目标时仍可正常记录。首次实际保存后，下一次自动成为个人历史。无 RIR、身体或质量字段保持缺失，不默认补 RIR、健康状态或重量；只限制确实需要它们的方法。

## 可选专项参考和首工作组边界

专项入口留在补充信息中，非普通训练前置条件。新手动声明须发生在本任务开始观察前，已开始／跳过／删除／撤销观察的事件账本不能用于事后换选好成绩。历史自动身份与原来源保留，不批量清空，不把旧普通组追认为参考。

`first-work-set` 和 `predeclared-first-work-set` 定位按真实顺序出现的**第一工作组**，再核对其资格；首组没有计划不允许跳到第二组。`first-planned-work-set` 明确定位**首个有计划的工作组**，语义独立。明确逐组指定若与声明位置冲突则拒绝；未识别策略保持未知，不自行解释。专项筛选也必须看到完整顺序，不能先按完成或资格过滤再把第二组叫作第一组。日常历史仍读取两组真实记录，与这些专项限制分离。新的专项计算显式携带 `reference_selection_version=specialist-first-position-1.1.0`，旧冻结结果不回写。

## 缓存、时间、并发和历史冻结

新版本不会命中旧参考组驱动业务身份。签名覆盖当前父会话状态／修订、动作／条件、待开始组 UUID／目标版本、最近选择与全部相关记录的状态／修订、匹配版本、身体／相关训练、档案／声明、真实档位和当前知识权限，以及实际窗口／日期／可见性。新近训练、时间更正、删／恢复历史、条件／目标／档位或规则变化会重新核对。

先捕获输入一致性基准，再确定唯一 cutoff、读取截止时点实例和业务记录。保存及缓存命中在私人库短事务内复查依赖，变化明确拒绝并要求重算；不混用新旧字段，不无限重试，也不在长检索期间持有写锁。知识签名检查是检查时点的依赖验证，不宣称跨数据库原子事务。建议失败不回滚已保存的实际训练。

父会话 `completed`、`aborted` 或 `deleted` 时，缓存命中／未命中均由同一资格检查拒绝当前待开始建议，受控服务错误为 `current_training_session_ended:<状态>`；页面显示“这场训练已结束”。旧建议仍按其历史身份读取，合法恢复产生新状态版本并重新核对。不能仅比较新读状态与 live 状态而跳过旧缓存适用性。

缓存复用保留原 `created_at` 和相对该冻结时点的事实；旧页面测试把首屏建议永久视为之后实际对应版本的断言也被替代：身体窗口持续移动时，实际按开始前最新且身份适用的版本关联，同时保留首屏旧建议不变。相对年龄不冒充新观察。最近可见的分类疼痛自评独立检索，不受 28 日身体展示窗口截断；同一真实时刻的不同报告全部保留，不按录入先后掩盖矛盾。日期与原范围始终展示，未确认今天仍有或已经无症状，不设自动失效阈值。已有身体数据时以实际新 cutoff 重算滚动窗口，不因记录 ID 不变而声称身体事实已经更新，不新增自定有效期。晚到数据和修订影响新合法结果，不能倒写旧建议／报告或冒充当时已知。身体窗口、动作终身历史和周月范围分别保留。

状态仍为草稿但已记有实际开始／结束时间的组，也是需要核对的实际观察；其中疼痛等信息不能因状态标签而消失。这些组不因此取得成功工作组的计算资格。纯计划、无实际时间的草稿仍不算实际训练。

客观对照仍按会话、动作实例、组 UUID、目标版本及生成／开始时间关联，无最接近成绩配组。新建议冻结全组依据，`daily_comparisons` 按真实物理条件并列每条来源；不能唯一对应时写明限制，不挑代表组填回 `reference_record`。唯一可比记录才按原 STR-12/13/14 条件计算相应对照。历史旧 `reference_record` 保持旧身份，旧手工反馈及冻结报告可读。

## 页面与周月报告

`app.py → 力量` 优先显示最新动作日期、距冻结时点天数、各组实际、当前身体、近期同部位背景、可选安排和缺项。来源 UUID、任务与研究身份在展开详情中。旧“带入上次值”保留为明确的可选单条草稿复制，不再把该条说成整次训练。

选择部位尚未确认动作时，只展示已有计划、动作及近期背景；选定动作后才检索该动作，不编整套计划或个人起始重量。自由实际保存走原服务，不依赖建议成功或身体完整。周／月联合报告继续接受普通实际、可见身体及其时间对应；不满足专项统计条件不写成没有训练。声明撤回／替换后保留记录事实及旧报告，只有依赖失效声明的解释／行动受限。实际可见且属于当前动作相关范围的最新明确疼痛自评进入症状复核，保留其日期、部位及来源；不新增自评失效天数或过期阈值；没有自评不新增记录前置条件，也不将睡眠／HRV 数字改造成疼痛或公斤数。

普通逐组报告可以进入同动作、相同完整条件的当前训练；历史第 1／2／3 组的严格任务位置不再成为导航障碍。`daily-report-navigation-1.0.0` 保留原严格 task ID，并核对非空条件键、动作身份、定义版本及器械／ROM／侧别／负荷口径等条件。这个映射仅用于导航，当前建议仍重新核对当前数据和规则，不继承旧报告的数值或研究权限。命中同一建议时，只追加 `current_advice_report_link`；不改写冻结建议／报告。条件不符或来源条件键缺失时仍拒绝。

## 16 项行为验收映射

全部用例使用隔离合成库、真实训练／知识／计算服务；页面测试运行完整 `app.py`，未 mock 核心选择、权限或最终结果。下面列出验收入口；实际执行身份、最终命令、计数、Ruff 与哈希见 [本轮验证回执](../artifacts/analysis-core/daily-training-verification.json)。

|验收|实际证据入口与应核对内容|
|---|---|
|1 普通身份无关|`tests/training/test_daily_history.py::test_reference_identity_does_not_control_daily_fact_selection`；真／假／空均选同一实际。`test_daily_training_page.py` 正向三组从未预指定|
|2 最近全组进入决策|`test_ordinary_mixed_sets_latest_session_all_records_and_scopes` 及 `test_real_app_ordinary_all_groups_free_record_next_training_and_reports`：三条 UUID、input_record_ids、逐组试验范围与来源|
|3 最新下降／疼痛|`test_latest_decline_failed_session_pain_and_unknown_rir_never_fall_back`；最新中止／疼痛／未知 RIR 保留；`test_daily_advice_contract.py::test_latest_failed_decline_is_not_replaced_by_older_success` 同时验证不产生数值|
|4 普通保存更新下次|完整页面多组用例：自由55×12→下一场该会话／组 ID、60×8／RIR2及真实计划／档位／规则出处；反馈表为空|
|5 后续组改变|`test_full_record_states_and_later_group_revision_change_hash`；第一组不变、后续质量／疼痛更正改变冻结输入；`test_daily_advice_contract.py::test_ordinary_all_groups_actually_enter_rule_evaluation_and_later_pain_limits_every_option` 核对后组疼痛使各选项受限、旧建议不变|
|6 同部位不同动作|`test_daily_advice_contract.py::test_other_same_region_action_is_context_without_personal_load_conversion`：新动作无个人起始负荷、保留同部位背景|
|7 超365天|`test_ordinary_mixed_sets_latest_session_all_records_and_scopes`；完整页面参数 `history=True,age=500`，真实日期与全组、无间隔减重公式|
|8 完全无历史|`test_no_history_new_action_and_missing_data_keep_free_records`；完整页面 `history=False`，无起始重量、正常记录后下一次自动读取|
|9 无计划／缺字段|`test_missing_conditions_do_not_hide_actuals_or_fill_rir_and_plan`、完整页面无模板／无目标路径、原 `test_sampling_does_not_relax_science_conditions` 的 RIR 负例和 `test_current_training_reports.py` 身体缺失／仅身体回归；事实和记录保留|
|10 重复实例／重排／替换|`test_duplicate_instances_original_order_and_research_mapping_survive`、`test_protocol_change_does_not_remove_daily_history_but_strict_identity_differs`；原多动作替换客观关联回归|
|11 修订删恢复|`test_correction_deletion_undo_reselect_without_rewriting_frozen_history`、原 `test_parent_deletion_cutoff_and_undo`；删除排除日期／原因、旧冻结不变、恢复唯一计数|
|12 首工作组|`test_first_work_protocol_cannot_skip_unplanned_first_work`、`test_first_planned_work_protocol_has_distinct_position`、`test_specialist_filter_locates_first_before_eligibility`；日常依然读取两组|
|13 结束会话缓存|`test_daily_advice_contract.py::test_ended_parent_never_returns_pending_advice_with_or_without_cache_and_restores` 的 completed／aborted／deleted × 有／无缓存及恢复；直接服务不能返回待开始选项，旧 advice ID 仍可读|
|14 并发／晚到|原 `test_second_connection_changes_before_freeze_are_rejected`、`test_cache_hit_checks_interleaved_session_deletion`、`test_rule_retraction_during_calculation_rejects_old_authority`、`test_late_entry_occurrence_not_import_order_and_original_cutoff_is_frozen`；`test_daily_advice_contract.py::test_interleaving_after_history_selection_refuses_mixed_version_and_keeps_actual_save` 的更近会话、目标、结束、删历史、档位和规则撤回六类交错|
|15 权限／范围|原 `test_explicit_choice_condition_is_not_forged_for_automatic_options`、普通三组数值正向及缺规则／RIR／档位负例；无用户主动选择或反馈伪造，无固定加重／恢复分／因果|
|16 完整页面与报告|新 `test_daily_training_page.py` 和 `test_daily_report_navigation.py`；原 `test_current_training_acceptance.py`、`test_current_training_reports.py` 和三项修复页面删恢复回归，含部位／模板、声明、两入口联合周月及旧反馈；普通第3组 W4 报告进入当前训练，独立链接与冻结结果保留|

补充的直接服务证据位于 `tests/integration/test_daily_advice_contract.py`：`test_ordinary_all_groups_actually_enter_rule_evaluation_and_later_pain_limits_every_option` 核对三条真实输入及逐组数字、末组修订后的适用性；`test_ended_parent_never_returns_pending_advice_with_or_without_cache_and_restores` 覆盖三种结束状态 × 有无缓存及恢复；`test_interleaving_after_history_selection_refuses_mixed_version_and_keeps_actual_save` 覆盖更近训练、目标、结束、删历史、档位及撤回规则的六种交错。普通主流程的反馈表保持为空。

`tests/integration/test_daily_symptom_history.py` 补充 27／29 天分类症状状态、同刻矛盾自评、更新明确无症状、缺身体、混合单位的逐来源计算、首组无计划／次组有计划的专项与日常组合、带实际时间的草稿症状，以及完整页面的跨窗口有日期症状展示。身体滚动指标保留其原窗口，分类症状不从展示窗口取得有效期；每条历史组只使用自己已知且匹配的单位，不受其他组单位不同的无关门槛阻断。

`tests/integration/test_daily_report_navigation.py` 直接验证三个普通组位置的报告链接同一缓存建议、各自链接、冻结 JSON／Markdown 与零反馈；六类动作／条件差异及动作定义升级继续拒绝；完整 `app.py` 明确选择第 3 组 W4 报告并进入当前训练。

最终整仓 pytest、既定 Ruff 与最终文件哈希清单见本轮交付回执；发布后另核对远端 SHA／树。旧1848项／310份清单只属于基线历史，不能作为本轮完成证明。

## 本轮验证记录与限制

首个完整整仓运行得到 **1925 passed、1 failed、1 warning，1387.32 秒**，随后既定 Ruff 通过；没有中断或跳过该失败。失败为旧 `test_v13_training_ui.py::test_training_ui_condition_target_replacement_order_and_numeric_errors` 的动作重排控件重跑超过 AppTest 默认 3 秒，尚未到业务断言。该用例独立重跑 1 passed，整个旧页面文件重跑 3 passed。原测试仅把第一次渲染设为 30 秒；现将同样的 `default_timeout=30` 贯穿三个既有页面用例的后续控件操作，保留全部业务断言，不修改服务结果。

最后的普通报告导航修改后，15 个训练／报告／工作流测试文件的扩展回归为 **254 passed、1 warning，531.44 秒**，同一最终生产代码的 Ruff 通过。该副本 359 份受验输入在运行中未变；首个整仓副本则有 358 份，缺少后来新增的导航测试，且 `current.py` 仍为导航修复前版本。这些运行分别保留身份，不能把不同副本说成同一最终代码。唯一 pytest 警告是旧 `record_property` 与 JUnit xunit2 不兼容；最终整仓使用 `junit_family=legacy` 正确保存该属性，未过滤警告。最终整仓也包含导航和上述超时配置修复。

最终冻结副本完整运行 `PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q --tb=short -o junit_family=legacy --junitxml=<stage>/pytest.xml`，结果为 **1935 passed、0 failed、0 errors、0 skipped、0 pytest warnings，1372.37 秒，退出码 0**。随后执行既定 `ruff check src tests app.py tools/analysis_core*.py`，退出码 0。359 份最终代码、测试、工具、配置、合成夹具及规范输入在运行中未变，与最终工作区逐文件 SHA-256 一致：src 159、tests 131、tools 40、specs 20、fixtures 3、templates 4，加 app.py 和 pyproject.toml。

最终 [输入清单](../artifacts/analysis-core/daily-training-input-hashes.json)、[公开文件清单](../artifacts/analysis-core/daily-training-public-files.sha256) 与 [验证回执](../artifacts/analysis-core/daily-training-verification.json) 按实际文件重新生成。公开文件清单排除自身及引用它的回执，避免哈希循环；两者最终由 Git 提交／树身份标识。回执保存完整实测命令、环境、首轮失败与最终通过的区别、16 项验收的实际 JUnit 身份、生产规则六例的范围和清单摘要；中断／被替代的运行不计为完整通过。

当前终身历史检索重放可见事件，尚未为超大私人训练库建立新的分页性能验收。数值规则只授权有条件的单组可选试验，不授予整场处方、今天能力、严格停滞或个人因果结论。缺少适用规则、真实目标、质量／症状或方法必要单位时，相应数字继续受限，事实和自由记录保留。本轮没有新增独立专家审核、科学 Gold 或真人预测有效性认证。
