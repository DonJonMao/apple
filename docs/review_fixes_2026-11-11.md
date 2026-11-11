# v1.3.1 推送后审查修复验收

审查日期：2026-11-11。固定审查基线：`0a943b49638247e16197cf7fa768cde33f5d0901`。本次针对 R01–R15 及 RAG 支持语义修复；以本文件和 `artifacts/review/` 的新证据为准。旧 `artifacts/demo/`、知识目录的 `visible_eval.json/holdout_eval.json`、`artifacts/verification/final-manifest.json` 是此前交付的历史快照；知识目录的两份 `*_latest_eval.json` 已按本次当前语料重新运行。

本次所有训练、Apple XML、CSV 和审核权限测试均使用合成数据及临时库。合成的“合格审核角色”只验证软件准入与闭环，不是真实专业审核；未改真实卡的解释权限来解锁数值候选。未加入固定减量百分比、加权准备度分数或专用动作/重量判断。

## 逐项验收表

以下测试均先确认相应错误，再验证修复；基线失败证据见 [训练基线](../artifacts/verification/review-training-baseline.xml)、[科学基线](../artifacts/review/science-baseline.xml)、[知识基线](../artifacts/review/knowledge_baseline.json)、[候选基线](../artifacts/review/candidate-baseline.json)。代码路径均相对 `src/healthzip/`。

|编号|触发条件与错误原因|改动与修复后结果|真实入口及回归证据|
|---|---|---|---|
|R01|同场多动作各预指定参考组，原实现按整个会话唯一参考而丢弃全部；跨动作趋势混算。|`science/strength.py`、`engine.py`、`semantics.py`、`analytics/v13.py`、`ui/analysis_page.py` 建立独立动作/物理条件/协议任务。|`test_multiaction_ui_history_reaches_default_analysis`：页面创建卧推与高脚杯深蹲模板，三场同场记录后默认分析两任务各3条参考及独立描述趋势。|
|R02|页面只写协议文本，科学模块要求结构化字段，正常入口无法生成可比协议。|`training/semantics.py`、`ui/training_page.py` 统一6个协议字段与版本，自由文本保留备注，未知不补齐。|`test_r02_three_sessions_from_page_produce_protocol_identified_trend`；候选E2E同时覆盖协议完整和未知。|
|R03|页面仅有STR-25上沿进阶，没有STR-26策略选择与冻结流程。|`ui/recommendation_page.py`、`science/strength.py` 连通策略、当前组目标、器械档位、适用依据、冻结、采纳、执行及复核。未到上沿可选择更难档位/降低次数试验，缺审核仍无数值候选。|`test_visible_candidate_task_end_to_end` 从实际模板/临时训练控件开始，包含上沿进阶、未到上沿试验、无审核与未知协议；结束后实际反馈达到STR-27。|
|R04|当前/历史控件缓存旧值，却携新数据库revision保存全部字段，静默回退次数。|`ui/training_page.py` 绑定加载revision及字段快照；保存真实脏字段，清洁保存不写，过期脏字段进入冲突。|`test_r04_clean_history_save_cannot_revert_current_view`、`test_r04_dirty_history_keeps_loaded_revision_and_reports_conflict`：双视图、重渲染、无意保存与脏备注。|
|R05|不可变审阅阻止撤销；修订新版本后旧版本仍approved并参与检索。|`knowledge/store.py`、`workbench.py`、`retrieval.py` 增加独立生命周期审计与supersedes；历史审批不改写，当前只用有效版本。|`test_r05_revocation_keeps_review_and_frozen_history_but_stops_current_use`、`test_r05_revision_activates_only_replacement_and_records_supersedes`。|
|R06|全文任意license节点可将单图CC许可扩大到主文。|`knowledge/rights.py`、`acquisition.py`、`store.py` 按文章、图表、补充、子文章作用域判断；冲突或范围不符待审，逐span门控。|`test_r06_component_license_never_licenses_the_parent_or_other_components` 及范围冲突参数化用例；旧解析许可须重新核对，保留原版本。|
|R07|改组目标只写set，建议与另存模板仍读旧instance计划。|`training/service.py` 增加 `current_targets()` 及内容版本；建议选明确组目标冻结，另存模板读取当前目标，原计划保留。|临时/模板目标变更、正常跳过保留目标、实际修订不改变目标版本；候选E2E冻结页面改后的6–8次目标。|
|R08|候选反馈只在未结束训练显示，结束后入口消失。|`ui/training_page.py`、`recommendation_page.py` 在历史已结束/中断训练展示候选、采纳、执行、实际组与复核结果。|`test_r08_feedback_remains_after_finishing_session`、候选完整E2E：正常结束后再反馈，冻结快照保持不变。|
|R09|仅重算编辑组；清除时间端点仍留旧休息，结束时间可能被自动补回。|`training/service.py`、`schema.py`、`exchange.py` 重派生相邻组，缺端点未知，记录派生来源与独立主动休息；依赖修订有审计。|前组结束后移120→60秒、清端点、删/撤销、旧截止时间、CSV主动休息往返；派生事件不能清除人工冲突。|
|R10|登记alpha在look_allocation，区间却读顶层alpha_look；存在登记被误当已消费。|`science/registry.py`、`strength.py`、`analytics/v13.py`、`ui/analysis_page.py` 从真实登记receipt消费同一alpha并验证家族/指标/任务/数据版本/hash/截止时间。|`test_r10_actual_analysis_view_registers_and_consumes_budget`：页面首看0.025→97.5%区间，同快照重看幂等，数据更正后消耗下一预算；伪造/错配拒绝。缺真人校准仍无正式停滞标签。|
|R11|窗口累计量继承kcal/day单位。|`science/energy.py` 明确窗口累计kcal、日桶和带完整日分母的日均。|`test_r11_imported_two_day_energy_cumulative_has_kcal_unit`：真实XML导入两天1600+600，累计4400kcal、有效日均2200kcal/day。|
|R12|不同日期/覆盖的basal和active仅按外层窗口拼成total。|`science/energy.py`、`reports.py` 同日期、流与支持区间配对；缺项、边界和冲突传播到总量与报告。|真实XML第一天只有basal、第二天只有active：总能量未知；同日不相交区间及不同设备不得拼成一组总量。|
|R13|缺main_sleep_episode时把窗口多晚总和标为主睡眠。|`science/state.py` 无明确片段返回缺项；有效片段裁剪且归属到日期，历史汇总独立。|`test_r13_imported_multiple_nights_require_explicit_main_episode`：真实三晚睡眠XML不再返回21小时主睡眠。|
|R14|体重CSV的source未映射流身份，不同秤被混成一条趋势。|`analytics/v13.py`、`science/state.py` 保留canonical来源身份并分段；未知来源与协议不伪造。|`test_r14_real_measurement_csv_preserves_scale_source_streams`：合法带时区CSV scale_A80、scale_B90，各只有1点，不能生成70kg/week共同趋势。|
|R15|record_version成功把corrected_pending_review重置acquired。|`knowledge/store.py` 分开获取与科学状态；更正事件与精确版本复核绑定，metadata成功不能释放旧全文，withdrawn不由重试解除。|普通重试、metadata更新、新全文、精确版本clearance及后续新更正状态转移回归。|
|RAG|词项命中和任意claim被标evidence_supported，即使未回答目标问题。|`knowledge/support.py`、`retrieval.py`、`evaluation.py` 分开相关阅读与目标答案支持；按目标、适用条件、证据关系与审核绑定，冲突不按排序裁定。|新增答案/证据案例在输出冻结后由非实现代理独立AI标注；固定来源家族留出集不改动、不用于调参。人工独立语义验收仍单列。|

详细触发、原因、文件和复现说明见 [训练修复](review_training_repairs.md)、[科学修复](review_science_repairs.md)、[知识修复](review_knowledge_repairs.md)。

## 独立复核追加的回归

- 参考组50kg、随后普通组110lb时，候选必须使用计算所选参考组的UUID与kg单位；页面不得从最后一条普通记录借用单位。已有真实UI回归覆盖。
- 任务数值满足但动作质量未填时，结果保持未知，不算失败、不进入成功率分母；明确技术不合格与未知分别处理。
- 目标集合不因实际跳过而丢组；派生休息的自动审计不能替代尚未解决的人工冲突决议。
- 参考任务分组不能删除组内下降计算需要的普通组；相同数字的kg/lb不得视为相同负荷。
- 区间页面切换分析家族、alpha、明确截止时刻或完整时间窗时，旧登记与旧区间立即失效，防止显示上一次选择的结果。

## 验证与五维状态

最终整仓pytest为 **476 passed，0失败、0错误、0跳过，203.81秒**。生产代码、测试及本次变更工具的Ruff、离线锁文件检查、wheel构建与隔离安装、中文手册PDF字形/文本/渲染检查均通过。命令、源码及证据哈希见 [最终验证清单](../artifacts/verification/review-final-manifest.json)。测试数量只表示已执行用例，功能验收以逐项真实链路与边界用例为准。

|维度|本次结论|
|---|---|
|软件实现|R01–R15和RAG支持状态语义按上述边界修复；功能2/3有可见策略与反馈流程，正式停滞/数值候选继续受协议、审核、预算和校准门控。|
|软件验证|真实AppTest、Repository、XML/CSV导入与状态转移回归；包括可生成候选与必须拒绝候选两类。最终运行结果见manifest。|
|语料覆盖|此前14来源全文收据保留；新许可作用域规则的本地重解析、可检索情况单独报告，获取数量不等于合格证据覆盖。|
|专业审阅|11张历史AI辅助解释卡已通过审计事件置为needs_review，当前有效approved为0；原审核保留，另9张仍为草稿。没有新增独立专家审核或数值候选权限，本轮合成审核仅用于软件测试。|
|科学验证|没有新增真人时间外预测、干预有效性或独立人工问答语义证据；研究校准仍为simulation_only。不能据测试通过宣称解除停滞或个人处方有效。|

新冻结的10例RAG独立AI审阅为7通过、3失败，门控为 `failed_independent_review`，独立人工分母为0。当前语料的开发集gold召回为0/67，固定留出为0/8；旧卡待审导致无法形成有效审核支持，不能将保守拒答称为语义准确性提升。失败详情保留在 [独立审阅结果](../artifacts/review/rag_semantics_independent_ai_results.json)。
