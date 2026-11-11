# v1.4 修复与交付验收

日期：2026-11-11。基线：`912aefc93b9bd9c1cebf297a10728c69c827e266`。执行范围见 [实施计划](v14_implementation_plan.md)。v1.3 的 R01–R15 见 [既有验收表](review_fixes_2026-11-11.md)，本轮保留这些回归；旧 476 项通过记录不能代替本轮检查。

本次使用合成训练、Apple 格式 ZIP 与 CSV 验证软件。实际公开来源和 wger 快照另有获取回执。私人数据库、完整教材/论文正文和下载媒体不随 Git 提交。最终整仓结果、工件与源码哈希见 `artifacts/v14/final-manifest.json`；GitHub 提交状态须以实际远端核对为准。

输入执行包的PDF原件保留在本地；Git保存文本规范与原包manifest。该manifest描述收到的输入包，不表示所有原件均已公开发布。

最终整仓 **632 passed，0失败、0错误、0跳过**；Ruff、离线锁文件检查、核心依赖wheel隔离安装和8页中文手册的字形/文本/实际渲染均通过。逐项功能范围和未完成的知识覆盖继续按下面的证据区分。

## F01–F13 逐项验收

表中路径相对 `src/healthzip/`。失败前证据与修复后的结果均保留在 `artifacts/v14/`，没有把原反例改成通过。

|编号|触发条件与原因|修复文件及行为|入口与验收证据|
|---|---|---|---|
|F01|Apple kJ/SDNN秒被错误视为kcal/ms；旧规范值可能已错标。|`normalize/__init__.py`、`science/state.py`、`energy.py`、`analytics/v13.py` 统一核对原值、原单位及转换版本，未知不入数值聚合。|`test_v14_science_import.py::test_f01_real_import_checks_units_before_energy_and_physiology` 真实ZIP导入；科学单位注册表与未知单位回归。|
|F02|跨午夜睡眠按结束日期计覆盖，可能超出半开窗口分母并中断全分析。|`science/state.py`、`reports.py`、`engine.py` 裁剪时间支持后计本地日期；单指标失败保留错误，不中断独立指标。|`test_f02_sleep_coverage_uses_clipped_half_open_local_dates`：UTC、上海、纽约DST和±1微秒；错误隔离回归。|
|F03|只取历史好参考，当前已记录的疼痛/技术受限不进建议。|新增 `advice.py` 统一UI/CLI/服务输入，分开历史参考与当前观察；当前不适改变当前使用状态，原候选不改。|`test_v14_advice_flow.py` 真实表单冻结、当前症状和原快照回归；`artifacts/v14/advice/`。|
|F04|STR26未与STR25共用参考质量和症状门控。|`science/applicability.py`、`strength.py` 共用true/false/unknown适用合同；未知不可视为无痛。|`test_f04_restricted_or_unknown_reference_cannot_license_harder_task` 参数化反例及正常正例；真实候选流程。|
|F05|新建第二场后编辑器仍写旧场。|`training/service.py`、`ui/training_page.py` 使用显式当前会话和恢复选择。|真实AppTest `test_f05_real_ui_new_session_and_explicit_resume`：两场各写动作/组、显式恢复、结束。|
|F06|历史另存模板读取目录最新定义，把旧次数目标套到新时长动作。|`training/service.py`、`exchange.py`、`offline.py` 保存并读取原 `definition_version`、展示和条件快照；新增目标校验测量模式。|次数→时长、负荷口径变化、历史模板/交换/离线旧版本回归；目录基线3失败工件。|
|F07|同动作两负荷的历史被合并为不兼容整体。|`science/semantics.py`、`engine.py`、`strength.py` 分离物理任务和负荷结果序列；各层独立样本、跨度、单位、预算和数据哈希。|`test_f07_real_training_service_preserves_load_layers_in_analysis`；两层各n=3、kg/lb精确等价、跨层receipt拒绝。|
|F08|校准只匹配调用方提供的范围子集，漏字段变成放宽适用范围。|`science/registry.py`、`semantics.py`、`prediction.py` 核对完整required_scope，动作/协议/单位从实际记录派生。|缺动作/协议/单位、人群未知、动作错配、调用方与实际冲突均拒绝，完整正例通过。|
|F09|iPhone仅inBed的流阻断Watch唯一asleep流。|`science/state.py` 先筛实际asleep支持，多个asleep流仍不相加。|真实ZIP导入Phone inBed+Watch asleep，新增任意inBed不改420分钟。|
|F10|先截top-k再检查矛盾，反证被展示预算隐藏。|`knowledge/retrieval.py` 在展示截断前核对全部目标/范围证据冲突。|`test_f10_conflicts_cannot_be_hidden_by_display_budget`：k=1/6/7一致，范围不同与真实冲突分开。|
|F11|父p的text/raw_xml含受限子fig内容，父许可泄漏子内容。|`knowledge/documents.py`、`rights.py`、`store.py` 使用节点独占内容与作用域；旧解析保留但被新版本替代。|文章/图许可四组合与段落/list/table；text/structured/raw_xml逐一检查，16旧解析重新处理。|
|F12|相同更正通知重抓使已精确复核版本再次失效。|`knowledge/store.py`、`acquisition.py` 以通知身份、内容与目标版本去重；变化才新建审查epoch。|`test_f12_identical_provider_notice_is_idempotent_but_changed_content_invalidates`，同时保留R15普通fetch不能解除待审。|
|F13|默认分析逐次反序列化所有历史；页面同时算周月。|`db/temporal_schema.py`、`analytics/cache.py`、`v13.py`、`core.py`、`p1.py`、`app.py` 按时间支持筛候选再选latest-visible；版本化有界缓存、按需页面/周月。|`test_v14_query_planning.py`；10k/100k/1m真实合成ZIP→Repository→默认分析→实际AppTest导航，详见性能工件。|

## 功能2、3与端到端场景

每日任务入口在「力量 → 本次候选与后续复核」。适用信息由用户填写并在本机保存版本；当前逐组目标通过唯一接口读取，保留原模板计划。选择策略和本台器械档位后核对候选；数值来自实际参考、用户目标和器械档位，不从群体证据推算个人必然成功的公斤数。可以暂缓、不采纳或修改后冻结为新任务。结束训练后在历史补录未执行/部分执行/完成及实际组。

未达到原计划上沿时，可选择负荷/次数试验；也可用用户明确的较高次数目标做同负荷次数试验。出现疼痛、技术限制、未知质量/关键协议、缺适用正文规则时，保存具体缺项。新观察、目标或知识变化只影响当前适用状态，旧候选快照可追溯。没有真人因果研究不自动阻断有适用规则的可选任务；没有真人校准仍不能发布确定停滞标签。

|场景|验证链与结果证据|
|---|---|
|E2E-01 空库→ZIP→状态/能量|`test_v14_science_import.py` 真实合成Apple ZIP导入到默认分析；既有能量累计/日均、日期覆盖、体重CSV来源回归；规模脚本实际导航状态/报告页。|
|E2E-02 旧目录/历史/模板升级|`test_legacy_46_and_condition_keys_survive_publication`、展示/定义更新与交换往返回归；默认库备份后原表哈希核对。|
|E2E-03 两场未结束→新场记录|`test_f05_real_ui_new_session_and_explicit_resume` 从真实控件开始，核对新增组归属、显式恢复与结束。|
|E2E-04 目标/档位/规则→候选|既有临时/模板double_progression和heavier_lower_reps控件回归；`tools/v14_advice_evidence.py` 使用真实核心库副本与合成训练，从可见控件填写协议、目标、适用信息到冻结/执行/反馈；缺目标/规则/协议均有负例。|
|E2E-05 当前疼痛/质量改变|`test_f03_current_pain_remains_in_frozen_evidence_and_blocks_upgrade` 和 `test_new_symptom_changes_current_use_without_rewriting_frozen_task`。|
|E2E-06 两负荷→周/月|真实TrainingService进入默认分析各自n=3；科学周期报告与UI按需报告共同回归，区间预算按序列登记。|
|E2E-07 选择/执行/反馈|实际UI采纳→完成→结束后反馈；未执行与部分执行分开；STR27/28按候选去重并保留任务/策略/规则分层。|
|E2E-08 更正/撤回|SourceClaim/ApplicationRule生命周期单测；真实核心UI验收在知识副本撤回S1后当前使用变待核，原快照不变。|
|E2E-09 新问法/冲突/缺正文|独立新表达先冻结后取实际输出再标注；原始失败结果保留。自由问答语义覆盖尚未完成，详见知识验收。|
|E2E-10 离线→重放两次|真实Chromium断网/重启IndexedDB、旧模板定义、目录1004项；原离线事件幂等回归。|
|E2E-11 全历史→编辑/时区|缓存精确输入/版本/时区/知识依赖失效，百万窗外历史不反序列化；旧版本移动/删除不复活。|
|E2E-12 空知识库|合成空库/全待审的UI负例继续支持记录、描述和具体缺项；不注入生产合成批准。|

逐场景并不意味着自由问答和全部知识主题都已通过。动作目录CAT-01–18见 [目录验收](v14_catalog.md)，KB-01–20见 [知识验收](v14_knowledge.md)，77指标追踪见 `artifacts/v14/metric-audit-77.json`。

## 性能与迁移

`tools/benchmark_v14.py` 生成10k/100k/1m历史记录，全部在当前30天窗口之外；每个规模实际流式导入ZIP，确认记录数不减少，测首次/重复分析、实际页面导航和重新打开数据库。硬件、内存、响应预算、源码身份及时间见 `artifacts/v14/performance/scale-results.json`。这衡量窗外历史增长路径；不代表百万条都在窗口内，也没有用用户真实全量ZIP或目标设备测量。

Repository事务迁移到schema v4，增加目录版本/媒体回执、窗口查询索引、建议适用信息和使用状态；既有事实、修订、模板、候选及审核历史保留。迁移前用 `python -m healthzip.cli --db-path <原库> backup <备份新路径>`；需要恢复时用 `python -m healthzip.cli restore <备份> <另一个新路径>`，不要用旧版本程序降级打开已升级原库。目录重建可重复运行，不清除私人动作/别名。默认本地安装另有备份与原34张表原列哈希核对，公开工件只保留核对状态。

自动分析的60秒刷新周期、16份缓存上限和2秒响应预算均为产品参数；显式cutoff不取整。新增导入、修订、目标、知识或时区改变会使对应缓存失效。页面显示实际计算截止时间，不能把缓存日期当成最新事件发生时间。

## 五维状态与剩余限制

|维度|本次状态|
|---|---|
|软件实现|F01–F13修复、历史兼容、完整目录、建议闭环和查询缓存实现；详细限制按CAT/KB/E2E逐项报告。|
|软件验证|最终pytest/Ruff、锁文件、安装、真实UI/浏览器与规模结果以final-manifest为准。测试仅证明指定软件行为。|
|语料覆盖|已取得并逐段核对S1和HHS相关正文；付费教材、部分中文正文处理许可及其规则主题仍有缺口，逐来源/章节/功能列出。完整目录媒体覆盖不等于科学证据覆盖。|
|专业审阅|核心主张/规则为真实AI辅助内容与适用性核对，未伪称人工专家；旧11卡不自动升权。动作AI中文译稿与肌群标签也不算专业训练审核。|
|科学验证|无新增真人时间外校准、个体干预因果收益或人工独立语义评测。自由问答的新表达仍暴露明显语义缺口；旧固定留出集未变为调参集。|

全部正文主题与自由问答尚未全通过，不能将本次代码推送表述为“全部功能已获科学或专业验证”。能够独立完成的记录、描述、适用规则下的任务和后续复核均已按上述路径实现；没有用缺真人验证掩盖软件接线或计算错误。
