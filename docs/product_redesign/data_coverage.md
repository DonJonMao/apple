# 数据场景覆盖与升级说明

本页对应本轮 A02、A04–A08、A19，区分数据语义、Streamlit 控件和真实浏览器证据。所有夹具都是合成数据。数据专项 68 项通过；单位转换版本补齐后，单位/来源观察/查询计划 19 项补验通过。睡眠独立 24 小时窗口修正后的当前源码，数据合同/规范一致性/日历摘要 47 项补验通过。全量入口移除分钟缓存键后，数据合同/全量查询规划/睡眠草稿 33 项补验通过。完整项目测试及最后界面修正的结论由最终交付回执统一汇总，不能由这些专项数量推断全项目已通过。

## 需求覆盖

|场景|实现与已覆盖行为|可执行证据|浏览器证据与边界|
|---|---|---|---|
|A02 总览本周/本月|[摘要](../../src/healthzip/analytics/workspace_summary.py) 按当地日历生成本期与上期同期；[总览](../../src/healthzip/ui/overview.py) 卡片、图、发现只消费选中的同一 period。比较使用相同已过本地时长，前月更短时截在前月末；缺失不填零。整场未结束、空会话不能增加完成训练次数，明确完成的工作组独立统计。|[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_current_partial_period_compares_same_elapsed_time_and_empty_training_not_counted`；[日历摘要](../../tests/integration/test_workspace_calendar_summary.py) `test_strength_real_completed_draft_delete_and_undo`；[应用切页](../../tests/integration/test_workspace_switching.py) `test_overview_direct_training_counts_only_completed_facts`。|[桌面总览](../../artifacts/product_redesign/after/overview-1440.png)、[手机尺寸总览](../../artifacts/product_redesign/after/overview-390.png) 和 [Chromium 逐页几何回执](../../artifacts/product_redesign/after/browser-results.json)。同窗口数值切换另由真实 Streamlit AppTest 断言，不以截图代替数据断言。|
|A04 本月/近30天/时区跨日|[详情事实入口](../../src/healthzip/analytics/workspaces.py) `workspace_window` 是唯一边界来源。本周从当地周一零点，本月从月初，近30天为今天及前29个本地日期至实际截止；自定义为明确天数回看。`workspace_scope` 传给卡、图、结论、明细和解释。恰逢周期开始零点时返回空指标，不人为扩展上一日。|[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_month_thirty_days_and_calendar_midnight_have_exact_scopes`、`test_workspace_path_source_and_timezone_are_cache_dependencies`；[日历摘要](../../tests/integration/test_workspace_calendar_summary.py) `test_local_calendar_year_and_dst_boundaries`、`test_exact_calendar_start_is_empty_current_period`、`test_sleep_boundary_uses_canonical_interval_clipping_and_wake_date`；[页面摘要](../../tests/integration/test_workspace_summary_ui.py) `test_week_month_cards_trends_and_details_use_the_same_snapshot`。|健康详情截图显示实际起止日期；日界、跨年和 DST 以时区受控测试验证。浏览器量级基准中的新范围切换是交互计时，不代替这些边界断言。|
|A05 只有范围外旧 VO₂|[有氧入口](../../src/healthzip/analytics/workspaces.py) 只将本期 latest-visible 来源传给既有 `OBS-VO2-REPORTED`；旧观察放在 `latest_observations`，标记 `historical_reference_outside_selected_window`。体重页面不返回有氧数据，旧值不混入本期均值/趋势。|[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_vo2_old_points_are_only_historical_and_weight_has_no_vo2`；[详情控件](../../tests/unit/test_health_detail_redesign.py) `test_cardio_old_observation_is_only_a_dated_history_reference`、`test_cardio_and_weight_have_independent_cards_and_details`；[规范一致性](../../tests/integration/test_workspace_analysis_scope.py) 同来源、单位与范围断言。|[旧数据浏览器回执](../../artifacts/product_redesign/states-old/browser-results.json) 为9页×1440/390px真实 Chromium 检查，状态通过；[旧VO₂手机尺寸截图](../../artifacts/product_redesign/states-old/cardio-390.png) 显示所选范围无记录、实际历史日期及单独折叠的历史参考。数据值归属仍由前列行为测试核对。|
|A06 冷/热/跨分钟|[页面缓存](../../src/healthzip/analytics/cache.py) 有界、领域版本驱动、同键计算合并；心率不读取训练、推荐、主观日志或其他健康类型。自动键使用时区日期与实际窗口，去掉当前分钟；命中保留原实际截止。|[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_auto_cache_cross_minute_ttl_and_local_date`、`test_unrelated_catalog_and_source_edit_keep_heart_cache`、`test_same_key_concurrent_calls_merge_without_sharing_connections`；[日历摘要](../../tests/integration/test_workspace_calendar_summary.py) `test_hot_cache_does_not_read_sources_replay_training_or_evaluate`；[阶段与逐次基准](performance.md)。|[10万浏览器](../../artifacts/product_redesign/browser-performance-100k.json)、[百万浏览器](../../artifacts/product_redesign/browser-performance-1m.json) 各30次跨页热返回；首进程打开、运行中冷范围与服务端计时分列。跨分钟由 [生命周期](../../artifacts/product_redesign/backend-lifecycle.json) 和受控时钟测试验证。|
|A07 外进程导入/持写事务浏览|[app](../../app.py) 普通浏览不调用 `persist_analysis`；健康详情不初始化训练种子；总览用 `TrainingService(..., initialize=False)` 重用只读历史。新连接只读核对已迁移标记。模型解释用独立任务与独立连接，不占用页面查询连接。|[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_fresh_health_and_overview_are_read_only_under_external_writer`、`test_other_import_process_invalidates_committed_domain`；[应用切页](../../tests/integration/test_workspace_switching.py) `test_overview_and_health_reruns_are_readonly_while_writer_holds_lock`、`test_factual_workspaces_do_not_freeze_analysis_and_keep_context_warning`；[开库并发](../../tests/integration/test_repository_open_concurrency.py) 暖开库、并发升级锁后重查和取消回滚。|[生命周期](../../artifacts/product_redesign/backend-lifecycle.json) 记录另一连接持写锁时清缓存浏览、另一个 Python 进程通过真实 `insert_sample` 导入后重算的时延与修订变化。它是同机并发验证，不是远程网络测试。|
|A08 更正日期/类型/删除/撤销|[时态查询](../../src/healthzip/db/temporal_schema.py) 索引仅缩小候选身份，先选择截至 cutoff 的最新有效修订，再核对类型、时间及删除状态。触发器同时失效该记录曾属于的类型；历史 as-of 保留旧可见值。页脚最新日期也走最新可见修订，不从被删除旧版取“最新”。|[类型候选查询](../../tests/integration/test_typed_source_queries.py) `test_typed_candidate_uses_latest_visible_revision_before_final_filter`（类型/时间/删除＋恢复＋精确微秒）；[产品数据合同](../../tests/integration/test_product_data_contract.py) `test_domain_revision_invalidates_old_type_and_restoration`（再含可见时间修订）、`test_footer_latest_dates_resolve_tombstones_type_date_changes_and_asof`；[规范一致性](../../tests/integration/test_workspace_analysis_scope.py) `test_late_correction_preserves_prior_cutoff_and_new_view_updates`；训练删除/撤销见 A02。|修订与撤销由真实 SQLite/既有训练事件服务测试，不能仅用前端重新加载截图证明。跨进程持久版本已另测。|
|A19 空白/旧数据/单点/部分缺项|[详情呈现](../../src/healthzip/ui/body_pages.py) 不填演示值；有效来源继续显示，稀疏序列用真实点，无缺失日补线；历史体重和 VO₂ 有实际日期，首末变化只在同来源且至少两点时出现。睡眠非正/非有限观察不进展示分母，仍保留原科学结果。|[产品数据合同](../../tests/integration/test_product_data_contract.py) 空范围、旧VO₂、来源过滤历史体重；[身体控件](../../tests/unit/test_body_pages.py) `test_sleep_omits_zero_negative_missing_and_nonfinite_only_from_display_statistics`、`test_empty_weight_window_shows_actual_historical_date_and_can_expand`、`test_same_named_sources_with_different_conditions_are_still_separate`；[新详情控件](../../tests/unit/test_health_detail_redesign.py) `test_sparse_chart_has_only_real_points_and_no_line_across_missing_dates`、`test_vo2_same_name_different_protocol_is_never_merged`、`test_dense_chart_bound_preserves_brief_extreme_without_changing_statistics`。|[空白](../../artifacts/product_redesign/states-empty/browser-results.json)、[旧数据](../../artifacts/product_redesign/states-old/browser-results.json)、[单点](../../artifacts/product_redesign/states-single/browser-results.json) 均完成9页×1440/390px真实 Chromium 渲染/几何检查，无异常或横向溢出。已目视核对[空心率](../../artifacts/product_redesign/states-empty/heart-390.png)的导入入口、[单点心率](../../artifacts/product_redesign/states-single/heart-390.png)的真实点及[旧有氧](../../artifacts/product_redesign/states-old/cardio-390.png)的独立历史参考；缺项数值语义另由前列测试验证。|

固定过去 24 小时睡眠指标与 A04 的主页面范围明确区分：周初/月初查询会额外取齐该指标所需前一日睡眠，`workspace_scope.extra_metric_windows` 提供独立边界与展示标签，使用它的解释旁标注“过去24小时（独立于所选范围）”。主卡、逐日趋势、明细及本期最近观测仍只用所选页面范围。数据合同中的 `test_sleep_fixed_24h_dependency_does_not_change_page_calendar_facts` 对周初和月初各验证一次，避免固定科学指标错误截短，也避免旧睡眠混入本期事实。

## 数据升级与兼容

|项目|本轮变化|已有数据的处理|
|---|---|---|
|根数据版本|`CURRENT_SCHEMA_VERSION` 保持5；`REPOSITORY_MIGRATION_REVISION` 升为3。|已就绪连接不触发写事务；缺迁移标记的旧库走原原子升级路径，更高版本仍拒绝降级。|
|时态查询投影|`QUERY_PROJECTION_VERSION=4.5`，新增 `source_revision_type_window` 类型/事件边界/记录身份复合索引。|从4.3/4.4仅追加新索引和触发器，原台账 payload 字节不改写，已有通用事件索引保留；无需清库或重新导入。|
|迁移成本|10万库约0.66秒、百万库约6.29秒。|这是首次增量升级；重复开库按标记跳过。耗时和磁盘增量见 [性能报告](performance.md)，不将一次性迁移计入日常冷访问并掩盖。|
|来源领域版本|`schema_meta` 的 `source_domain:<table>:<type>` 和通配 `*` 键，由来源修订 INSERT/UPDATE/DELETE 触发器维护。|同一记录历史所属类型都会失效，避免改类型后旧页面继续命中；跨进程修改无需通知本进程，无需新缓存服务。|
|普通页面计算|心率/睡眠/体重/有氧只读取必需来源；运动使用有修订身份的 Workout 记录，未版本化附表不冒充历史字段。|全套77指标、流式导入、同步增量去重、修订台账与旧报告仍保留。全历史运动 inventory API 保留其原用途，日常页面改用统一范围快照。|
|训练只读构造|`TrainingService(..., initialize=False)` 供已经由 Repository 完成表结构迁移的纯读取使用。|默认构造行为不变；开始训练等写操作继续原服务初始化/种子/事件机制，不制造第二套事实表。|
|单位转换|`healthzip-units-1.4.1` 增加 VO₂ 数学等价单位字符串 `mL/(kg*min)`。|原始数值、原始单位和转换依据保留；旧冻结结果不回写，不增加科学阈值或换算用户训练负荷口径。|

升级事务、保留台账与幂等验证见 [类型查询迁移测试](../../tests/integration/test_typed_source_queries.py) `test_existing_43_upgrade_is_additive_and_preserves_ledger_bytes` 和 [Repository 并发测试](../../tests/integration/test_repository_open_concurrency.py)。

## 缓存与配置

页面事实缓存上限16项，安全 TTL 为300秒。键包含数据库解析路径及文件身份、相关持久修订、工作区/指标集合、所选范围、时区、来源筛选和算法版本。自动范围以用户时区本地日期更新；用户显式历史 cutoff 以精确时间区分。训练目录编辑不会失效心率，相关源修改立即失效。无提交事务中的结果不共享；重复计算请求合并，等待线程使用自己的连接，不跨线程共享 SQLite 连接。

可选复盘的完整科学入口 `v13.analyze` 和 `core.all_analysis` 同样移除分钟键，使用本地日期和300秒 TTL；它们继续按完整输入与知识修订失效。缓存仍携带原真实计算截止，显式 as-of 不随自动时钟过期。产品数据合同的 `test_full_analysis_auto_cache_retains_cutoff_until_ttl_revision_or_local_date` 对两个入口分别验证实际行为；`test_full_analysis_explicit_cutoff_does_not_expire_with_automatic_clock` 保留精确历史身份，睡眠草稿测试继续验证范围离开与修订时的正确恢复。

这套事实缓存不保存训练草稿。浏览器草稿仍由既有训练组件/事件桥维护。可选解释单独缓存其科学快照、证据与提示版本，计时诊断字段不成为模型身份。解释失败、未配置、未授权不影响事实查询；网络授权由设置/复盘中的明确选择控制，不自动发送数据库或完整原始样本。

三个异步解释入口额外使用会话隔离的授权令牌：任务只持不可变的授权代数，后台线程不读取 Streamlit 会话状态。设置或复盘取消授权会立即使已排队/正在检索的旧代数失效；之后重新允许也不会恢复旧任务的发送权限。知识检索继续沿用原权限检查，模型客户端在真实 `urlopen` 请求前动态核对授权。已经发送的请求无法因此撤回，旧任务结果也不会在新授权身份下冒充当前结果。原布尔授权调用保持兼容；队列满时只显示局部重试提示。

这项修正后的当前源码专项 46 项通过、Ruff 通过，覆盖现有模型最小摘要/证据校验和详情/来源观察入口。[令牌与传输测试](../../tests/unit/test_ai_consent.py) 验证排队期间及构造请求期间撤回、撤回后重新授权不复活旧任务、动态检查失败时拒绝请求；[延迟检索回归](../../tests/knowledge/test_async_explanation_consent.py) 使用真实 KnowledgeWorkbench、Streamlit 设置回调和本机 HTTP 模型桩，正对照实际收到请求，检索中取消及取消后重开两例均未收到任何模型请求。该专项发生在最终授权补丁后，真实浏览器 A20 结果由交付回执另列。

无需安装缓存服务器或新增数据库配置。工作区路径和分析时区移到设置，页面范围位于相应主内容区；数据导入/增量同步仍走原入口服务。环境变量 `HEALTHZIP_AI_BASE_URL`、`HEALTHZIP_AI_MODEL`、`HEALTHZIP_AI_API_KEY` 仅供可选模型服务，未配置也可完整查看事实与记录训练。

缓存命中保留实际计算截止，不伪装成刚刚重算。导入时间和最近观测日期分开。总览/健康页只读，明确“更新分析”或“生成报告”才创建派生持久结果。

## 验证边界

数据时态与来源隔离有真实 Repository 行为测试，控件范围与折叠状态有 Streamlit AppTest，正常界面和量级性能有同机 Chromium 证据。上述三个层次互补。当前环境没有真机 iPhone Safari 或移动网络测量，不能把桌面 Chromium 的手机尺寸模拟写成真实软键盘或手机线上 P95。
