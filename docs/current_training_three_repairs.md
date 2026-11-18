# 当前训练三项边界修复验收

> **本轮合同已替代旧日常自动参考要求。** 当前设计与验收见 [日常全组历史](daily_training_history.md)。本页的自动预指定、参考组驱动数值及旧测试／哈希是历史实现回执；其并发一致性、删除、历史冻结和专项方法保护继续保留。新普通组不自动获得研究参考身份。

基线：`555acb0ae8c3b2888f1e672be05569499c28484a`。范围只有自动前瞻参考、建议读取／冻结一致性、整场删除有效性。未更改科学公式、来源或行动规则，未读取真实健康库，也未开展资料复核及索引重建。

## 原复现与实现

开发开始时，新增回归实际得到四项失败：自动流程的新组 `reference_set` 为空；第二连接在旧初读位置完成组仍保存成功；有缓存及无缓存两条删除路径均返回 `linked_objectively`。

|合同|根因与实现位置|验收证据（tests/integration/test_current_training_three_repairs.py）|
|---|---|---|
|A1|正常计划没有前瞻参考。`training/reference.py` 在既有训练事务中按固定计划顺序指定，`current.py` 冻结实际参考依据|`test_automatic_reference_updates_next_numeric_basis`；真实 `app.py` 的 `test_real_app_plan_reference_update_and_deleted_history`|
|A2|不能事后升级最好组；当前状态和历史事件共同锁定采样|`test_never_promotes_better_ordinary_set_after_observation`，含不合格参考|
|A3|预指定与科学行动权限分开；现有 STR-25/26 未改动|`test_sampling_does_not_relax_science_conditions`，另保留原主动选择权限测试|
|A4|只在新建／修改的前瞻草稿事务中指定，迁移不回填历史|`test_completed_ordinary_history_is_never_backfilled`，普通实际仍进入描述分析|
|A5|组 UUID、任务、模板／目标版本、协议和来源进入 `reference_selection_json`，事件保留指定／撤销／更新|`test_reference_draft_lifecycle_and_repeated_instances`、`test_observed_or_skipped_task_cannot_reopen_sampling`、`test_explicit_plan_reference_and_unknown_policy`；原页面故障恢复测试追加参考身份断言|
|A6|自动采样及客观对照不写反馈|完整页面及服务闭环断言反馈表为空；原候选及历史反馈回归保留|
|B1|旧代码先读实例后取输入版本。现在先捕获基准，只用初读的父身份，业务数据统一使用 cutoff-visible AdviceContext|`test_initial_read_interleaving_cannot_freeze_completed_group`，真实第二连接|
|B2|保存前核对实例、父会话、目标／参考／实际版本、档位及知识；开始时间非空的草稿不属于待开始建议|`test_second_connection_changes_before_freeze_are_rejected` 的八类交错；`test_draft_with_actual_start_time_is_not_pending_advice`|
|B3|缓存也在短事务内核对；知识签名覆盖当前规则权限，私人写锁不冒充跨库锁|`test_cache_hit_checks_interleaved_session_deletion`、`test_rule_retraction_during_calculation_rejects_old_authority`；原无变更缓存复用测试|
|C1/C2|对照身份及行有效性遗漏父会话。现在加入父会话状态、版本及时间，历史页显著提示|`test_parent_deletion_cutoff_and_undo` 的有／无缓存分支；真实 app.py 删除历史页|
|C3|历史可见性新增显式 include_deleted 供对照读取，统计仍排除删除记录；撤销产生新依赖身份|历史 cutoff、撤销后唯一组计数、三个版本、冻结建议／对照不变；真实页面场景同时核对旧报告不变、新周月报告排除|
|C4|既有共同分析和记录路径继续使用|原 current_training 三文件、训练生命周期、候选、联合报告、声明失效、时间／任务隔离及整仓回归|

## 自动参考的明确边界

产品采样协议 `first-planned-work-set/1.0.0` 只使用计划工作组身份、动作条件、顺序和计划目标；不读取实际负荷、次数、RIR或是否成功来择组。动作条件确认、次数范围和计划 RIR 不足时不自动指定。显式逐组计划参考使用 `explicit-planned-reference-set/1.0.0`，优先于默认首组规则。无法解释的非空用户选择协议保留未指定。产品协议不会填充缺失的科学测量协议。

同条件重复实例共享采样范围，科学 task_id 仍沿用既有含位置的身份。新建组在同一创建事务内完成初始指定，保留初始记录修订 1；后续指定变化增加修订并追加事件。系统来源为 `system_plan_protocol`；只有真实手动指定为 `user_explicit`。开始后的手动追认被拒绝。草稿换条件不沿用旧条件声明；观察后不会因删除／跳过／低表现重新抽样。过去事件即使撤销，也不会解锁事后择优。

正常合成页使用计划 8–12／RIR2、档位 30／34／38和已有许可规则：旧参考 30×10 → 页面 34×8 → 自由完成34×12／RIR2 → 下一次 reference_set_id 指向新组，38×8／RIR2。具体 UUID 及冻结来源见本轮验证回执的页面证据。这些数字仅是合成验收结果。

保留原科学边界：缺计划 RIR 或实测 RIR 时，STR-25 不授予余力匹配进阶；STR-26 在原规则独立允许时仍可给非保证试验，目标／实测 RIR 缺失保持未知，并说明不能声称努力匹配。自动采样没有扩大或削弱这些权限。

## 旧测试调整说明

- `test_joint_report_body_values_sources_complete_days_and_new_task_page` 原来用带明确计划的组验证普通实际清单。带计划新组现在会自动预指定，夹具改为真实无计划普通组，保留原 `actual_records_no_reference_inferred`、身体时间对应及报告断言。
- `test_targets_condition_and_reference_are_frozen_before_outcome` 原来假设新计划草稿未指定。现在先断言自动来源，再显式撤销，继续原“完成时不得首次手动指定”的拒绝断言；保留后续手动声明、目标冻结、条件冻结及历史普通组拒绝断言。
- 原正常模板闭环的描述性分析断言保留；新增完整数值参考更新验收，避免仅以 STR-10 接收新记录作为完成证明。

## 验证记录

最终冻结副本上的专项验收：33 passed，0 failed，0 skipped，0 warnings，79.77 秒。真实 app.py 页面的新参考 UUID 为 `3c4ecca7-6c66-521b-b0c2-f9e7d4fa9556`，实际 34×12／RIR2，来源 `system_plan_protocol`；下一次数值实际使用该 UUID，输出 38×8／RIR2。该闭环反馈表为空。

最终隔离整仓结果：1848 passed，0 failed，0 skipped，0 warnings，1279.93 秒；既定 Ruff 全部通过。受验输入重新枚举为 310 份，测试后工作区与冻结副本逐文件 SHA-256 全部一致。清单摘要：`59d08bcf3553323d1313d255a7adc54e89787bf3cb5c2d04302a010d4b20dca1`。完整清单、逐项映射、真实页面依据及日志摘要见 [本轮验证回执](../artifacts/analysis-core/current-training-three-repairs-verification.json)。

整仓验证中途仅因最后两项具体生命周期修复停止过一次旧副本：替换动作的跳过身份改由内部事件元数据证明，不能依赖可编辑备注；某个普通组的撤销不能误清除另一已指定组。随后重新冻结并完成上述完整整仓验证，旧中断结果未作为最终通过证据。此前 1815 项通过属于基线，也未作为本轮结果。
