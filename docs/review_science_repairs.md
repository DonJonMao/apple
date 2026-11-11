# 发布后科学与分析链路修复：R01、R02、R10–R14

基线是 `0a943b49638247e16197cf7fa768cde33f5d0901`。本轮先新增复现用例并运行：`tests/science/test_review_repairs.py` 与 `tests/integration/test_review_analysis.py` 的最初 7 项用例全部失败，见 `artifacts/review/science-baseline.xml`。XML 只清理机器名及临时目录等环境元数据，保留断言与失败结果。修复后的计算版本为 `healthzip-science-1.3.1`，应用分析快照版本为 `healthzip-v1.3.1`；历史冻结快照不改写。

机器可读逐项结果与工件哈希见 [science-results.json](../artifacts/review/science-results.json)。科学/导入/分析回归为 313 passed；真实训练页面的 R01/R02 确认为 2 passed；最后 R10 显示绑定修复另有 2 passed 的 AppTest。完整仓库最终证据以根任务的项目 `.venv` 全量回归为准，不把这些分项数量代替功能闭环。

所有复现都使用合成记录、临时 Repository 或临时 XML/CSV。测试不读取私人数据库，不把合成理论审核当作专业审阅。原 `artifacts/demo/`、`artifacts/science/` 是前版验收证据；本次回归证据位于 `artifacts/review/`。新版演示命令及产物见本文件末尾。

## R01：按测量任务保留每动作参考

**触发与原因。** 三场训练，每场两个动作各指定一个参考组。旧 `reference_rows` 只按 session_id 分组，认为每场两个参考互相冲突，6 条记录变成 0 条；单独分会话又会把不同动作混成一个趋势。

**改动。** `science/semantics.py` 定义动作/物理条件/结构化协议与真实参考位置组成的 task_id；`science/strength.py` 在任务内按会话唯一选择参考。`science/engine.py` 按任务分别执行参考表现、频率、趋势与候选指标。`analytics/v13.analyze()` 返回 `strength_tasks[]`，每项包含动作、条件、协议身份、数据哈希及自己的 MetricResult；`ui/analysis_page.py` 展示每任务样本与趋势。多任务的主 MetricResult 提供 `task_results`，不再把跨动作冲突当作全部动作的数据不足。

STR-15 的同场后续组变化仍读取全部有效工作组，不能被仅参考组任务覆盖。STR-08 频率与 STR-07 同样分任务。固定负荷趋势显式检查原输入单位；50 kg 与 50 lb 不以相同数字混算，也不进行未经用户确认的统一转换。

**真实入口与结果。** `test_r01_default_repository_analysis_has_independent_action_tasks` 通过真实服务记录两动作、三场训练，默认分析分别得到 3 条参考、3 个独立场次及非空斜率。`test_multiaction_ui_history_reaches_default_analysis` 从空库通过真实 Streamlit 控件建两个通用动作的模板、每场预指定并完成参考组，验证同一默认接口。不是从 context JSON 直接造任务。

**回归。** 包括同场多动作、协议未知、原单位不一致，以及“一个参考组+两个普通后续组”仍保留 3 条组内变化。描述性斜率不等于个人有效预测或正式停滞。

## R02：页面、存储和科学模块使用同一协议

**触发与原因。** 原页面只写 reference_protocol 文本，科学模块需要隐藏的结构化规则；正常用户三场记录虽能显示参考向量，却无法进入趋势。

**改动。** 与训练模块约定 `condition.reference_protocol={protocol_id,version,reference_policy_id,effort_protocol,tempo,rest_protocol}`。六项均由普通页面明确填写，真实组位置仍取持久化 set_number。自由文本迁到 `reference_protocol_note`，不填充未知规则。适配器展开为 reference_protocol_id/reference_protocol_version 等可比字段；协议版本与定义一起冻结，并参与任务身份。字符串、null 和空字段不会通过完整性检查。

**真实入口与结果。** `test_r02_three_sessions_from_page_produce_protocol_identified_trend` 纯 AppTest 建模板、填写六字段、记录同负荷 6/7/8 次的三场预指定参考。默认分析得到一个完整协议任务、3 条参考及描述性斜率。单次或未知协议不自动获得可比趋势。测试 helper 只操作可见控件，没有在后台补隐藏字段。

**文件与回归。** 页面/存储见 `docs/review_training_repairs.md`；科学侧是 `science/semantics.py`、`strength.py`、`engine.py`。版本差异与旧文本保持未知均有回归。

## R10：登记预算控制实际查看的区间

**触发与原因。** 首次 family 总预算 0.05 分配 alpha=0.025，但旧 STR-20 仍读取旁路顶层 alpha_look 默认 0.05，输出 95% 区间；非空 allocation 未证明区间真的消费登记值。

**改动。** ParameterRegistry 的不可变查看记录增加绑定：family、metric、task、数据版本、实际输入与窗口/截止哈希。`verified_look` 从本地登记库只读核对原记录、协议成员、首次登记时间、预算公式及完整 receipt；上下文中的手工 alpha 不生效。STR-20/22 使用唯一核验后的 alpha，STR-24 核验同一记录。未登记时保留 STR-19 描述性点估计，区间为空；缺少真人校准仍不能确认停滞。

**真实入口与结果。** `analytics.v13.view_task_interval` 由分析页“登记本次查看并计算”按钮调用。页面显示共享 family 和总预算，首次查看 0.025→97.5%；相同任务/指标/快照重看复用 receipt。真实组记录更正后绑定新数据版本，下一次为 0.05/6→99.1667%。每次重绘默认分析会移动系统 cutoff，因此页面明确冻结当前查看快照；相同输入、数据版本与日历窗口的普通重绘不会消耗另一笔预算。

**回归。** `test_r10_actual_analysis_view_registers_and_consumes_budget` 使用真实 Repository 和 AppTest，且每次渲染都重新计算动态 cutoff，验证上述首次/重复/更正链路。专属科学测试篡改 alpha、数据版本及旁路 alpha，验证拒绝或不生效；STR-24 与实际区间的身份一致。预算有效不代表单次模型的误差假设已成立，原自相关覆盖失败证据仍保留。

分析快照显式记录 `cutoff_mode=auto/explicit`：只有自动当前时间的同一输入/日历窗口重绘可以复用冻结截止；用户或调用者明确指定截止时，完整 start/end/cutoff 参与绑定，同日相差一分钟也不是同一查看快照。显示区间同时匹配当前 family、总预算、任务、指标、数据版本、窗口输入哈希与 cutoff；切换家族/预算/显式窗口会隐藏先前结果。两个实际 AppTest 覆盖家族切换、预算切换与同日明确截止变化，证据另列 `science-look-binding.xml`。

## R11：窗口累计与每日均值分开

**触发与原因。** 真实 Apple XML 导入两天各 basal1600、active600，旧主指标输出 4400 kcal/day；实际是窗口累计。

**改动。** `science/energy.py` 的设备 basal/active/total 累计统一输出 `unit=kcal` 与明确 aggregation 身份。日桶给日期、来源、组成分量、覆盖和完整性；可配对流另列 complete_days 与 valid_day_mean_kcal_day。有效日均明确使用完整日分母，不能把窗口累计换个标签当日均。

**真实入口与结果。** `test_r11_imported_two_day_energy_cumulative_has_kcal_unit` 经临时 Apple ZIP→import_apple_zip→Repository→默认 analyze，验证累计 4400 kcal，完整日 2，日均 2200 kcal/day，basal/active 也为 kcal。

**回归与边界。** 日累计不推断真实 TEE，不叠加 workout，不加固定 TEF；没有完整日不发布完整日均。派生报告复用相同日桶，不再另算一套单位。

## R12：同日期、同来源、同观察区间才配对

**触发与原因。** 第一天只有 basal1600、第二天只有 active600；旧逻辑按整个查询窗口与设备键相同直接相加。

**改动。** `device_energy_days` 先按本地日期和来源分组，再核对组成分量的真实区间并集。不同日期、互不相交区间、冲突或跨日未知分摊均不构成已知总量。已配对部分与完整日区分。`science/reports.py` 复用同一结果；多个设备各给自己的汇总，顶层不把两台设备重复相加。

**真实入口与结果。** `test_r12_imported_disjoint_component_days_cannot_form_total` 的跨日分量得到 total=null/insufficient。`test_r12_same_date_disjoint_intervals_and_different_devices_are_not_pooled` 通过真实 XML 导入核对同日互不相交的两分量仍未知；两台完整设备分别输出 2200，报告显示两个流且不发布合并总量。

**文件与边界。** `science/energy.py`、`reports.py`。缺少一个分量不按 0 处理；跨边界样本不假设均匀速率来摊分。

## R13：主睡眠必须有片段，历史汇总另设序列

**触发与原因。** 三晚各 7 小时，旧主睡眠默认累计为 1260 分钟。partial 标签不能修正测量对象错误。

**改动。** `STATE-SLEEP-MAIN` 缺少明确 main_sleep_episode 时返回 null、`main_sleep_episode_not_declared`。明确片段需有效且不晚于截止；归属日期由明确提供值或已声明片段结束的本地日期记录。过去 24 小时仍使用自己的 24 小时区间，不依赖主睡眠判断。

报告历史序列用 `series_id=observed_sleep_by_wake_date`，标签明确“按结束日期汇总的已观察睡眠（未认定主睡眠）”；派生 series 的 metric_id 为 `sleep_observed_minutes_by_wake_date`，不是新增注册指标。`analytics/core.py` 的图表消费该序列并保留标签，不再把每日期所有 asleep 观察称为主睡眠。

**真实入口与结果。** `test_r13_imported_multiple_nights_require_explicit_main_episode` 通过真实 XML 导入得到 MAIN=null，历史序列分别为 420/420/420 分钟。已有显式片段、DST真实经过时长、重复来源和截止 24 小时测试继续覆盖原行为。

## R14：CSV 原始来源进入规范流身份

**触发与原因。** 合法带时区 CSV 的 scale_A=80 kg、次日 scale_B=90 kg；旧 adapter 未映射 source，落入全 None 来源键并输出 70 kg/week。

**改动。** `analytics/v13.snapshot` 将原始 source/source_bundle_id 映射为规范 source_name，保留原字段；`science/state.stream_key` 使用真实来源，设备与协议未知仍为 null。不把无来源的多条记录暗中认定为同一秤。每日观察、体重趋势和状态汇总均按同一来源身份分组。

**真实入口与结果。** `test_r14_real_measurement_csv_preserves_scale_source_streams` 直接调用实际 CSV importer，再默认分析，得到两个来源流，各一个日期，斜率均为 null。测试没有补写 CSV 中不存在的设备或协议字段。

**回归。** 原同来源合成日趋势夹具现在明确声明其合成 source，以验证真实时间算法；这不是给用户缺失来源补默认值。已知单位转换仍由导入规范执行，未知协议没有变成个人校准。

## 候选与反馈的相关回归

STR-25/26 的数值任务要求完整参考协议、明确原负荷单位及适用审核。heavier_lower_reps 的目标必须为正整数且低于参考次数，并有实际可用的更难档位（助力方向相反）。返回值显式携带 reference_set_id 和 load_unit，供建议冻结使用，不能从随后任意普通组借用单位。数值权限不足仍返回缺项，不伪造审核。

`_outcome` 将条件/质量的未知与已知不匹配分开：未知为 null、明确不匹配为 false。STR-27 只有明确执行、数值完整且质量/条件已知才能进入成功分母；未知质量不记为失败。真实服务保存候选→执行→反馈及后续质量更正的回归覆盖 null→false。UI 候选闭环由根任务的 `test_review_candidate_flow.py` 覆盖。

## 复现命令与证据边界

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/science tests/integration/test_review_analysis.py tests/integration/test_v13_analysis_adapter.py -q --junitxml=artifacts/review/science-regressions.xml
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_review_training_ui.py tests/integration/test_review_candidate_flow.py -q
PYTHONPATH=src .venv/bin/python tools/demo_v13.py --output artifacts/review/demo
.venv/bin/python -m ruff check src/healthzip/science src/healthzip/analytics/v13.py src/healthzip/analytics/core.py src/healthzip/ui/analysis_page.py tests/science tests/integration/test_review_analysis.py tools/demo_v13.py
```

`tools/demo_v13.py` 已使用与页面相同的结构化协议，正常命令继续通过；没有为了演示给科学函数注入不存在的协议或预算旁路。新产物与 0a943b4 历史证据分目录保存。

项目锁定环境为 `.venv`。另一次未使用项目环境的系统 Python UI 探测在 Streamlit 测试框架解析初始 selectbox 时失败（`'all' is not in list`），尚未进入业务流程，记录在 `science-ui-system-environment.xml`。它不替代项目环境的 UI 验收；生产判定使用项目 `.venv` 的专属和全量回归。

软件实现及软件回归是本文件报告的完成维度。语料取得、独立专业审阅、真人预测校准和个人干预有效性仍由各自证据决定；本次修复没有升级这些状态，也没有增加固定百分比减量或加权准备分。
