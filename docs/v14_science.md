# v1.4 科学与单位合同审计

本轮以 `912aefc93b9bd9c1cebf297a10728c69c827e266` 与 v1.4 执行包的 77 项矩阵为基线，逐项阅读并核对 65 项非 QAL 指标。机器可读追踪见 [metric_audit_65.json](../artifacts/v14/science/metric_audit_65.json)：每项列出要求、实现文件、已执行的软件测试、运行单位与验证边界。QAL、知识主张审阅、最终页面验收由相应工作分支汇总。

本批原计划分项目标、RIR区间及睡眠/as-of修订合同改动后，科学算法版本提升为 `healthzip-science-1.4.1`，上层分析与缓存分别为 `healthzip-v1.4.1`、`analysis-cache-v1.4.1`。旧计算快照保持原版本；新版本使旧缓存失效，最终整仓验证记录新版本，先行失败/定点验证工件保留当时身份。

## 已修复的计算行为

- **F01 单位**：静息/活动/饮食能量共用 kJ→kcal；SDNN 支持 s→ms。未知单位不再把原数字重标为规范数字。原值、原单位保留；`quantity_value()` 统一检查单位并输出转换身份、`healthzip-units-1.4` 版本。旧错标记录只在原值与原单位足以验证时重新计算，并标注 `reprocessed_from_raw`；没有原始依据的 unverified 数据不进入聚合。STATE、BODY、ENERGY、报告使用此入口，结果带排除原因与数值来源。ENERGY 三项注册表主单位与运行结果统一为累计 `kcal`，日均字段单列。
- **F02 日期域**：睡眠覆盖率以裁剪后的半开时间支持建立当地日期集合；UTC、上海、纽约春秋 DST、午夜端点与 ±1 微秒都有反例。报告和能量覆盖率与窗口日期域相交。无观察的覆盖率保持未知。`evaluate_all()` 将单指标合同错误返回为 `not_applicable`、`metric_execution_failed` 与错误详情，独立指标仍计算；直接 `evaluate()` 继续明确拒绝无效合同。
- **F09 睡眠来源**：先选实际 asleep 相关流，inBed-only 或 awake-only 来源不阻断 Watch 睡眠；两个真实 asleep 流仍要求明确主来源。分期只使用选定流，分期冲突保留。观察睡眠不被称为已确认的主睡眠或完整夜晚。
- **F03/F04 候选适用性**：共享 `candidate_applicability(reference, current_observations)` 返回 `true/false/null`；参考与当前记录的停止原因、质量、显式疼痛与症状分别留痕。明确受限拒绝更难数字任务，缺项返回未知；SQLite 明确 0/1 可还原布尔值，None 不默认无痛。未能验证当前观察时间的记录也不能作为“空列表”消失后放行。STR25/26 结果附 `candidate_applicability`。知识规则权限与此检查是不同的必要条件。
- **F07 指标序列**：保留物理 `task_id`；STR19/20/22/24 按可审计负荷、口径、单位、协议、观察段建立 `outcome_series_id`，通过 `series_results` 返回每层样本数、来源、真实跨度与快照。单层保留既有 `value` 结构；多层各自计算，不用 e1RM 桥接。已知 kg/lb 精确归一，未知协议、质量、单位明确排除。STR13 保留跨负荷同次数比较；STR12/14 保留同层比较；STR07/08/29 分别展示参考暴露、记录场次和可比覆盖。
- **F08 范围门控**：校准工件须声明 `required_scope`，逐项检查已知与相等，额外审计字段不改变权限。实际动作、协议、单位、系列从记录派生，不让调用方标签覆盖；人群须有可追溯的上下文。STR21/22 共用等效界限单位、有限数值、声明时间和来源验证。没有真实适用校准，仍只能描述或研究，不能正式宣称停滞或已验证个人预测。

## 全矩阵审计补充修复

矩阵核对额外建立了失败反例并修复：STR18 跨任务/负荷重测配对、零观察误差的解释边界；STR30 缺体重来源及分子单位；ENERGY-IDENTIFIABILITY 仅凭布尔输入就宣称可识别；能量情景中单个倒序边界被另一个范围掩盖；包含休息的 elapsed 时长错误扣暂停；STR27/28 反馈重复计数及缺少策略/任务/规则版本分层。研究公式、日内等权、未知分母、可见修订和既有因果/校准边界继续回归。

`STR-30` 的有效分母通过 `context.body_mass_observation` 提供，含 canonical_type、原值或规范值及单位、来源、event_end、available_at；分子显式使用 `strength_numerator_unit='kg'`。单独一个无来源的 `body_mass_kg` 不再构成完整事实。

## 接口与集成

`discuss_sets` / `discuss_interval` 现在通过独立的一般解释路径工作：明确选择主题后，在核心分区核对实际可用的已审来源，冻结说明、逐主张引用、目标版本与同条件记录；训练间隔指场次分布，不混同组间休息。页面显示明确计划的工作组、历史工作父组数、已记录场次起点间隔和可选用户时间约束。最近365天只是产品观察窗口，未记录训练保持未知，不能据此估算个人最佳组数或恢复天数。

一般讨论不需要数值候选权限，也不产生数值任务、成功概率或个人处方；当前疼痛/未知仍保留在数值任务限制里。来源撤回后当前使用须复核，冻结记录不改；无可用解释时保留实际事实并明确缺项。讨论不能经“修改后采用”升级为数值任务。`test_v14_bounded_discussions.py` 的真实Service/页面冻结、采纳反馈、重开、撤回及负面测试已通过；修前4失败与修后12通过分别存于 `bounded-discussions-failing-before.xml` 和 `bounded-discussions-verification.xml`，均为隔离合成输入，不是个人训练效果验证。

`context.current_session_observations` 为当前相关训练事实；候选结果的 `reference_record_ids` 和 `current_session_record_ids` 分开保存。根集成负责 AdviceContext、冻结后使用状态与页面行为。

`MetricResult.series_results[]` 提供 `outcome_series_id`、`task_id`、`normalized_load`、`normalized_unit`、`load_basis`、`outcome_unit`、`observation_segment`、`source_record_ids`、`first_observed_at`、`last_observed_at`、`data_snapshot_hash`、`input_data_hash` 与内层 `metric`。`context.outcome_series_id` 选择单层，`series_contexts[id]` 提供该层上下文。新页面登记 `allocate_look(..., outcome_series_id=...)` 后由相同系列核验，换负荷或截止时间不能复用旧 receipt。旧单层调用的既有 receipt 兼容，但新集成必须显式绑定系列。

STR28 `strata` 按 strategy/task_id/rule_versions 保存分母与未知；缺元数据保留空值，不编造分层身份。多次反馈以候选身份选择 cutoff 前最新可见记录。

2026-11-12 的完成审计发现：原 STR27/28 只输出执行类别与成功计数，REPORT-RECOMMENDATION-FOLLOWUP 的 `followup_windows` 没有生产者，未实现矩阵要求的原始观察差值。修前合成复现保存在 `artifacts/v14/science/followup-gap-before-20261112.json`，没有以空因果字段或旧通过用例替代完成证据。

现在候选表单可在保存前声明带时区的后续起止时间，冻结为 `followup_window={start,end,timezone,closure,origin,declared_at}`；起点不得早于候选创建，使用半开区间，未声明保持空值。原有字符串窗口保留可读，但不当作预先声明。Repository 的截止前可见修订同时提供执行参考、冻结目标逐项比较和后续场次参考。报告显示目标、实做、单位、负荷口径及相对目标上下界的差值；kg/lb 在明确口径下精确换算并保留原录值与转换身份，不可换算时保持未知。区间 RIR 不改写成点值。

后续记录须在用户窗口内、晚于执行且来自另一场次；条件、协议、负荷层和有效参考资格匹配才给出观察差值，换器械、换负荷与质量问题列出排除原因。未执行、部分或未知执行、窗口待观察、已观察及窗口结束无可比记录分别计数；采纳、明确执行及完整目标结果使用各自分母。跨月候选按 `predeclared_followup_overlap` 明确进入窗口重叠的报告，未伪造新的事件时间。新修订或删除只影响相应可见截止时点；较晚派生快照不能复用到较早截止点。`causal_effect` 始终为空，完成或后续改善不代表策略导致改善。

上述随访语义首次发布使用 `healthzip-science-1.4.2`、`healthzip-v1.4.2` 和 `analysis-cache-v1.4.2`，旧冻结结果及旧验证工件保持原身份。实际 Repository 与页面验证见 `tests/integration/test_v14_followup_report.py`、`followup-final-tests-20261112.xml`（220项相关回归）及其后单位一致性补充 `followup-units-final-tests-20261112.xml`（17项）；前后结果见 `followup-completion-after-20261112.json`、`followup-unit-conversion-20261112.json`。这些均为实现作者的合成软件证据，独立科学验证分母为0。

知识原则的 `permitted_actions` 与用户请求动作取交集；STR25 必须显式有 `double_progression`，STR26 必须有对应的具体动作。缺失字段不继承宽泛 capability 的全部权限；每个输出动作列出对应规则版本。隔离正例明确声明测试动作许可，不修改生产规则的审阅事实。

获许可的 `repetition_progression` 使用 `progression_plan.rep_upper`：它必须是用户明确给出的正整数且高于已观察参考次数；同负荷候选保留参考负荷（`observed`）并使用该上沿次数（`user_target`）。无上沿、目标已达到、分数次数或受限/未知适用性只返回缺项/无需新增目标的理由，不默认加一次，不保证完成。

STR25 在数值比较前验证完整目标：次数上沿与下一任务次数须为正整数，下一次数不高于上沿，RIR 两端须完整、有限、有序且位于 0–10，器械档位须为有限非负数列表。部分目标正常冻结为 `insufficient`，不崩溃、不生成缺次数终点的负荷任务。STR26 的用户试验可明确只指定负荷与次数；两端 RIR 均缺失时保留 `target_rir_range=null`、`effort_target_status=unspecified` 并说明不属于已匹配努力目标。只填一个 RIR 端点或范围非法则阻止数值试验；不从历史 RIR 猜测用户目标。SQLite 文本数值经验证后作为数值输出，原始记录不改写。

STR09 保留原计划组完成率，同时新增 `target_attainment.load/reps/rir`，逐项报告达成、未达成、已知、未知、无目标数、已知目标比例，以及相对全部已声明目标的已观察达成比例。每项保留逐计划组原目标、实际值、状态和原因，不生成总分。只消费训练开始事件的原始目标，修改当组目标或模板不会降低原计划分母或原目标。负荷是指定口径下的计划数值匹配，复用明确kg/lb转换；助力增加按更容易记录，不能把更大数字视为达成。目标缺单位/口径保持未知；页面未声明负荷目标时为无目标，不从实际重量或器械档位反填。RIR区间完全落入目标范围才达成、完全不相交才未达成，部分重叠仍未知。

明确跳过与缺记录分开。STR09只在冻结原计划所属会话有明确窗口归属、且状态修订在截止前可用时保留无实际端点的计划状态；不伪造组执行时间，未来可用、窗外计划、身份不符和已删除/更正旧状态均不借此恢复。draft/in_progress中的已录数字可显示 `observed_match`，最终达成仍未知；aborted保留实际终点匹配，但不增加已完成组数，因此单项匹配不表示整组完成。真实页面跳过、Service→snapshot→指标、原计划版本、单位、助力与RIR区间由 `test_v14_plan_target_attainment.py` 的28例覆盖；修前13个缺终点结果失败和3个无端点状态接线失败分别见 `str09-targets-before.xml`、`str09-plan-status-before.xml`，相关回归281项通过见 `str09-targets-verification.xml`。

最终边界复核另修复原计划含热身组的情况：STR09按原计划中的全部组计完成与额外组，已完成热身不能因不是工作组而变成未知。判定仅限STR09，STR01等工作组统计仍保留原筛选。混合warmup/work模板→实际记录→分析的新增反例与129项定点回归见 `str09-warmup-before.xml`、`str09-warmup-verification.xml`；此前28例/281项工件仍保留原执行身份。

周/月入口使用各自 `period_result.strength_tasks` 的负荷层显示来源数、有效参考、实际起止时间、kg 或器械单位、点趋势及未确认的停滞状态。`test_v14_period_review.py` 通过真实 TrainingService 和页面周期按钮检查：同月每层 3 条、当周每层 2 条，月外历史与截止后记录不进入本周期，界面数值与持久化报告来源集合一致。

补充矩阵复核修复：STR07/08 的观察日期按所选时区计数，同一个当地日跨 UTC 午夜的两场不能伪装为多日频率；STR20 缺少正式 look 时仍在 `point_estimate` 保留描述斜率、变化、观察跨度和单位，区间保持未知；STR15 使用规范负荷变化比较同场任务，30 kg 与 30 lb 不当作同负荷，而已知精确等价 kg/lb 可以描述。周期覆盖同时提供去重的 `daily_coverage` 和各来源/协议独立的 `daily_stream_coverage`，未记录日期不等于事件未发生。

STR05/06 的历史映射要求改为实际逐组合同：只消费 `reviewed_anatomy_snapshot`，不再把当前 `context.muscle_mappings` 应用到旧记录。快照保存 mapping_id/version、动作 ID/定义版本、direct/indirect 标签、已记录的审阅人与来源引用，以及带时区的 reviewed_at/frozen_at；校验 `reviewed_at ≤ frozen_at ≤ available_at`。不同版本分别汇总，输出逐组绑定哈希及来源；同版本内容冲突拒绝。没有快照的旧记录保持未知。来源导航标签和批准的分析映射仍分开，软件仅校验输入合同，不声称自动认证审阅人身份或创造真实批准。

补充睡眠上下文审计修复了三条时间路径。`STATE-SLEEP-TIMING` 的显式 `sleep_episodes` 现在先按可用时间选可见修订，再按结束时刻落入半开窗口；缺 `available_at` 只能在明确回顾模式使用并标记，未来可用、窗外和被更正的旧会话不能进入。中点仍按真实时间跨度计算，原始带偏移的开始/结束时间、指定时区、来源ID及可用时间分别保留，计数域为睡眠会话。`STATE-SLEEP-STAGE` 指定主睡眠会话时先将分期支持裁剪到该会话，防止多夜分子除以单夜分母形成超过1的覆盖率。统一 `select_as_of` 将事件时间过滤放到最新可见修订之后：已知的未来时间更正、未知端点修订和无端点删除都使旧值失效；截止后才获知的修订不改变过去。

上述睡眠时间修复最初只通过科学API显式上下文接入；新增12个反例见 `sleep-context-before.xml`，修后与合同、既有指标验收、真实ZIP/Repository及建议时间路径的定点回归为274项通过，见 `sleep-context-regressions.xml`。既有中点/跨时区正例只补上显式合成来源ID和可用时间，原断言未放宽；迁移前3失败/259通过另留 `sleep-context-regressions-initial.xml`。这不构成主睡眠识别算法或设备睡眠分期的临床验证。

2026-11-12 对 `049d48b` 的普通入口复核另确认两项缺口：同日切换体重来源会沿用旧来源的匹配确认；睡眠主片段与时点指标虽有API，但普通页面无法声明片段。首次实际失败分别保存在 `reference-mass-confirmation-before.xml`、`sleep-selection-entry-before.xml`。前者现将确认绑定到具体分析快照、参考组和体重记录；改来源必须重新确认，B0仍可独立查看。

分析页新增「声明睡眠片段与主睡眠」：用户明确选择来源，逐晚填写带时区的起止和归属日期，再选择本次主睡眠，或留空只看逐晚边界中点。不会自动把多夜合并或最长片段标为主睡眠。声明保存真实 `declared_at/available_at`、来源记录ID及版本哈希，写入独立分析快照并可下载；原始睡眠资料不修改。来源修订、删除或不可见会使原选择失效，不用另一台设备补位。同一来源仍不重叠计晚；声明的当地日期须落在该片段所涉及日期。主睡眠的区间支持允许终点恰等于窗口终点；时点统计仍按片段结束时刻落入半开窗口，两个计数对象没有混用。

声明不得早于片段结束或所用来源可见时间。保存明确生成当前截止的新分析，保留原快照；若截止更新使旧片段不在新的滚动或周/月窗口内，页面保留旧结果并报告缺项。已有参考负荷/体重选择的上下文会随睡眠重算保留。主睡眠已观察时长仍为 `partial`，不把用户声明解释为整夜设备覆盖证明；边界中点不是实测入睡时间。来源切换、晚到修订、删除、重复片段、等界及±1微秒、旧月拒绝迁移、正常UI保存及参考选择串联由 `test_sleep_episode_selection.py` 等44项回归验证，见 `sleep-selection-reference-verification.xml`。新增来源修订夹具最初使用不存在的数据库列导致2失败/6通过，已按实际revision_id边界修正，诊断保留为 `sleep-selection-fixture-initial.xml`，没有改变业务断言。

本次新增入口使用 `healthzip-science-1.4.3`、`healthzip-v1.4.3`、`analysis-cache-v1.4.3`。完整限定审计及原始/公开诊断哈希见 `product-ui-completion-audit-20261112.json`。未新增专业审核、真人校准或独立科学验证。当次交付尚未核查训练事件与候选反馈的全历史重放性能；本轮后续查询与页面修复见下节，既有Apple数据规模基准仍不能代替训练事件测量。

最后的普通页面时钟复核发现睡眠草稿绑定了精确滚动起点，自动分析每分钟刷新会无提示清空已填声明。补充修前3个真实AppTest失败保留为 `sleep-draft-refresh-before.xml`。现以窗口模式、天数、周期、时区和所选来源建立稳定绑定；每个声明只重核实际支持源版本。正常跨分钟刷新及另一晚的无关修订保持声明时间和主睡眠选择；片段确实离开窗口或支持记录改变时明确提示并移除该声明，用户改窗口及周/月换期同样解释清除原因。5个刷新用例与原10个睡眠集成用例共15项通过，见 `sleep-draft-refresh-verification.xml`；前述44项工件保持原结果，未冒充覆盖这一新增边界。

实际服务将映射作为 `condition_json` 的独立冻结注释保存，不改变物理条件键。历史版本回归见 `test_v14_anatomy_history.py`：直接创建并持久化两个版本、较早 cutoff 回放、未知旧记录、另存模板及导出/导入后保留原快照。参数接口可显式采用已有审阅事实，没有自动批准生产肌肉映射。

## 组间休息讨论与有界训练支持

`discuss_rest`现接入同一普通候选/选择/反馈流程，并与组数、场次间隔讨论分开。当前组目标中的休息秒数标为用户计划，主动记录保留方法与原值，相邻端点派生保留前组身份、端点与缺项原因；不会从计划或主动记录反填缺失端点，也不会把派生间隔全部解释为纯休息。引用沿用实际可用的S1片段及`CORE-CLAIM-REST` 1.4.3，该历史阶段知识发布为1.4.13。真实核心库副本的普通页面核验分别展示计划180秒、主动115秒和端点120秒，这三个合成观察没有合并为建议值；原来源库未改。

一般解释不授予个人最佳秒数或数值成功目标。用户采纳并完成讨论后，STR27/28仍不能把它计作已证明有效的数值试验；来源撤回或端点修订不会改写当时冻结的讨论。7项新用例及49项相关回归、6项原始失败与实际核心库页面回执见`artifacts/v14/advice/rest-discussion-audit.json`。新增独立语义、人工专家审阅和个人效果验证分母均为0。

报告查询保留原始计划分母和显式依赖：可见训练事件仅重放一次，旧基线、实际执行ID和声明的随访窗口在需要时扩大支持范围。候选反馈只有创建/反馈落窗或预声明随访交叠时进入相应查询；最终结果仍执行原时间、修订、条件和质量合同。跨月随访中的原目标、执行差值、后续观察与未知分母不能因性能过滤而丢失。14项合法偏移格式反例在修前全部失败；规范SQL参数后通过，与其他窗口/随访路径的30项回归另存`training-offset-audit.json`，不是新的独立语义准确率。

带出上次值的候选表只是查询元数据。精确UTC微秒排序、可见性检查及逐批上界停止不生成个人预测，也不将未知测量条件当作可比。兼容P1同负荷计数由二次循环改为一次分组计数；普通分析复用窗口结果，历史分页保留全部场次的可访问性。源事件与当前表不删减、不抽样；SQLite索引精度补偿不放宽科学窗口。该历史查询阶段算法/分析/缓存分别标为`healthzip-science-1.4.4`、`healthzip-v1.4.4`、`analysis-cache-v1.4.4`，P1标为`p1-1.4.4`。已完成的失效记录还保留各自原分析版本：`mark_recomputed`只处理当前用户及截止ID内仍待处理的记录，重复完成不会重写历史版本；部分索引减少已经完成历史的扫描和写入。这是审计元数据一致性修复，不改变科学权限；有效修前3失败/1通过及修后4项定向通过单独记录在 [待重算完成审计](../artifacts/v14/performance/training-invalidation-audit.json)，初始4项夹具设置错误不算产品失败或通过。阶段2整仓1300项通过、231份输入哈希不变的原结果保留；随后百万实际力量页超过产品响应预算，阶段3增加最近30条操作事件的排序索引，UI查询/撤销行为及科学权限未变。阶段3最终整仓1304项通过、232份输入哈希不变；规模响应单独报告。完整运行身份见总验收及最终清单；这仍是软件验证，不增加独立语义、专家审阅或真人校准分母。阶段1的1259项通过和人工中止的百万测量保持原有范围，不能当作后续阶段的最终验收。

## 可复现证据与限制

首次反例为 `failing_before.xml`（29 failed / 5 passed），随后新增矩阵与单位注册表反例分别保存在 `extended_before.xml`、`registry_before.xml`、`matrix_gaps_before.xml`、`followup_before.xml`。最终结果见 `verification.xml`；环境路径与主机元数据已脱敏，失败结果未改成通过。

候选目标补充审计先记录 `failing_before_plan_validation.xml` 的 35 个失败，再在 `plan_validation.xml` 验证全部通过；包含真实页面依次清空次数上沿、RIR、次数下限并保存缺项的回归。

周期与矩阵补充反例分别见 `failing_before_period_review.xml`（4 个失败）、`failing_before_period_streams.xml`（1 个失败）和 `failing_before_within_session_units.xml`（2 个失败）；修复后纳入同一 `verification.xml`。

历史肌肉映射先行反例见 `failing_before_mapping_snapshots.xml`（2 个失败、9 个未知输入用例已通过）。它揭示当前 context 可覆盖历史标签，以及同一映射版本内容缺少冲突检查。修复后的正例与拒绝例同时验证逐组快照消费。

使用项目虚拟环境运行：

```sh
.venv/bin/python -m pytest -q tests/science tests/integration/test_v14_science_import.py tests/unit/test_normalize.py tests/integration/test_review_analysis.py tests/integration/test_v14_advice_flow.py tests/integration/test_v14_choice_validation.py tests/integration/test_v14_period_review.py tests/integration/test_v14_anatomy_history.py --junitxml=artifacts/v14/science/verification.xml
.venv/bin/python -m ruff check src/healthzip/science src/healthzip/normalize tests/science tests/integration/test_v14_science_import.py artifacts/v14/science/build_audit.py
.venv/bin/python artifacts/v14/science/build_audit.py
```

组合回归包含既有正式区间登记页面用例。这里的 ZIP 与 TrainingService 都走实际入口，但内容均为合成数据；没有读取、发布真实个人健康导出，没有创建真人校准制品，没有伪造人工或专家审阅。测试通过证明已指定输入下的软件行为，不证明个体生理效度、预测校准或训练因果收益。


2026-11-12本轮入口补齐：逐组计划编辑按冻结测量模式提供次数、时长或距离，并分开休息、负荷值/单位/口径和RIR；周/月普通页面直接呈现对应period_result的STR01母组/分段与STR09冻结计划执行状态及目标分项。未知与明确0分开，当前目标编辑不改实际数据或原冻结计划。修前9项新UI失败，修后10项新UI加48项邻近回归通过；这58项只是软件入口验证，见 [目标与周期入口审计](../artifacts/v14/product-entry-targets-period-audit.json)。该入口补齐阶段的计算算法为1.4.4，没有新增个人统计校准或科学有效性。


## 时长/距离的原计划目标核对（1.4.5）

STR09新增`duration_s`与`distance_m`端点，补齐普通页面能记录目标但复盘未展示达成情况的遗漏。明确标量目标按相等值核对，低于或高于均不自动算满足；未登记的min/max键不产生新范围合同。原计划与实际均须有匹配的冻结测量模式，缺失、未知或冲突保持未知，不从当前目录推断。离线计划组按开始时冻结的模板项恢复模式与动作版本。现有负荷、次数和RIR合同以及整组完成分母保留。

正常控件验收包括模板设三组目标30→将本次首组目标改12→记录12/30/40→结束→生成周/月复盘：原计划仍为30，已满足1、未满足2，整组完成3/3。修前28项全部失败；最终36新用例与277相关回归共313项通过。科学、分析、缓存、P1及端点合同版本均为1.4.5，旧快照不回写。证据见 [模式目标验收](../artifacts/v14/science/str09-mode-targets-evidence.json)。这是软件合同验证，不是训练效果或全部77指标的新增科学验收。
