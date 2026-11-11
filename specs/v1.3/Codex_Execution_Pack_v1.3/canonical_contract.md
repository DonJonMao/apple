## 统一契约与名称对照

本交付包统一使用 `metric_result.schema.json`。分册中 status、data_status、usable、valid 等历史称呼按此处规范映射，不得在代码中形成多套接口。

| 统一字段 | 固定含义与兼容方式 |
| --- | --- |
| data_status | valid / partial / insufficient / incompatible / conflicted / stale / not_identifiable / not_applicable。旧 usable→valid，仅表示数据可用；incomparable→incompatible；provisional根据原因映射partial或insufficient，并保留legacy_status。 |
| evidence_status | observed / definition_based / descriptive / model_conditional / research_only / predictive_validated_for_scope / intervention_validated_for_scope。指标定义文件中的definition、audit_definition等为依据身份，运行时映射definition_based，不可误映射为validated。 |
| valid_n / total_n | 同一计数域中的有效与总数；需说明组/场/天/题/主张。分母未知为null。n_obs、sample_count、n_valid/n_total是旧称；n_sessions另列。 |
| window / cutoff_time | 半开时间窗[start,end)，明确时区；截止时间同时约束事件时间与available_at，不能用computed_at替代。 |
| uncertainty | kind、lower、upper、level、assumptions。旧interval/interval_kind合并到此对象；情景范围不得填95%置信水平。 |
| evidence_refs / source_record_ids | 前者为科学/官方来源ID；后者为个人记录ID。不得混成一个source_ids数组。 |
| algorithm_version / parameter_set_id / calibration_artifact_id | 方法、参数和验证产物独立版本。数据可用与科学验证独立，缺验证时不能通过改状态放行。 |

目录中的 load_basis、负荷指标中的 load_mode/load_convention 属于同一语义域，入库采用规范 load_basis 加 legacy_raw_value；映射必须逐值显式。rep/measurement/recording_mode 同理。此映射负责兼容名称，不能把两只哑铃总重与每只重量、动态次数与等长秒数视为相同含义。

所有值类型、枚举和数据库命名在实现时形成唯一合同；不必要拆表，不引入多套重复计算。前端、报告和AI都消费同一次版本化分析结果。下列专业细则若使用旧字段名，应按本表适配，科学定义不变。
