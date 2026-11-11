# v1.4 科学与单位合同审计

本轮以 `912aefc93b9bd9c1cebf297a10728c69c827e266` 与 v1.4 执行包的 77 项矩阵为基线，逐项阅读并核对 65 项非 QAL 指标。机器可读追踪见 [metric_audit_65.json](../artifacts/v14/science/metric_audit_65.json)：每项列出要求、实现文件、已执行的软件测试、运行单位与验证边界。QAL、知识主张审阅、最终页面验收由相应工作分支汇总。

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

`context.current_session_observations` 为当前相关训练事实；候选结果的 `reference_record_ids` 和 `current_session_record_ids` 分开保存。根集成负责 AdviceContext、冻结后使用状态与页面行为。

`MetricResult.series_results[]` 提供 `outcome_series_id`、`task_id`、`normalized_load`、`normalized_unit`、`load_basis`、`outcome_unit`、`observation_segment`、`source_record_ids`、`first_observed_at`、`last_observed_at`、`data_snapshot_hash`、`input_data_hash` 与内层 `metric`。`context.outcome_series_id` 选择单层，`series_contexts[id]` 提供该层上下文。新页面登记 `allocate_look(..., outcome_series_id=...)` 后由相同系列核验，换负荷或截止时间不能复用旧 receipt。旧单层调用的既有 receipt 兼容，但新集成必须显式绑定系列。

STR28 `strata` 按 strategy/task_id/rule_versions 保存分母与未知；缺元数据保留空值，不编造分层身份。多次反馈以候选身份选择 cutoff 前最新可见记录。

知识原则的 `permitted_actions` 与用户请求动作取交集；STR25 必须显式有 `double_progression`，STR26 必须有对应的具体动作。缺失字段不继承宽泛 capability 的全部权限；每个输出动作列出对应规则版本。隔离正例明确声明测试动作许可，不修改生产规则的审阅事实。

获许可的 `repetition_progression` 使用 `progression_plan.rep_upper`：它必须是用户明确给出的正整数且高于已观察参考次数；同负荷候选保留参考负荷（`observed`）并使用该上沿次数（`user_target`）。无上沿、目标已达到、分数次数或受限/未知适用性只返回缺项/无需新增目标的理由，不默认加一次，不保证完成。

STR25 在数值比较前验证完整目标：次数上沿与下一任务次数须为正整数，下一次数不高于上沿，RIR 两端须完整、有限、有序且位于 0–10，器械档位须为有限非负数列表。部分目标正常冻结为 `insufficient`，不崩溃、不生成缺次数终点的负荷任务。STR26 的用户试验可明确只指定负荷与次数；两端 RIR 均缺失时保留 `target_rir_range=null`、`effort_target_status=unspecified` 并说明不属于已匹配努力目标。只填一个 RIR 端点或范围非法则阻止数值试验；不从历史 RIR 猜测用户目标。SQLite 文本数值经验证后作为数值输出，原始记录不改写。

## 可复现证据与限制

首次反例为 `failing_before.xml`（29 failed / 5 passed），随后新增矩阵与单位注册表反例分别保存在 `extended_before.xml`、`registry_before.xml`、`matrix_gaps_before.xml`、`followup_before.xml`。最终结果见 `verification.xml`；环境路径与主机元数据已脱敏，失败结果未改成通过。

候选目标补充审计先记录 `failing_before_plan_validation.xml` 的 35 个失败，再在 `plan_validation.xml` 验证全部通过；包含真实页面依次清空次数上沿、RIR、次数下限并保存缺项的回归。

使用项目虚拟环境运行：

```sh
.venv/bin/python -m pytest -q tests/science tests/integration/test_v14_science_import.py tests/unit/test_normalize.py tests/integration/test_review_analysis.py tests/integration/test_v14_advice_flow.py tests/integration/test_v14_choice_validation.py -k 'not actual_analysis_view' --junitxml=artifacts/v14/science/verification.xml
.venv/bin/python -m ruff check src/healthzip/science src/healthzip/normalize tests/science tests/integration/test_v14_science_import.py artifacts/v14/science/build_audit.py
.venv/bin/python artifacts/v14/science/build_audit.py
```

排除的一个既有页面测试交由根集成与完整 UI 验收执行。这里的 ZIP 与 TrainingService 都走实际入口，但内容均为合成数据；没有读取、发布真实个人健康导出，没有创建真人校准制品，没有伪造人工或专家审阅。测试通过证明已指定输入下的软件行为，不证明个体生理效度、预测校准或训练因果收益。
