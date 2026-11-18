# 本次训练主流程与联合周期报告

> **本轮合同已替代旧日常自动参考要求。** 当前设计与验收见 [日常全组历史](daily_training_history.md)。本页的自动预指定、参考组驱动数值及旧测试／哈希是历史实现回执；其并发一致性、删除、历史冻结和专项方法保护继续保留。新普通组不自动获得研究参考身份。

2026-11-18 追加修复：基于 `555acb0ae8c3b2888f1e672be05569499c28484a` 的自动参考、并发冻结及父会话删除合同见 [三项修复验收](current_training_three_repairs.md)。业务版本更新为 `current-training-1.1.0`；下面的 1.0.0 回执保留历史身份。

正常计划创建及草稿修改在训练事务内按 `first-planned-work-set/1.0.0` 前瞻指定首个计划工作组，重复动作实例共享同条件的采样范围。明确的逐组计划指定优先；可识别的 `first-work-set` / `predeclared-first-work-set` 计划协议沿用，其他非空选择规则不猜测。无明确选择规则时使用公开的产品顺序规则，不补科学协议。预指定只是选择观察位置，不代表适宜加重或最优训练。元数据记录系统／用户来源、真实时间、会话、任务、动作条件、组 UUID、目标及模板版本，变更沿训练事件保留。已经观察、跳过、删除或撤销观察后不重新挑好成绩；历史普通实际不倒填。资料服务失败不影响此事务及实际保存。

数值仍由同一 STR-25/26、个人档案、记录质量、实际档位和资料权限核对。新合规预指定实际会成为下一次参考；不合格参考不回退挑选本次更好组。界面显示参考日期、动作和口径、实际重量次数 RIR、选择来源、用户计划范围和档位来源；更新较近但未被选入的普通实际说明排除原因。STR-25 的余力匹配条件与 STR-26 的独立可选试验语义不变，缺 RIR 不填值，也不宣称已经匹配努力或预测成功。

建议在幂等初始化后、任何业务实例读取前捕获输入版本和唯一 cutoff，所有目标、条件、组范围与签名复用同一 AdviceContext 可见实例。初次保存及缓存命中都在私人库短事务中核对当前实例、父会话、逐组版本与开始状态、目标、训练／档案／来源／声明版本、真实档位和知识签名。变化明确拒绝并可重试，已经保存的真实训练不回滚。检索不持长写锁；另一知识数据库的版本／签名检查只保证检查时点的依赖状态，不是跨库原子事务，也不保证返回后不会变化。

客观对照的身份包含父会话版本、状态及删除时间。整场删除后的当前对照标记记录移除，MetricResult 排除记录且保留“无日志不等于没有训练”；历史页显著提示删除。显式删除前 cutoff 保留历史，删除后 cutoff 排除，撤销后生成恢复版本并只计一次。删除前冻结的建议、对照及报告均不重写，新周／月报告排除删除会话。

本轮按用户 2026-11-18 的产品合同实施，审查基线 `eeb33d508e08191b7467cd6fdd20ba61b19ea5ab`。业务版本为 `analysis-workflows-1.7.0`、`healthzip-v1.7.0`、`current-training-1.0.0`、`joint-period-report-1.0.0`。既有科学公式、来源许可和数值行动规则未改变。最终验证结果记录在本文件末尾及新的验证回执中；此前 1779 项历史回执不是本轮通过证明。

本轮已读取本地 `HealthZIP_Diagnostic_Decision_Workflow_Design.pdf`（40 页）。其中记录、可比性、因素复核、证据与行动权限继续生效；要求先从报告创建候选、采纳并填写执行反馈的旧主流程，由本轮用户明确要求取代。没有重新开展资料复核、教材获取、资料扩充、向量构建或检索评测。

## 实际入口

1. 进入「力量」。可先按部位查看既有动作、肌群映射、相关计划与近期记录，或直接选择已有模板开始训练。部位本身不生成具体重量或完整计划。
2. 建立或继续真实草稿训练，选定动作后，页面自动展示本次身体背景、近期表现、合法数值选项及缺项。不需要打开旧报告、选择策略或填写采纳反馈。器械档位在动作下保存后复用；未知值不自动补齐。
3. 自由记录实际重量、次数、RIR、质量等。可以保持原计划、修改实际重量次数或换动作。RIR 缺失保留未知，实际保存不依赖建议服务。页面自动显示客观对照；训练历史中可再次查看。
4. 下一次训练根据新记录生成新的建议版本。在「分析 → 本周／本月复盘 → 生成当前周期复盘」或「报告 → 本周／本月 → 生成 Markdown 报告」生成联合报告。页面与下载使用同一冻结文本，刷新继续显示该报告；再次生成建立新版本。

「结束训练并保存反馈」保留既有按钮名称，此处采集整场主观感受等可选记录，不强制填写建议采纳或执行状态。历史明确反馈仍可从兼容入口阅读和填写。

## 数据与时间合同

`training.current.current_advice` 复用 `build_advice_context`、STR-25/26 和 W1。自动来源为 `automatic_training`，`user_choice=null`；只有明确手动请求策略时才使用 `requested_strategy_review`。若规则要求主动选择而实际没有，仍拒绝相应数值。允许的多策略并列展示，不用任意评分选出所谓个人最优方案。

- `current_training_advice`：不可变建议、逐个尚未开始的目标组 UUID、原计划／目标版本、输入与知识签名、身体背景、生成时可见参考记录和复核运行。
- `training_advice_equipment`：按实际动作条件保存器械档位版本，相同配置重存幂等。
- `training_objective_comparison`：当前实际修订与练前版本的客观身份对应。使用会话、动作实例、组 UUID、条件和开始前最新时间；同刻多版或无开始时间保留歧义。不会按最接近建议的重量／次数择优配组。
- `current_advice_report_link`：旧报告作为导航来源；缓存命中也可追加链接，不改变原建议及其输入身份。
- `joint_period_report`：冻结本期数据、声明生命周期、工作流引用、客观对照和报告文本；同一完整周期快照仍通过既有 `analysis_run` 保存，供原分析入口读取。

这些表属于业务版本与关联结构，不是新科学指标。沿既有 schema 5 幂等扩展，不回填未知值、不删除旧反馈、不把自动关联写进 `training_recommendation_feedback`。STR-27/28 的分母只保留旧明确反馈语义。

对照示例：建议可能包含 34 kg × 8 次，用户实际仍为 30 kg × 11 次、RIR2。系统展示实际、建议差异，以及冻结参考 30×10 到实际 30×11 的 STR-12 次数差 +1 和双方 RIR；不推断拒绝、采纳、执行、失败或干预效果。没有记录只表示无关联记录。修订不累计成两组，删除表示记录移除，旧建议／原计划／旧报告不变。

练前数据按生成截止时间及可见版本冻结。训练后到达的身体记录可以进入新的报告，不能倒灌原建议或前瞻的历史练前背景。显式回顾模式保留其可见性标识。当前报告的对照按统一 cutoff 重放实际修订，再限定本期实际组 UUID。

自动建议按相关训练、目标、个人适用信息、身体、自评、声明、器械配置、资料版本和本地日期复用；相同 rerun 不重复检索。冻结前复查输入、知识与档位；相关并发变更拒绝冻结并提示重算。检索不占用私人库的长写事务。资料服务故障不保存伪成功建议，真实组仍可保存，恢复后重算；未知历史开始时间不会因恢复而被补成已知。

## 联合报告与长期复核

`workflows.longitudinal.body_context` 是正常训练日与历史练前背景的共同入口。正常草稿也读取身体数据，不要求先发生未改善。`selection.session_backgrounds` 接受普通实际组，无需把它伪装成参考组。

报告将本地自然周／月的本期部分、前两个完整周期比较、每次训练开始前背景分别标明。当前事实含日期、动作／肌群、工作组、次数、负荷口径、RIR、频率／间隔、原计划与实际、可比较变化和不可比较项。新动作的普通实际组正常进入任务清单；参考与研究指标继续执行原门槛。无训练时身体事实保留；无身体时训练事实保留并说明联合分析缺项。

身体指标覆盖睡眠主段／24 小时、覆盖／分期／时点，RHR、SDNN，参考中位数／MAD／偏离，疲劳／酸痛／疼痛，体重日值／趋势；整场 sRPE、时长及 AU 仅在实际量表与时点满足时可用。相关 VO₂ 来源观测与设备基础／活动／配对能量、完整日覆盖、不可识别性保留各自定义。数值包含单位、日期、样本或覆盖、来源／设备／协议；完整日能量均值不补缺日、不重复加入运动摘要或 TEF，不反推饮食。

每次实际训练与开始前可见身体记录建立时间对应；因素复核显示支持、削弱与未知，下一步由已有记录、缺项和适用资料解释限定。负荷、次数与实际 RIR 联合的描述性未改善继续使用既有核心，查看范围不会被找参考用的 365 日窗口替代。严格统计停滞／因果条件不足不阻断描述、因素排查或独立有效行动。没有新增生理天数／次数阈值、恢复总分、固定加重幅度或 HRV 因果判断。

## 声明失效与历史报告

两报告入口在生成时统一复查声明。撤回／替换时保存原 `context_id`、历史值、事件、受限原因；失效值停止授权解释，身体和训练事实继续。下载自身含限制说明，不抛出未捕获声明异常、不生成只有标题的文件、不自动选最新声明。旧报告保留生成时原声明和结果。

独立行动规则继续核对真实个人档案、记录、目标和规则。来源解释仍须满足其指标 profile 的条件：例如 RHR profile 要求人群，声明失效时即使匹配了一条不带人群条件的主张，也不能因此绕过该 profile。测试同时验证这项限制和独立有效的数值规则。

从旧报告进入训练时使用当前真实会话、当前目标和当前查看范围；旧报告只是链接。W1／W4 的可选旧候选及反馈回调续算候选当前 W1，保留历史报告。旧事实、比较周期和分母不扩大，当前实际记录进入新对照和新报告。

## 17 项行为验收映射

下列用例均使用隔离合成私人库；`test_current_training_*.py` 位于 `tests/integration/`。

|合同场景|行为证据|
|---|---|
|1 已有计划自动建议|`test_real_template_region_free_record_next_training_and_joint_reports`：真实 app.py 选择模板、自动34档／计划7次／RIR2，无策略或采纳操作|
|2 部位入口|同一组合用例：chest 既有映射和计划导航；未选动作前无建议记录|
|3 无手工反馈|组合、服务与周月用例直接检查建议／反馈表保持为空，实际组进入下一次复核|
|4 保持原重量|`test_automatic_advice_permission_and_objective_actual_without_feedback`：实际30×11、RIR2，相对冻结参考+1；无拒绝推断|
|5 改重量次数／换动作|`test_multiple_actions_missing_record_and_replacement_keep_identity`：真实 replace_exercise、不同 UUID／任务不串建议|
|6 某动作无记录|同一多动作用例保留 `no_actual_record`；不写未执行|
|7 多组多版本|`test_multiset_versions_bind_by_identity_and_time_not_best_match`、`test_tied_advice_versions_keep_ambiguity_and_do_not_choose_closest_load`|
|8 重开／重复保存／修订删除|服务用例验证缓存不检索、原快照不变；`test_missing_time_rir_and_duplicate_event_preserve_unknowns` 验证事件重试、未知时间／RIR；`test_interleaved_inputs_refuse_stale_advice_and_actual_save_still_works` 验证三种并发写入|
|9 身体迟到|`test_late_body_changes_new_report_without_entering_original_advice`：新报告有SDNN，原建议与历史前瞻背景没有|
|10 近期未改善／全年改善|`test_recent_joint_review_uses_rir_and_body_despite_year_improvement`：300日前8次不遮蔽近期六次；实际5个RIR差、6场背景与SDNN中间变化参与|
|11 数值权限|`test_automatic_advice_permission_and_objective_actual_without_feedback`、`test_explicit_choice_condition_is_not_forged_for_automatic_options`：30/34/38档、许可及明确选择反例；生产能力另有只读核对|
|12 联合周月|完整页面组合和 `test_joint_report_body_values_sources_complete_days_and_new_task_page`：420分钟、61 bpm、41 ms、81 kg、VO₂42、4完整日／2000 kcal均值、来源日期与时间对应；两报告入口页面／下载一致|
|13 缺身体／只有身体|`test_frozen_joint_report_has_current_body_and_training_not_only_old_periods`、`test_normal_draft_reads_body_without_long_review_or_fake_records`|
|14 新任务／无本期训练但有旧反馈|普通非参考动作真实分析页不崩溃；`test_joint_report_without_current_actuals_keeps_manual_feedback_separate` 保留原反馈与分母；旧四项修复的任务隔离回归继续运行|
|15 跨周月旧报告→当前训练|`test_old_report_link_keeps_current_actuals_out_of_old_snapshot`：缓存来源链接、当前14日范围、本期实际及历史不变；既有四项／六项时间回归|
|16 声明撤回替换|`test_real_report_buttons_after_retirement`：两真实按钮；`test_joint_report_retirement_blocks_dependent_claim_but_keeps_independent_action_authority`（knowledge目录）：实际检索的正反权限|
|17 完整组合|真实部位／模板→自动建议→自由实际→下一训练→两入口周月导出；无需手工反馈；服务故障补充 `test_real_page_saves_actuals_during_evidence_failure_and_recovers`|

## 旧断言的明确调整

|原断言|调整原因|新断言／保留兼容|
|---|---|---|
|`test_candidate_from_calendar_trend_keeps_complete_comparison_bounds` 要求当前候选沿用旧 W4 完整周期|本轮要求旧报告只作链接、当前训练使用当前范围|改为 `test_candidate_from_calendar_trend_uses_current_action_window`，同时检查旧报告起止不变、当前截止和窗口更新|
|`test_historical_report_current_action_keeps_bounds_and_current_targets` 要求 W1 使用旧报告起止|同上；当前记录不能被旧窗口排除|改为 `test_historical_report_current_action_separates_bounds_and_current_targets`，核对当前目标、任务、范围、原快照与跨周月边界|
|旧训练 AppTest 初次30秒、后续默认3秒|自动建议新增真实服务计算，默认3秒不是业务合同|helper 将所有 run 默认设为30秒；未删除科学、权限、数据或界面断言|

原明确反馈正反例、采纳率分母、历史读取和 W1/W4 可选反馈回归继续保留。未跳过失败用例来达成通过。

## 实际生产规则能力

只读打开现有 SourceLibrary／TheoryLibrary（SQLite `mode=ro`），以合成私人记录调用既有权限与 STR-25/26；没有打开真实健康库、修改生产规则或重新检索评测。结果见 [生产规则核对元数据](../artifacts/analysis-core/current-training-production-rules.json)。

- `CORE-F2-DOUBLE-PROGRESSION@1.4.3`：STR-25。适用资料满足，参考达到用户计划上沿、RIR／质量符合且存在真实更难档位时，允许具体可选数值。
- `CORE-F2-LOAD-REPS-TRIAL@1.4.3` 与 `CORE-F3-STRATEGY-REVIEW@1.4.3`：STR-26。允许更难档位／较低次数的可选试验；次数必须来自实际计划下限且低于参考次数。
- `CORE-F2-REPETITION-TRIAL@1.4.3` 与上述策略复核规则：STR-26。允许维持实际参考负荷、采用用户计划中高于已观察次数的上限。

四条规则引用 `CORE-CLAIM-PROGRESSION@1.4.3` 及已登记 S1 证据，审核身份仍为 AI 辅助，权限没有升级为独立专家背书或个人效果验证。适用条件包括实际自报年龄／健康范围／训练目标／经验；记录、协议、质量、症状和目标另外通过原科学服务核对。

只读实跑中，合成30×10、RIR2、计划8–12、档位30/34/38在条件满足时分别产生34×8和30×12选项；未达到上沿时STR-25不给加重，达到12次后才产生34×8；缺适用档案时均无数值。这里的数值是输入结果，不是生产常量，也不是用户本人的建议。

睡眠、心率、SDNN、体重等首先是记录事实；来源解释按实际检索与 profile 条件逐项开放，不能因有数据而宣称解释充分。它们不直接映射成公斤、恢复百分比或确定因果。资料缺项、参考协议不全、未知目标／档位、要求用户主动选择而实际没有等情况继续受限，显示事实和具体核对入口。

## 最终验证与发布

开发期完整定向回归 144 项通过，缓存并发边界补充 1 项通过。首次隔离整仓完整执行为 **1814 passed、1 failed（1124.18 秒）**，Ruff 通过；唯一失败是无额外选择声明时漏存旧分析入口需要的完整周期快照，已通过既有适配器补回保存，原测试断言不变。隔离修复副本的周期及声明报告回归 **16 passed（66.26 秒）**。未中断首轮、未跳过失败测试；最终代码另建隔离副本重验，结果以新回执为准。旧工件保持历史身份。本轮只提交代码、文档、公开规则元数据及合成验收回执，不提交五份原有未跟踪 PDF、私人数据库、真实报告、受限全文或密钥。

最终隔离重验完整执行 `PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q`：**1815 passed、0 failed、0 skipped、0 warnings，1126.41 秒，退出码 0**。既定 `ruff check src tests app.py tools/analysis_core*.py` 通过，退出码 0。两次整仓均完整结束，首轮失败与修复记录保留。

308 份代码、测试、配置、合成夹具和规范输入在最终受验副本与主工作区逐文件哈希一致；清单 SHA256：`ac4a126006c2ddd27d4e45db7636392f295e0b301937f650f079642516697f03`。新回执见 [current-training-verification.json](../artifacts/analysis-core/current-training-verification.json)，包含实际命令、环境、计数、日志哈希及输入清单；旧回执不覆盖。

本轮软件验收完成：无手工反馈的真实页面全流程、下一次建议更新、两入口的身体—力量联合周/月报告、撤回声明受限导出、旧反馈兼容与原始记录故障恢复均通过。本结论不表示个人最优训练处方、因果确证、真人校准或真实干预效果已验证。
