# Health ZIP Workbench 本地分析报告

生成时间：2026-11-11T07:35:48.455093+00:00

> 本报告仅整理和解释导入数据，不是医疗诊断，也不把缺失记录解释为没有佩戴、没有睡眠或没有进食。

## 数据盘点

|规范化类型|原始类型|样本数|有效日期|起始|结束|来源数|
|---|---|---:|---:|---|---|---:|

## Evidence Cards

## v1.3 统一指标

数据截止：2026-11-11T12:00:00+00:00；算法：healthzip-v1.3；窗口：2026-11-09T00:00:00+08:00 至 2026-11-16T00:00:00+08:00

|指标|数值|单位|数据状态|证据身份|有效/总数|原因|
|---|---|---|---|---|---|---|
|STR-01|{"completed_work_parent_sets": 2, "segments": 2, "warmup_sets": 0, "failed_attempts": 0, "unknown_work_sets": 0}|组|valid|definition_based|2/2||
|STR-02|[{"id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "measurement_mode": "repetitions", "reps": 10, "duration_s": null, "distance_m": null, "side": "both", "status": "completed"}, {"id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "measurement_mode": "repetitions", "reps": 8, "duration_s": null, "distance_m": null, "side": "both", "status": "completed"}]|次 / 秒|valid|definition_based|2/2||
|STR-03|[{"id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "entered_load": "30", "entered_unit": "kg", "load_basis": "plates_per_side_kg", "normalized_kg": 30.0, "plate_total_kg": 60.0, "total_load_kg": null, "per_hand_kg": null, "implements_mass_sum_kg": null, "assistance_kg": null, "marked_load": null, "reason_codes": ["bar_mass_or_symmetric_loading_unknown"]}, {"id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "entered_load": "32.5", "entered_unit": "kg", "load_basis": "plates_per_side_kg", "normalized_kg": 32.5, "plate_total_kg": 65.0, "total_load_kg": null, "per_hand_kg": null, "implements_mass_sum_kg": null, "assistance_kg": null, "marked_load": null, "reason_codes": ["bar_mass_or_symmetric_loading_unknown"]}]|kg / lb / 器械刻度|partial|definition_based|0/2||
|STR-04|{"groups": [{"sum_kg_reps": 1120.0, "basis": "plates_only", "set_ids": ["strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98"], "exercise_id": "psa.ex.smith_incline_press"}], "excluded_ids": []}|kg·次|valid|definition_based|2/2|bookkeeping_not_mechanical_work_or_stimulus|
|STR-05|未知|组/肌群/时间窗|insufficient|definition_based|0/2|muscle_mapping_unreviewed|
|STR-06|未知|组/肌群/时间窗|insufficient|definition_based|0/2|muscle_mapping_unreviewed|
|STR-07|{"sessions": 2, "observed_dates": 2, "span_days": 2.0006944444444446, "recorded_frequency_per_week": 4.941176470588235, "interval_days": [2.0006944444444446]}|次 / 天|valid|definition_based|2/2|recorded_frequency_not_actual_training_or_recovery|
|STR-08|{"sessions": 2, "observed_dates": 2, "span_days": 2.0006944444444446, "recorded_frequency_per_week": 4.941176470588235, "interval_days": [2.0006944444444446]}|次/周；天|valid|definition_based|2/2|recorded_frequency_not_actual_training_or_recovery|
|STR-09|{"completed": 2, "skipped": 0, "unknown": 0, "planned": 2, "completed_fraction_of_plan": 1.0, "extra_sets": 0}|比例|valid|definition_based|2/2||
|STR-10|[{"id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "rir": 2.0, "rir_interval": null, "original_rpe": null, "scale_type": null, "converted": false, "stop_reason": "planned_stop"}, {"id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "rir": 2.0, "rir_interval": null, "original_rpe": null, "scale_type": null, "converted": false, "stop_reason": "planned_stop"}]|次余力 / 量表分值|valid|definition_based|2/2||
|STR-11|[{"id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "session_id": 1, "load_value": "30", "load_unit": "kg", "load_basis": "plates_per_side_kg", "reps": 10, "rir": 2.0, "rir_interval": null, "quality": "acceptable", "stop_reason": "planned_stop", "set_position": 1, "reference_policy_id": null, "reference_declared_at": "2026-11-09T08:01:00+00:00", "measurement_mode": "repetitions", "duration_s": null, "distance_m": null, "condition_key": "26b97201976124383ce89e96052c5f77b337c74012642d8b16dad11e5c69c2c7"}, {"id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "session_id": 2, "load_value": "32.5", "load_unit": "kg", "load_basis": "plates_per_side_kg", "reps": 8, "rir": 2.0, "rir_interval": null, "quality": "acceptable", "stop_reason": "planned_stop", "set_position": 1, "reference_policy_id": null, "reference_declared_at": "2026-11-11T08:02:00+00:00", "measurement_mode": "repetitions", "duration_s": null, "distance_m": null, "condition_key": "26b97201976124383ce89e96052c5f77b337c74012642d8b16dad11e5c69c2c7"}]|结构化向量|valid|definition_based|2/2||
|STR-12|未知|次|incompatible|definition_based|2/2|same_load_and_observed_reps_required|
|STR-13|未知|kg 或同机刻度|incompatible|definition_based|2/2|same_repetitions_required|
|STR-14|未知|次余力|incompatible|definition_based|2/2|same_load_and_repetitions_required|
|STR-15|[{"session_id": 1, "set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "delta_reps": 0, "fraction_decrease": 0.0}, {"session_id": 2, "set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "delta_reps": 0, "fraction_decrease": 0.0}]|次数差 / 比例|valid|descriptive|2/2||
|STR-16|[{"set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "value": null, "unit": "kg", "formula_id": "epley_n3_0.0333", "formula_version": "1", "inputs": {"weight": null, "reps": 10, "rir": 2.0, "load_basis": "plates_per_side_kg"}, "data_status": "not_applicable", "evidence_status": "research_only", "reason_codes": ["invalid_or_missing_input"], "domain": null}, {"set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "value": null, "unit": "kg", "formula_id": "epley_n3_0.0333", "formula_version": "1", "inputs": {"weight": null, "reps": 8, "rir": 2.0, "load_basis": "plates_per_side_kg"}, "data_status": "not_applicable", "evidence_status": "research_only", "reason_codes": ["invalid_or_missing_input"], "domain": null}]|kg|not_applicable|research_only|0/2|not_validated_for_personal_decisions|
|STR-17|[{"set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "value": null, "unit": "kg", "formula_id": "epley_rir_over_30", "formula_version": "1", "inputs": {"weight": null, "reps": 10, "rir": 2.0, "load_basis": "plates_per_side_kg"}, "data_status": "not_applicable", "evidence_status": "research_only", "reason_codes": ["invalid_or_missing_input"], "domain": null}, {"set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "value": null, "unit": "kg", "formula_id": "epley_rir_over_30", "formula_version": "1", "inputs": {"weight": null, "reps": 8, "rir": 2.0, "load_basis": "plates_per_side_kg"}, "data_status": "not_applicable", "evidence_status": "research_only", "reason_codes": ["invalid_or_missing_input"], "domain": null}]|kg|not_applicable|research_only|0/2|not_validated_for_personal_decisions|
|STR-18|未知|次 / kg 或CV|insufficient|model_conditional|2/2|repeat_measurement_design_unconfirmed|
|STR-19|未知|次/天 或经验证指标单位/天|incompatible|definition_based|2/2|trend_reference_conditions_incompatible|
|STR-20|未知|与ΔH相同|incompatible|definition_based|2/2|trend_reference_conditions_incompatible|
|STR-21|未知|次 / kg /明确任务单位|insufficient|definition_based|2/2|user_or_protocol_equivalence_required|
|STR-22|未知|类别|incompatible|definition_based|2/2|trend_reference_conditions_incompatible|
|STR-23|[{"set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05", "observation": "capacity_unobserved", "stop_reason": "planned_stop"}, {"set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "observation": "capacity_unobserved", "stop_reason": "planned_stop"}]|类别|valid|definition_based|2/2||
|STR-24|未知|α预算 / look编号|insufficient|definition_based|2/2|registered_family_and_data_hash_required|
|STR-25|未知|kg /同器械刻度|insufficient|definition_based|2/2|comparable_reference_and_user_plan_required|
|STR-26|{"candidates": ["maintain_and_collect_reference"], "quantified_change": null}|结构化建议|partial|definition_based|2/2|reviewed_principles_missing；personal_intervention_effect_unvalidated|
|STR-27|[{"recommendation_id": "synthetic-demo-candidate", "adoption": "partially_adopted", "execution_state": "executed", "short_term_success": null, "reason_codes": [], "nonexecution_reason": null, "complete": false}]|类别与原始差值|valid|definition_based|1/1||
|STR-28|{"adoption_numerator": 0, "adoption_denominator": 1, "unanswered": 0, "success_numerator": 0, "success_denominator": 0, "missing_outcomes": 1}|比例 / 差值 / 区间|valid|definition_based|0/1||
|STR-29|{"fields": {"entered_load": {"numerator": 2, "denominator": 2}, "reps": {"numerator": 2, "denominator": 2}, "rir": {"numerator": 2, "denominator": 2}, "stop_reason": {"numerator": 2, "denominator": 2}}, "comparable_references": 2, "candidate_references": 2}|数量 / 比例|valid|definition_based|2/2|no_aggregate_quality_score|
|STR-30|未知|kg/kg|insufficient|definition_based|2/2|complete_numerator_and_comparable_body_mass_required|
|STATE-SLEEP-MAIN|未知|min|insufficient|definition_based|0/0|no_observed_asleep_intervals|
|STATE-SLEEP-24H|未知|min|insufficient|definition_based|0/0|no_observed_asleep_intervals|
|STATE-SLEEP-COVERAGE|{"recorded_dates": 0, "elapsed_dates": 3, "fraction": 0.0}|ratio|valid|definition_based|0/3|record_coverage_not_wear_time_or_complete_nights|
|STATE-SLEEP-STAGE|{"stage_minutes": {}, "annotation_coverage": null, "conflicts": []}|min; ratio|partial|definition_based|0/0|episode_boundary_unknown|
|STATE-SLEEP-TIMING|未知|timestamp; clock_min|insufficient|definition_based|0/0|explicit_sleep_episode_boundaries_required|
|STATE-RHR|未知|beats/min|insufficient|observed|0/0|protocol_streams_not_pooled|
|STATE-SDNN|未知|ms|insufficient|observed|0/0|protocol_streams_not_pooled；SDNN_is_not_RMSSD|
|STATE-REFERENCE-MEDIAN|未知|same_as_metric|insufficient|descriptive|0/0|baseline_window_equals_requested_window_product_default；current_day_excluded_from_own_reference；equal_weight_per_day|
|STATE-REFERENCE-MAD|未知|same_as_metric|insufficient|descriptive|0/0|baseline_window_equals_requested_window_product_default；current_day_excluded_from_own_reference；equal_weight_per_day|
|STATE-DEVIATION|未知|original_unit; dimensionless|insufficient|descriptive|0/0|baseline_window_equals_requested_window_product_default；current_day_excluded_from_own_reference；equal_weight_per_day|
|STATE-FATIGUE|未知|ordinal|insufficient|observed|0/0|ordinal_observations_not_combined_recovery_score|
|STATE-SORENESS|未知|ordinal|insufficient|observed|0/0|ordinal_observations_not_combined_recovery_score|
|STATE-PAIN|未知|categorical|insufficient|observed|0/0|ordinal_observations_not_combined_recovery_score|
|LOAD-SRPE|[{"session_id": 1, "session_rpe": 6.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 270.0}, {"session_id": 2, "session_rpe": 7.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 315.0}]|0–10 ordinal|valid|definition_based|2/2|set_RPE_not_session_RPE|
|LOAD-DURATION|[{"session_id": 1, "session_rpe": 6.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 270.0}, {"session_id": 2, "session_rpe": 7.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 315.0}]|min|valid|definition_based|2/2|set_RPE_not_session_RPE|
|LOAD-SRPE-AU|[{"session_id": 1, "session_rpe": 6.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 270.0}, {"session_id": 2, "session_rpe": 7.0, "duration_minutes": 45.0, "duration_source": "user_reported", "actual_collection_delay_minutes": 0.0, "srpe_protocol": "cr10", "duration_protocol": "user_elapsed_including_rest", "AU": 315.0}]|AU|valid|definition_based|2/2|set_RPE_not_session_RPE|
|BODY-MASS-DAILY|未知|kg|insufficient|definition_based|0/0|comparable_body_mass_observations_missing|
|BODY-MASS-TREND|未知|kg/week|insufficient|definition_based|0/0|comparable_body_mass_observations_missing|
|BODY-MASS-RELATIVE|未知|%/week|insufficient|definition_based|0/0|comparable_body_mass_observations_missing|
|ENERGY-BASAL|未知|kcal/day|insufficient|observed|0/0|device_report_not_true_TEE；cross_boundary_samples_not_prorated|
|ENERGY-ACTIVE|未知|kcal/day|insufficient|observed|0/0|device_report_not_true_TEE；cross_boundary_samples_not_prorated|
|ENERGY-DEVICE-TOTAL|未知|kcal/day|insufficient|observed|0/0|same_window_and_stream_components_only；workout_not_added_again；no_TEF_multiplier；device_report_not_true_TEE|
|ENERGY-RECORD-COVERAGE|[{"kind": "basal", "numerator": 0, "denominator": 3, "definition": "recorded valid dates / elapsed target dates, not wear time"}, {"kind": "active", "numerator": 0, "denominator": 3, "definition": "recorded valid dates / elapsed target dates, not wear time"}, {"kind": "total", "numerator": 0, "denominator": 3, "definition": "recorded valid dates / elapsed target dates, not wear time"}]|ratio|valid|definition_based|0/3||
|ENERGY-NET-STORAGE|未知|kcal/day|not_identifiable|definition_based|2/2|body_mass_does_not_identify_storage；composition_model_required|
|ENERGY-DELTA-INTAKE|未知|kcal/day|insufficient|definition_based|2/2|mass_series_required|
|ENERGY-ABSOLUTE-INTAKE|未知|kcal/day|not_identifiable|definition_based|2/2|independent_intake_baseline_or_credible_bias_storage_scenario_required|
|ENERGY-IDENTIFIABILITY|{"identified": false, "invariant_family": "(I+c, E+c, b-c) leaves D=E+b and Q=I-E unchanged", "required_independent_data": ["independent equilibrium intake or calibrated device bias", "valid composition/storage model"]}|categorical|not_identifiable|definition_based|2/2||
|PRED-B0|未知|reps; RIR separately|insufficient|definition_based|2/2|fixed_task_prediction_target_required|
|PRED-B1|未知|reps|insufficient|definition_based|2/2|fixed_task_prediction_target_required|
|PRED-ERROR-GAIN|{"n_pairs": 0, "eligible_n": 0, "excluded_n": 0, "MAE_B0": null, "MAE_B1": null, "RMSE_B0": null, "RMSE_B1": null, "delta_MAE": null, "delta_RMSE": null, "fallback_n": 0, "strata": {}, "independent_person_effect_validation": false}|reps|insufficient|research_only|0/0||
|PRED-INTERVAL|{"n": 0, "total_n": 0, "covered": 0, "coverage": null, "mean_width": null, "strata": {}}|ratio; reps|insufficient|research_only|0/0||
|REPORT-PERIOD-COVERAGE|{"daily_coverage": [], "session_coverage": [{"kind": "LOAD-SRPE", "numerator": 2, "denominator": 2, "definition": "known measurements / eligible completed sessions in the window"}, {"kind": "LOAD-DURATION", "numerator": 2, "denominator": 2, "definition": "known measurements / eligible completed sessions in the window"}, {"kind": "LOAD-SRPE-AU", "numerator": 2, "denominator": 2, "definition": "known measurements / eligible completed sessions in the window"}], "complete_previous_period_comparable": false}|ratio|partial|definition_based|2/2|current_calendar_period_incomplete|
|REPORT-STATE-SUMMARY|未知|mixed explicit units|insufficient|descriptive|2/2|current_calendar_period_incomplete|
|REPORT-ENERGY-SUMMARY|{"body_mass_trend": {"metric_id": "BODY-MASS-TREND", "algorithm_version": "healthzip-science-1.3.0", "computed_at": "2026-11-11T12:00:00+00:00", "cutoff_time": "2026-11-11T12:00:00+00:00", "window": {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00", "timezone": "Asia/Shanghai", "closure": "[start,end)"}, "value": null, "unit": "kg/week", "data_status": "insufficient", "evidence_status": "definition_based", "valid_n": 2, "total_n": 2, "n_sessions": 2, "count_domain": "records", "coverage": [], "uncertainty": {"kind": "not_estimated", "lower": null, "upper": null, "level": null, "assumptions": []}, "assumptions": [], "reason_codes": ["comparable_body_mass_observations_missing"], "source_record_ids": ["strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"], "evidence_refs": ["E1", "E2"], "parameter_set_id": null, "calibration_artifact_id": null, "limitations": ["足够数据后方可用验证过的时间块bootstrap；不能以OLS方差冒充Theil–Sen区间。"]}, "known_complete_day_energy_sum": null, "valid_day_mean": null, "valid_complete_days": 0, "elapsed_dates": 3, "whole_window_delta_intake": {"metric_id": "ENERGY-DELTA-INTAKE", "algorithm_version": "healthzip-science-1.3.0", "computed_at": "2026-11-11T12:00:00+00:00", "cutoff_time": "2026-11-11T12:00:00+00:00", "window": {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00", "timezone": "Asia/Shanghai", "closure": "[start,end)"}, "value": null, "unit": "kcal/day", "data_status": "insufficient", "evidence_status": "definition_based", "valid_n": 2, "total_n": 2, "n_sessions": 2, "count_domain": "records", "coverage": [], "uncertainty": {"kind": "not_estimated", "lower": null, "upper": null, "level": null, "assumptions": []}, "assumptions": [], "reason_codes": ["mass_series_required"], "source_record_ids": ["strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"], "evidence_refs": ["E2", "E4"], "parameter_set_id": null, "calibration_artifact_id": null, "limitations": ["h=ρq+εl；条件方差hᵀΣh+ε²VarW0−2εCov(hᵀw,W0)，另传播参数/系统误差；非独立W0保留协方差。"]}, "extrapolated_period_total": null}|kg/week; kcal; kcal/day|partial|descriptive|2/2|current_calendar_period_incomplete|
|REPORT-RECOMMENDATION-FOLLOWUP|{"execution": {"metric_id": "STR-27", "algorithm_version": "healthzip-science-1.3.0", "computed_at": "2026-11-11T12:00:00+00:00", "cutoff_time": "2026-11-11T12:00:00+00:00", "window": {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00", "timezone": "Asia/Shanghai", "closure": "[start,end)"}, "value": [{"recommendation_id": "synthetic-demo-candidate", "adoption": "partially_adopted", "execution_state": "executed", "short_term_success": null, "reason_codes": [], "nonexecution_reason": null, "complete": false}], "unit": "类别与原始差值", "data_status": "valid", "evidence_status": "definition_based", "valid_n": 1, "total_n": 1, "n_sessions": 2, "count_domain": "recommendations", "coverage": [], "uncertainty": {"kind": "not_estimated", "lower": null, "upper": null, "level": null, "assumptions": []}, "assumptions": [], "reason_codes": [], "source_record_ids": ["strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"], "evidence_refs": ["R7"], "parameter_set_id": null, "calibration_artifact_id": null, "limitations": ["实际结果与推荐依从性可核对；因果效果仍需对照。", "短期做成不证明长期增肌有效", "不能只保留成功采纳者"]}, "summary": {"metric_id": "STR-28", "algorithm_version": "healthzip-science-1.3.0", "computed_at": "2026-11-11T12:00:00+00:00", "cutoff_time": "2026-11-11T12:00:00+00:00", "window": {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00", "timezone": "Asia/Shanghai", "closure": "[start,end)"}, "value": {"adoption_numerator": 0, "adoption_denominator": 1, "unanswered": 0, "success_numerator": 0, "success_denominator": 0, "missing_outcomes": 1}, "unit": "比例 / 差值 / 区间", "data_status": "valid", "evidence_status": "definition_based", "valid_n": 0, "total_n": 1, "n_sessions": 2, "count_domain": "recommendations", "coverage": [], "uncertainty": {"kind": "not_estimated", "lower": null, "upper": null, "level": null, "assumptions": []}, "assumptions": [], "reason_codes": [], "source_record_ids": ["strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98", "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"], "evidence_refs": ["R7", "M1"], "parameter_set_id": null, "calibration_artifact_id": null, "limitations": ["小分母、同人相关、选择性采纳与缺失影响估计；分别披露，不将比率包装为疗效。", "采纳率不能作为唯一优化目标", "前后变好不证明是建议导致"]}, "followup_windows": [], "causal_effect": null}|categorical; outcome units|partial|descriptive|2/2|current_calendar_period_incomplete|
|QAL-01|{"queries": [], "macro_group_recall": null, "bundle_hit": {"numerator": 0, "denominator": 0, "rate": null}, "unreviewed_gold_cases": 0}|比例 / 完整命中题数|insufficient|definition_based|0/0|finite_retrieval_budget_required；gold_review_separate_from_model_output|
|QAL-02|{"queries": [], "micro_precision_lower": {"numerator": 0, "denominator": 0, "rate": null}, "macro_precision_lower": null}|比例 / 证据单元数 / token|insufficient|definition_based|0/0||
|QAL-03|{"rendered_citation_count": 0, "unique_citation_associations": 0, "location_rate": {"numerator": 0, "denominator": 0, "rate": null}, "support_precision": {"numerator": 0, "denominator": 0, "rate": null}, "judgment_coverage": {"numerator": 0, "denominator": 0, "rate": null}, "support_labels": {}}|比例 / 引用主张链接数|insufficient|definition_based|0/0||
|QAL-04|{"claim_support": {"numerator": 0, "denominator": 0, "rate": null}, "labels": {}, "intent_coverage": null}|比例 / 原子主张数|insufficient|definition_based|0/0||
|QAL-05|{"applicability_error_rate": {"numerator": 0, "denominator": 0, "rate": null}, "unjudged": 0, "error_types": {}}|比例 / 错配主张数|insufficient|definition_based|0/0|unknown_is_not_scope_match|
|QAL-06|{"unsupported_numeric": {"numerator": 0, "denominator": 0, "rate": null}, "causal_overreach": {"numerator": 0, "denominator": 0, "rate": null}, "unjudged_numeric": 0, "unjudged_causal": 0, "any_violation_answer_count": 0}|比例 / 违规断言数 / 涉及回答数|insufficient|definition_based|0/0||
|QAL-07|{"overanswer": {"numerator": 0, "denominator": 0, "rate": null}, "underanswer": {"numerator": 0, "denominator": 0, "rate": null}, "labels": {}, "answerable_intents": 0, "insufficient_intents": 0}|比例 / 意图数|insufficient|definition_based|0/0||
|QAL-08|{"fallback_requests": {"numerator": 0, "denominator": 0, "rate": null}, "trace_coverage": {"numerator": 0, "denominator": 0, "rate": null}, "fallback_completion": {"numerator": 0, "denominator": 0, "rate": null}, "event_count": 0, "reason_request_counts": {}, "incident_clusters": 0}|比例 / 请求数 / 回退事件数|insufficient|definition_based|0/0||
|QAL-09|{"overall_fulltext_acquisition": {"numerator": 0, "denominator": 0, "rate": null}, "licensed_retrievable_fetch": {"numerator": 0, "denominator": 0, "rate": null}, "theory_review_completion": {"numerator": 0, "denominator": 0, "rate": null}, "theory_activation_ready": {"numerator": 0, "denominator": 0, "rate": null}, "feature_claim_coverage": {"numerator": 0, "denominator": 0, "rate": null}, "source_states": {}}|比例 / 来源版本数 / 理论卡数 / 功能主张要求数|insufficient|definition_based|0/0||
|QAL-10|{"request_violation_rate": {"numerator": 0, "denominator": 0, "rate": null}, "decision_violation_rate": {"numerator": 0, "denominator": 0, "rate": null}, "blocked_attempts": 0, "unverifiable_guard_gap": 0, "attack_families": [], "release_gate_passed": false}|事件数 / 涉及请求比例|insufficient|definition_based|0/0||
|QAL-11|{"numeric_consistency": {"numerator": 0, "denominator": 0, "rate": null}, "reference_coverage": {"numerator": 0, "denominator": 0, "rate": null}, "issues": []}|比例 / 可核验数值断言数|insufficient|definition_based|0/0||
|QAL-12|{"identity_verified": {"numerator": 0, "denominator": 0, "rate": null}, "active_material_compliance": {"numerator": 0, "denominator": 0, "rate": null}, "noncompliant_active_ids": [], "release_gate_passed": false}|比例 / 来源版本数 / 违规激活事件数|insufficient|definition_based|0/0||

完整合同（含窗口、记录ID、参数、区间、证据和算法版本）：

```json
{
  "metrics": {
    "STR-01": {
      "metric_id": "STR-01",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "completed_work_parent_sets": 2,
        "segments": 2,
        "warmup_sets": 0,
        "failed_attempts": 0,
        "unknown_work_sets": 0
      },
      "unit": "组",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "计数为确定性账目，但真实执行与记录准确性未知；报告未知组数。",
        "组数不等于有效刺激",
        "不同肌群组数之和不等于全身有效组"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-02": {
      "metric_id": "STR-02",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "measurement_mode": "repetitions",
          "reps": 10,
          "duration_s": null,
          "distance_m": null,
          "side": "both",
          "status": "completed"
        },
        {
          "id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "measurement_mode": "repetitions",
          "reps": 8,
          "duration_s": null,
          "distance_m": null,
          "side": "both",
          "status": "completed"
        }
      ],
      "unit": "次 / 秒",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "用户记录可能误数；不自行制造测量置信区间，保留原始与修改版本。",
        "保持60秒不等价于做60次",
        "自重动作不因外部重量为0就无训练量"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-03": {
      "metric_id": "STR-03",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "entered_load": "30",
          "entered_unit": "kg",
          "load_basis": "plates_per_side_kg",
          "normalized_kg": 30.0,
          "plate_total_kg": 60.0,
          "total_load_kg": null,
          "per_hand_kg": null,
          "implements_mass_sum_kg": null,
          "assistance_kg": null,
          "marked_load": null,
          "reason_codes": [
            "bar_mass_or_symmetric_loading_unknown"
          ]
        },
        {
          "id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "entered_load": "32.5",
          "entered_unit": "kg",
          "load_basis": "plates_per_side_kg",
          "normalized_kg": 32.5,
          "plate_total_kg": 65.0,
          "total_load_kg": null,
          "per_hand_kg": null,
          "implements_mass_sum_kg": null,
          "assistance_kg": null,
          "marked_load": null,
          "reason_codes": [
            "bar_mass_or_symmetric_loading_unknown"
          ]
        }
      ],
      "unit": "kg / lb / 器械刻度",
      "data_status": "partial",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "单位换算是确定性的；杆重、摩擦、滑轮倍率未知属于结构不确定性，不能靠更多相同记录消除。",
        "单边30kg不能直接称总重30kg",
        "不能把辅助重量当正外部训练重量",
        "机器刻度不等于跨机器可比阻力"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-04": {
      "metric_id": "STR-04",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "groups": [
          {
            "sum_kg_reps": 1120.0,
            "basis": "plates_only",
            "set_ids": [
              "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
              "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98"
            ],
            "exercise_id": "psa.ex.smith_incline_press"
          }
        ],
        "excluded_ids": []
      },
      "unit": "kg·次",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "bookkeeping_not_mechanical_work_or_stimulus"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "已知输入的乘积和为确定值；覆盖与口径不确定性必须随输出传播。",
        "不是焦耳；缺少位移不能叫机械功",
        "吨位增加不等于肌肥大增加",
        "禁止把它与sRPE或kcal加权求和"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-05": {
      "metric_id": "STR-05",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "组/肌群/时间窗",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "muscle_mapping_unreviewed"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "映射的不确定性与剂量生理意义分开；不生成伪精确刺激量。",
        "不能将所有肌群计数相加作全身有效组",
        "直接肌群也不意味着每组刺激完全相同"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-06": {
      "metric_id": "STR-06",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "组/肌群/时间窗",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "muscle_mapping_unreviewed"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "间接参与的定性标签不确定性须记录；无普适量化折算置信度。",
        "0.5不是通用生理刺激比例",
        "不能用该折算直接给个人最优组数"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-07": {
      "metric_id": "STR-07",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "sessions": 2,
        "observed_dates": 2,
        "span_days": 2.0006944444444446,
        "recorded_frequency_per_week": 4.941176470588235,
        "interval_days": [
          2.0006944444444446
        ]
      },
      "unit": "次 / 天",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "recorded_frequency_not_actual_training_or_recovery"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "n是样本量而非有效独立信息量，相关观测不计成独立样本保证。",
        "3次不是已足以判定停滞的科学门槛"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-08": {
      "metric_id": "STR-08",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "sessions": 2,
        "observed_dates": 2,
        "span_days": 2.0006944444444446,
        "recorded_frequency_per_week": 4.941176470588235,
        "interval_days": [
          2.0006944444444446
        ]
      },
      "unit": "次/周；天",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "recorded_frequency_not_actual_training_or_recovery"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "缺日志导致实际频率未知；明确“记录内频率”。",
        "不能从平均间隔推断肌肉已恢复",
        "同场两个动作不等于同肌群两次独立训练日"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-09": {
      "metric_id": "STR-09",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "completed": 2,
        "skipped": 0,
        "unknown": 0,
        "planned": 2,
        "completed_fraction_of_plan": 1.0,
        "extra_sets": 0
      },
      "unit": "比例",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "planned_sets",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "未知执行保留分母状态；不得把缺失归入已完成或跳过。",
        "执行率高不代表刺激足够",
        "禁止训练后降低目标使完成率虚高"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-10": {
      "metric_id": "STR-10",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "rir": 2.0,
          "rir_interval": null,
          "original_rpe": null,
          "scale_type": null,
          "converted": false,
          "stop_reason": "planned_stop"
        },
        {
          "id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "rir": 2.0,
          "rir_interval": null,
          "original_rpe": null,
          "scale_type": null,
          "converted": false,
          "stop_reason": "planned_stop"
        }
      ],
      "unit": "次余力 / 量表分值",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S3",
        "S4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "RIR具有个体/动作/次数依赖误差；不使用群体平均偏差给个体统一校正。",
        "相同工作RIR下降不是进步",
        "不能统一给全部RIR加1修正",
        "高RIR估计不自动认定准确"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-11": {
      "metric_id": "STR-11",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "session_id": 1,
          "load_value": "30",
          "load_unit": "kg",
          "load_basis": "plates_per_side_kg",
          "reps": 10,
          "rir": 2.0,
          "rir_interval": null,
          "quality": "acceptable",
          "stop_reason": "planned_stop",
          "set_position": 1,
          "reference_policy_id": null,
          "reference_declared_at": "2026-11-09T08:01:00+00:00",
          "measurement_mode": "repetitions",
          "duration_s": null,
          "distance_m": null,
          "condition_key": "26b97201976124383ce89e96052c5f77b337c74012642d8b16dad11e5c69c2c7"
        },
        {
          "id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "session_id": 2,
          "load_value": "32.5",
          "load_unit": "kg",
          "load_basis": "plates_per_side_kg",
          "reps": 8,
          "rir": 2.0,
          "rir_interval": null,
          "quality": "acceptable",
          "stop_reason": "planned_stop",
          "set_position": 1,
          "reference_policy_id": null,
          "reference_declared_at": "2026-11-11T08:02:00+00:00",
          "measurement_mode": "repetitions",
          "duration_s": null,
          "distance_m": null,
          "condition_key": "26b97201976124383ce89e96052c5f77b337c74012642d8b16dad11e5c69c2c7"
        }
      ],
      "unit": "结构化向量",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S3",
        "S6",
        "S7",
        "M1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "努力程度和动作质量未测完全时，只能有限可比；样本质量标签与估计区间不是同一概念。",
        "每次取最大e1RM会引入选择偏差",
        "不能将不同机器同名动作拼接"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-12": {
      "metric_id": "STR-12",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "次",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "same_load_and_observed_reps_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S5",
        "S6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "两次原始次数差可直接报告，稳定适应需考虑测量波动与后续重复。",
        "单次多1次不自动等于永久适应"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-13": {
      "metric_id": "STR-13",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kg 或同机刻度",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "same_repetitions_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S5",
        "S6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "实际差值确定但能力提升不确定；完整负荷未知时不报告总负荷百分比。",
        "增加负荷不自动等于增肌",
        "辅助重量减少应按辅助模式解释"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-14": {
      "metric_id": "STR-14",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "次余力",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "same_load_and_repetitions_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S3",
        "S4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "余力差的主观误差不能按独立精确次数处理；区间/上界输入保留集合语义。",
        "RIR高2不等于1RM确定增加某百分比"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-15": {
      "metric_id": "STR-15",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "session_id": 1,
          "set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "delta_reps": 0,
          "fraction_decrease": 0.0
        },
        {
          "session_id": 2,
          "set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "delta_reps": 0,
          "fraction_decrease": 0.0
        }
      ],
      "unit": "次数差 / 比例",
      "data_status": "valid",
      "evidence_status": "descriptive",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S3"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "组序疲劳、休息、配速等混杂；该描述不是原因概率。",
        "掉次不证明过度训练",
        "不能超过20%就自动减两组"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-16": {
      "metric_id": "STR-16",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "value": null,
          "unit": "kg",
          "formula_id": "epley_n3_0.0333",
          "formula_version": "1",
          "inputs": {
            "weight": null,
            "reps": 10,
            "rir": 2.0,
            "load_basis": "plates_per_side_kg"
          },
          "data_status": "not_applicable",
          "evidence_status": "research_only",
          "reason_codes": [
            "invalid_or_missing_input"
          ],
          "domain": null
        },
        {
          "set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "value": null,
          "unit": "kg",
          "formula_id": "epley_n3_0.0333",
          "formula_version": "1",
          "inputs": {
            "weight": null,
            "reps": 8,
            "rir": 2.0,
            "load_basis": "plates_per_side_kg"
          },
          "data_status": "not_applicable",
          "evidence_status": "research_only",
          "reason_codes": [
            "invalid_or_missing_input"
          ],
          "domain": null
        }
      ],
      "unit": "kg",
      "data_status": "not_applicable",
      "evidence_status": "research_only",
      "valid_n": 0,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "not_validated_for_personal_decisions"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S6",
        "S7",
        "N3"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "误差区间必须来自匹配动作/协议的校准工件，不能任意±5%；无校准就只显示proxy或隐藏数值。",
        "不把同一公式当所有动作的精确强度换算",
        "不得拼接不同formula的趋势"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-17": {
      "metric_id": "STR-17",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "value": null,
          "unit": "kg",
          "formula_id": "epley_rir_over_30",
          "formula_version": "1",
          "inputs": {
            "weight": null,
            "reps": 10,
            "rir": 2.0,
            "load_basis": "plates_per_side_kg"
          },
          "data_status": "not_applicable",
          "evidence_status": "research_only",
          "reason_codes": [
            "invalid_or_missing_input"
          ],
          "domain": null
        },
        {
          "set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "value": null,
          "unit": "kg",
          "formula_id": "epley_rir_over_30",
          "formula_version": "1",
          "inputs": {
            "weight": null,
            "reps": 8,
            "rir": 2.0,
            "load_basis": "plates_per_side_kg"
          },
          "data_status": "not_applicable",
          "evidence_status": "research_only",
          "reason_codes": [
            "invalid_or_missing_input"
          ],
          "domain": null
        }
      ],
      "unit": "kg",
      "data_status": "not_applicable",
      "evidence_status": "research_only",
      "valid_n": 0,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "not_validated_for_personal_decisions"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S3",
        "S4",
        "S6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "组合公式增加RIR测量误差；没有专门校准时不能给伪置信区间或作为核心决策。",
        "不得作为默认停滞核心",
        "不得据此保证32.5kg能做8次"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-18": {
      "metric_id": "STR-18",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "次 / kg 或CV",
      "data_status": "insufficient",
      "evidence_status": "model_conditional",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [
        "independent repeat pairs",
        "equal within-person variance",
        "no systematic learning or fatigue between repeats"
      ],
      "reason_codes": [
        "repeat_measurement_design_unconfirmed"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S7",
        "M1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "报告TE/SEM的估计区间或至少适用研究协议；样本不足不能给稳定个人噪声。",
        "不把群体CV4.2%写成每个人阈值",
        "MDC不是用户最小有价值变化"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-19": {
      "metric_id": "STR-19",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "次/天 或经验证指标单位/天",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "trend_reference_conditions_incompatible"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M1",
        "M2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "点估计没有不确定性保证；误差模型由STR-20单独处理，不能用接近零的斜率直接下结论。",
        "负斜率不等于原因诊断",
        "记录序号不可代替真实日期"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-20": {
      "metric_id": "STR-20",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "与ΔH相同",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "trend_reference_conditions_incompatible"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M1",
        "M2",
        "N1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "区间的覆盖声明附带误差分布/相关结构/适用数据情景。仅通过残差检验不能证明假设，需校准与敏感性分析。",
        "三次可回归不代表三次足够停滞",
        "不能随机拆同一个人的重叠窗口验证区间"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-21": {
      "metric_id": "STR-21",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "次 / kg /明确任务单位",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "user_or_protocol_equivalence_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "δ是决策意义定义，不是估计不确定性。报告不同合理δ下结论是否改变，不为某次结果调δ。",
        "不能看完数据后选一个刚好让结果显著的δ",
        "不能把TE/MDC直接当同一概念"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-22": {
      "metric_id": "STR-22",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "类别",
      "data_status": "incompatible",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "trend_reference_conditions_incompatible"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M2",
        "S3",
        "S4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "区间宽→uncertain；候选标签不是因果或疾病诊断。误报/漏报取决于明确参考标签。",
        "不把P>0.05称停滞",
        "不因HRV正常判定训练刺激不足",
        "不声称“已证明生理无法进步”"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-23": {
      "metric_id": "STR-23",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "set_id": "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05",
          "observation": "capacity_unobserved",
          "stop_reason": "planned_stop"
        },
        {
          "set_id": "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
          "observation": "capacity_unobserved",
          "stop_reason": "planned_stop"
        }
      ],
      "unit": "类别",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S3",
        "S4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "停止原因和RIR有自报误差；capacity_unobserved是信息状态而非低能力判断。",
        "固定做10次不是证明只能做10次",
        "不要求用户为了模型安全地/不安全地做每组力竭"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-24": {
      "metric_id": "STR-24",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "α预算 / look编号",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "registered_family_and_data_hash_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M2",
        "N2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "并集界无需各look独立，但需要每个区间有效；预算只对声明family范围成立，不自动扩展为全App终身误报率。",
        "95%区间每天重复使用不等于长期95%保证",
        "不能将普通95%CI称置信序列",
        "本基线的统一CI等效判定不等同于标准α级TOST的90%CI"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-25": {
      "metric_id": "STR-25",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kg /同器械刻度",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "comparable_reference_and_user_plan_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S2",
        "S5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "可用负荷档位是确定事实，是否适合/能做成仍未知；无个体预测校准不输出成功概率。",
        "不能固定加5%或减5%",
        "最小档位不等于安全/成功保证"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-26": {
      "metric_id": "STR-26",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "candidates": [
          "maintain_and_collect_reference"
        ],
        "quantified_change": null
      },
      "unit": "结构化建议",
      "data_status": "partial",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "reviewed_principles_missing",
        "personal_intervention_effect_unvalidated"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S1",
        "S5",
        "S8",
        "R7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "文献支持候选方向，不支持个体最优与精确效果；推荐需附替代选择及证据不足。",
        "恢复指标正常不证明容量不足",
        "加组的群体剂量反应不能倒推个人最佳组数",
        "不能把30×10换算保证32.5×8"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-27": {
      "metric_id": "STR-27",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "recommendation_id": "synthetic-demo-candidate",
          "adoption": "partially_adopted",
          "execution_state": "executed",
          "short_term_success": null,
          "reason_codes": [],
          "nonexecution_reason": null,
          "complete": false
        }
      ],
      "unit": "类别与原始差值",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 1,
      "total_n": 1,
      "n_sessions": 2,
      "count_domain": "recommendations",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "实际结果与推荐依从性可核对；因果效果仍需对照。",
        "短期做成不证明长期增肌有效",
        "不能只保留成功采纳者"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-28": {
      "metric_id": "STR-28",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "adoption_numerator": 0,
        "adoption_denominator": 1,
        "unanswered": 0,
        "success_numerator": 0,
        "success_denominator": 0,
        "missing_outcomes": 1
      },
      "unit": "比例 / 差值 / 区间",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 1,
      "n_sessions": 2,
      "count_domain": "recommendations",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R7",
        "M1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "小分母、同人相关、选择性采纳与缺失影响估计；分别披露，不将比率包装为疗效。",
        "采纳率不能作为唯一优化目标",
        "前后变好不证明是建议导致"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-29": {
      "metric_id": "STR-29",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "fields": {
          "entered_load": {
            "numerator": 2,
            "denominator": 2
          },
          "reps": {
            "numerator": 2,
            "denominator": 2
          },
          "rir": {
            "numerator": 2,
            "denominator": 2
          },
          "stop_reason": {
            "numerator": 2,
            "denominator": 2
          }
        },
        "comparable_references": 2,
        "candidate_references": 2
      },
      "unit": "数量 / 比例",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "no_aggregate_quality_score"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "M1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "记录完整性只反映数据可用性，不证明记录内容或生理解释可靠。",
        "不以字段齐全证明测量真实准确",
        "不以无记录推断未训练"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STR-30": {
      "metric_id": "STR-30",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kg/kg",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "complete_numerator_and_comparable_body_mass_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "S6",
        "S7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "分子模型误差与体重测量误差都继承；不自动换算跨人体型公平排名。",
        "比值上升可能因减重而非绝对力量增加"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "STATE-SLEEP-MAIN": {
      "metric_id": "STATE-SLEEP-MAIN",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "min",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "no_observed_asleep_intervals"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SLEEP",
        "R4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "设备标签误差不等于统计抽样误差；没有验证资料不输出精确测量CI。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SLEEP-24H": {
      "metric_id": "STATE-SLEEP-24H",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-10T12:00:00+00:00",
        "end": "2026-11-11T12:00:00+00:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "min",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "no_observed_asleep_intervals"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SLEEP",
        "R4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "未记录睡眠不能靠缺失分布恢复。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SLEEP-COVERAGE": {
      "metric_id": "STATE-SLEEP-COVERAGE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "recorded_dates": 0,
        "elapsed_dates": 3,
        "fraction": 0.0
      },
      "unit": "ratio",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 3,
      "n_sessions": 0,
      "count_domain": "local_dates",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "record_coverage_not_wear_time_or_complete_nights"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SLEEP"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "记录可得性指标，不是睡眠时长误差估计。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SLEEP-STAGE": {
      "metric_id": "STATE-SLEEP-STAGE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "stage_minutes": {},
        "annotation_coverage": null,
        "conflicts": []
      },
      "unit": "min; ratio",
      "data_status": "partial",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "episode_boundary_unknown"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SLEEP"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "阶段是算法标签，不能直接测量肌肉恢复。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SLEEP-TIMING": {
      "metric_id": "STATE-SLEEP-TIMING",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "timestamp; clock_min",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "explicit_sleep_episode_boundaries_required"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SLEEP",
        "R4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "片段边界和设备标签误差保留；不产生生物钟诊断。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-RHR": {
      "metric_id": "STATE-RHR",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "beats/min",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "protocol_streams_not_pooled"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_RHR",
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "设备估计误差及日内更新；中位数范围不等于测量CI。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SDNN": {
      "metric_id": "STATE-SDNN",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "ms",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "protocol_streams_not_pooled",
        "SDNN_is_not_RMSSD"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_SDNN",
        "R2a",
        "R2b"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "无NN不能估计原始伪差率；机会采样可有选择偏差。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-REFERENCE-MEDIAN": {
      "metric_id": "STATE-REFERENCE-MEDIAN",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "same_as_metric",
      "data_status": "insufficient",
      "evidence_status": "descriptive",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "baseline_window_equals_requested_window_product_default",
        "current_day_excluded_from_own_reference",
        "equal_weight_per_day"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R5",
        "R8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "H是分析设计，非14天生理定律；参考不确定性由有效样本及漂移决定。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-REFERENCE-MAD": {
      "metric_id": "STATE-REFERENCE-MAD",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "same_as_metric",
      "data_status": "insufficient",
      "evidence_status": "descriptive",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "baseline_window_equals_requested_window_product_default",
        "current_day_excluded_from_own_reference",
        "equal_weight_per_day"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "小样本/强序列相关使离散估计不稳；不等于测量误差。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-DEVIATION": {
      "metric_id": "STATE-DEVIATION",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "original_unit; dimensionless",
      "data_status": "insufficient",
      "evidence_status": "descriptive",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "baseline_window_equals_requested_window_product_default",
        "current_day_excluded_from_own_reference",
        "equal_weight_per_day"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R2a",
        "R2b",
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "z不是概率、诊断或恢复百分比；阈值需独立验证。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-FATIGUE": {
      "metric_id": "STATE-FATIGUE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "ordinal",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "ordinal_observations_not_combined_recovery_score"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "自评误差/背景影响；原创量表不得标临床验证。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-SORENESS": {
      "metric_id": "STATE-SORENESS",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "ordinal",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "ordinal_observations_not_combined_recovery_score"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "酸痛不是肌损伤、有效训练或增肌的直接量。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "STATE-PAIN": {
      "metric_id": "STATE-PAIN",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "categorical",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "ordinal_observations_not_combined_recovery_score"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R5"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "症状记录不提供诊断；数值低不证明训练安全。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "LOAD-SRPE": {
      "metric_id": "LOAD-SRPE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "session_id": 1,
          "session_rpe": 6.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 270.0
        },
        {
          "session_id": 2,
          "session_rpe": 7.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 315.0
        }
      ],
      "unit": "0–10 ordinal",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "sessions",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "set_RPE_not_session_RPE"
      ],
      "source_record_ids": [
        "session:1",
        "session:2"
      ],
      "evidence_refs": [
        "R6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "主观内部反应，非局部机械刺激；延迟影响需评测。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "LOAD-DURATION": {
      "metric_id": "LOAD-DURATION",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "session_id": 1,
          "session_rpe": 6.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 270.0
        },
        {
          "session_id": 2,
          "session_rpe": 7.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 315.0
        }
      ],
      "unit": "min",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "sessions",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "set_RPE_not_session_RPE"
      ],
      "source_record_ids": [
        "session:1",
        "session:2"
      ],
      "evidence_refs": [
        "R6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "计时协议误差不等于生理负荷误差。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "LOAD-SRPE-AU": {
      "metric_id": "LOAD-SRPE-AU",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "session_id": 1,
          "session_rpe": 6.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 270.0
        },
        {
          "session_id": 2,
          "session_rpe": 7.0,
          "duration_minutes": 45.0,
          "duration_source": "user_reported",
          "actual_collection_delay_minutes": 0.0,
          "srpe_protocol": "cr10",
          "duration_protocol": "user_elapsed_including_rest",
          "AU": 315.0
        }
      ],
      "unit": "AU",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "sessions",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "set_RPE_not_session_RPE"
      ],
      "source_record_ids": [
        "session:1",
        "session:2"
      ],
      "evidence_refs": [
        "R6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "不是能量、肌肥大刺激或机械张力。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "BODY-MASS-DAILY": {
      "metric_id": "BODY-MASS-DAILY",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kg",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "comparable_body_mass_observations_missing"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "E1",
        "E2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "秤误差与水分/糖原波动并存，体重不是脂肪量。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "BODY-MASS-TREND": {
      "metric_id": "BODY-MASS-TREND",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kg/week",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "comparable_body_mass_observations_missing"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "E1",
        "E2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "足够数据后方可用验证过的时间块bootstrap；不能以OLS方差冒充Theil–Sen区间。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "BODY-MASS-RELATIVE": {
      "metric_id": "BODY-MASS-RELATIVE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "%/week",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "comparable_body_mass_observations_missing"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "E1"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "继承趋势与参考误差；不代表脂肪下降比例。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "ENERGY-BASAL": {
      "metric_id": "ENERGY-BASAL",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "device_report_not_true_TEE",
        "cross_boundary_samples_not_prorated"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_BASAL",
        "E8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "设备估计误差未知，字段语义不证明真值准确。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "ENERGY-ACTIVE": {
      "metric_id": "ENERGY-ACTIVE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "device_report_not_true_TEE",
        "cross_boundary_samples_not_prorated"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_ACTIVE",
        "E7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "能量准确性不由心率准确性推导；无统一±10%。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "ENERGY-DEVICE-TOTAL": {
      "metric_id": "ENERGY-DEVICE-TOTAL",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "insufficient",
      "evidence_status": "observed",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "same_window_and_stream_components_only",
        "workout_not_added_again",
        "no_TEF_multiplier",
        "device_report_not_true_TEE"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "APPLE_BASAL",
        "APPLE_ACTIVE",
        "E7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "继承系统偏差/随机误差，不能假装两分量误差独立。"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "ENERGY-RECORD-COVERAGE": {
      "metric_id": "ENERGY-RECORD-COVERAGE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": [
        {
          "kind": "basal",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        },
        {
          "kind": "active",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        },
        {
          "kind": "total",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        }
      ],
      "unit": "ratio",
      "data_status": "valid",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 3,
      "n_sessions": 2,
      "count_domain": "dates",
      "coverage": [
        {
          "kind": "basal",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        },
        {
          "kind": "active",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        },
        {
          "kind": "total",
          "numerator": 0,
          "denominator": 3,
          "definition": "recorded valid dates / elapsed target dates, not wear time"
        }
      ],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "APPLE_BASAL",
        "APPLE_ACTIVE"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "100%记录仍可有估计误差或算法填补。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "ENERGY-NET-STORAGE": {
      "metric_id": "ENERGY-NET-STORAGE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "not_identifiable",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "body_mass_does_not_identify_storage",
        "composition_model_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "E1",
        "E2",
        "E8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "组成/能量密度/水分误差；体重稳定也可能重组。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "ENERGY-DELTA-INTAKE": {
      "metric_id": "ENERGY-DELTA-INTAKE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "mass_series_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "E2",
        "E4"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "h=ρq+εl；条件方差hᵀΣh+ε²VarW0−2εCov(hᵀw,W0)，另传播参数/系统误差；非独立W0保留协方差。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "ENERGY-ABSOLUTE-INTAKE": {
      "metric_id": "ENERGY-ABSOLUTE-INTAKE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "kcal/day",
      "data_status": "not_identifiable",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "independent_intake_baseline_or_credible_bias_storage_scenario_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "E2",
        "E3",
        "E4",
        "E7",
        "E8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "区间明确标统计CI/预测区间/场景范围；独立性不成立时保留协方差；场景不冒称95%。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "ENERGY-IDENTIFIABILITY": {
      "metric_id": "ENERGY-IDENTIFIABILITY",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "identified": false,
        "invariant_family": "(I+c, E+c, b-c) leaves D=E+b and Q=I-E unchanged",
        "required_independent_data": [
          "independent equilibrium intake or calibrated device bias",
          "valid composition/storage model"
        ]
      },
      "unit": "categorical",
      "data_status": "not_identifiable",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "E1",
        "E2",
        "E8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "先验形成的后验标conditional，不是观测唯一确定。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "PRED-B0": {
      "metric_id": "PRED-B0",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "reps; RIR separately",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "fixed_task_prediction_target_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R7",
        "R8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "区间仅在严格时间外校准后展示；单点参考无虚假精确CI。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "PRED-B1": {
      "metric_id": "PRED-B1",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "reps",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "fixed_task_prediction_target_required"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R7",
        "R8",
        "R2a",
        "R2b"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "时间外误差/校准区间；参数不稳定与选择过程纳入评测。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "PRED-ERROR-GAIN": {
      "metric_id": "PRED-ERROR-GAIN",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "n_pairs": 0,
        "eligible_n": 0,
        "excluded_n": 0,
        "MAE_B0": null,
        "MAE_B1": null,
        "RMSE_B0": null,
        "RMSE_B1": null,
        "delta_MAE": null,
        "delta_RMSE": null,
        "fallback_n": 0,
        "strata": {},
        "independent_person_effect_validation": false
      },
      "unit": "reps",
      "data_status": "insufficient",
      "evidence_status": "research_only",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 2,
      "count_domain": "paired_test_exposures",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R8",
        "R7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "按用户/时间块计算差异区间，避免重叠窗口伪独立。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "PRED-INTERVAL": {
      "metric_id": "PRED-INTERVAL",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "n": 0,
        "total_n": 0,
        "covered": 0,
        "coverage": null,
        "mean_width": null,
        "strata": {}
      },
      "unit": "ratio; reps",
      "data_status": "insufficient",
      "evidence_status": "research_only",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 2,
      "count_domain": "predicted_intervals",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "覆盖率自身有抽样误差；宽到无用的区间不能只凭覆盖称优。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "REPORT-PERIOD-COVERAGE": {
      "metric_id": "REPORT-PERIOD-COVERAGE",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "daily_coverage": [],
        "session_coverage": [
          {
            "kind": "LOAD-SRPE",
            "numerator": 2,
            "denominator": 2,
            "definition": "known measurements / eligible completed sessions in the window"
          },
          {
            "kind": "LOAD-DURATION",
            "numerator": 2,
            "denominator": 2,
            "definition": "known measurements / eligible completed sessions in the window"
          },
          {
            "kind": "LOAD-SRPE-AU",
            "numerator": 2,
            "denominator": 2,
            "definition": "known measurements / eligible completed sessions in the window"
          }
        ],
        "complete_previous_period_comparable": false
      },
      "unit": "ratio",
      "data_status": "partial",
      "evidence_status": "definition_based",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "current_calendar_period_incomplete"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "APPLE_SLEEP",
        "R6"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "覆盖是可用性而非真实测量准确性。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "REPORT-STATE-SUMMARY": {
      "metric_id": "REPORT-STATE-SUMMARY",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": null,
      "unit": "mixed explicit units",
      "data_status": "insufficient",
      "evidence_status": "descriptive",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "current_calendar_period_incomplete"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R5",
        "R4",
        "R8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "描述统计不是因果作用；小n不提供夸大精度。"
      ],
      "daily_facts": [],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "REPORT-ENERGY-SUMMARY": {
      "metric_id": "REPORT-ENERGY-SUMMARY",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "body_mass_trend": {
          "metric_id": "BODY-MASS-TREND",
          "algorithm_version": "healthzip-science-1.3.0",
          "computed_at": "2026-11-11T12:00:00+00:00",
          "cutoff_time": "2026-11-11T12:00:00+00:00",
          "window": {
            "start": "2026-11-09T00:00:00+08:00",
            "end": "2026-11-16T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "closure": "[start,end)"
          },
          "value": null,
          "unit": "kg/week",
          "data_status": "insufficient",
          "evidence_status": "definition_based",
          "valid_n": 2,
          "total_n": 2,
          "n_sessions": 2,
          "count_domain": "records",
          "coverage": [],
          "uncertainty": {
            "kind": "not_estimated",
            "lower": null,
            "upper": null,
            "level": null,
            "assumptions": []
          },
          "assumptions": [],
          "reason_codes": [
            "comparable_body_mass_observations_missing"
          ],
          "source_record_ids": [
            "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
            "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
          ],
          "evidence_refs": [
            "E1",
            "E2"
          ],
          "parameter_set_id": null,
          "calibration_artifact_id": null,
          "limitations": [
            "足够数据后方可用验证过的时间块bootstrap；不能以OLS方差冒充Theil–Sen区间。"
          ]
        },
        "known_complete_day_energy_sum": null,
        "valid_day_mean": null,
        "valid_complete_days": 0,
        "elapsed_dates": 3,
        "whole_window_delta_intake": {
          "metric_id": "ENERGY-DELTA-INTAKE",
          "algorithm_version": "healthzip-science-1.3.0",
          "computed_at": "2026-11-11T12:00:00+00:00",
          "cutoff_time": "2026-11-11T12:00:00+00:00",
          "window": {
            "start": "2026-11-09T00:00:00+08:00",
            "end": "2026-11-16T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "closure": "[start,end)"
          },
          "value": null,
          "unit": "kcal/day",
          "data_status": "insufficient",
          "evidence_status": "definition_based",
          "valid_n": 2,
          "total_n": 2,
          "n_sessions": 2,
          "count_domain": "records",
          "coverage": [],
          "uncertainty": {
            "kind": "not_estimated",
            "lower": null,
            "upper": null,
            "level": null,
            "assumptions": []
          },
          "assumptions": [],
          "reason_codes": [
            "mass_series_required"
          ],
          "source_record_ids": [
            "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
            "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
          ],
          "evidence_refs": [
            "E2",
            "E4"
          ],
          "parameter_set_id": null,
          "calibration_artifact_id": null,
          "limitations": [
            "h=ρq+εl；条件方差hᵀΣh+ε²VarW0−2εCov(hᵀw,W0)，另传播参数/系统误差；非独立W0保留协方差。"
          ]
        },
        "extrapolated_period_total": null
      },
      "unit": "kg/week; kcal; kcal/day",
      "data_status": "partial",
      "evidence_status": "descriptive",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "current_calendar_period_incomplete"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "E1",
        "E2",
        "E4",
        "E7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "不平均高度重叠ΔEI窗口制造窄CI；模型系统误差保留。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "REPORT-RECOMMENDATION-FOLLOWUP": {
      "metric_id": "REPORT-RECOMMENDATION-FOLLOWUP",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "execution": {
          "metric_id": "STR-27",
          "algorithm_version": "healthzip-science-1.3.0",
          "computed_at": "2026-11-11T12:00:00+00:00",
          "cutoff_time": "2026-11-11T12:00:00+00:00",
          "window": {
            "start": "2026-11-09T00:00:00+08:00",
            "end": "2026-11-16T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "closure": "[start,end)"
          },
          "value": [
            {
              "recommendation_id": "synthetic-demo-candidate",
              "adoption": "partially_adopted",
              "execution_state": "executed",
              "short_term_success": null,
              "reason_codes": [],
              "nonexecution_reason": null,
              "complete": false
            }
          ],
          "unit": "类别与原始差值",
          "data_status": "valid",
          "evidence_status": "definition_based",
          "valid_n": 1,
          "total_n": 1,
          "n_sessions": 2,
          "count_domain": "recommendations",
          "coverage": [],
          "uncertainty": {
            "kind": "not_estimated",
            "lower": null,
            "upper": null,
            "level": null,
            "assumptions": []
          },
          "assumptions": [],
          "reason_codes": [],
          "source_record_ids": [
            "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
            "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
          ],
          "evidence_refs": [
            "R7"
          ],
          "parameter_set_id": null,
          "calibration_artifact_id": null,
          "limitations": [
            "实际结果与推荐依从性可核对；因果效果仍需对照。",
            "短期做成不证明长期增肌有效",
            "不能只保留成功采纳者"
          ]
        },
        "summary": {
          "metric_id": "STR-28",
          "algorithm_version": "healthzip-science-1.3.0",
          "computed_at": "2026-11-11T12:00:00+00:00",
          "cutoff_time": "2026-11-11T12:00:00+00:00",
          "window": {
            "start": "2026-11-09T00:00:00+08:00",
            "end": "2026-11-16T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "closure": "[start,end)"
          },
          "value": {
            "adoption_numerator": 0,
            "adoption_denominator": 1,
            "unanswered": 0,
            "success_numerator": 0,
            "success_denominator": 0,
            "missing_outcomes": 1
          },
          "unit": "比例 / 差值 / 区间",
          "data_status": "valid",
          "evidence_status": "definition_based",
          "valid_n": 0,
          "total_n": 1,
          "n_sessions": 2,
          "count_domain": "recommendations",
          "coverage": [],
          "uncertainty": {
            "kind": "not_estimated",
            "lower": null,
            "upper": null,
            "level": null,
            "assumptions": []
          },
          "assumptions": [],
          "reason_codes": [],
          "source_record_ids": [
            "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
            "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
          ],
          "evidence_refs": [
            "R7",
            "M1"
          ],
          "parameter_set_id": null,
          "calibration_artifact_id": null,
          "limitations": [
            "小分母、同人相关、选择性采纳与缺失影响估计；分别披露，不将比率包装为疗效。",
            "采纳率不能作为唯一优化目标",
            "前后变好不证明是建议导致"
          ]
        },
        "followup_windows": [],
        "causal_effect": null
      },
      "unit": "categorical; outcome units",
      "data_status": "partial",
      "evidence_status": "descriptive",
      "valid_n": 2,
      "total_n": 2,
      "n_sessions": 2,
      "count_domain": "records",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "current_calendar_period_incomplete"
      ],
      "source_record_ids": [
        "strength_set:b0bfe6a2-9ace-571a-8e38-3d1389171f98",
        "strength_set:b54f6c96-1c89-583b-bdf4-12bc3d9b5e05"
      ],
      "evidence_refs": [
        "R7",
        "R8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "回归均值、自然进步、携带效应与选择偏差存在。"
      ],
      "exclusions": [],
      "input_snapshot_n": 2,
      "input_available_n": 2
    },
    "QAL-01": {
      "metric_id": "QAL-01",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "queries": [],
        "macro_group_recall": null,
        "bundle_hit": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "unreviewed_gold_cases": 0
      },
      "unit": "比例 / 完整命中题数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "finite_retrieval_budget_required",
        "gold_review_separate_from_model_output"
      ],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "完整命中是query级二元结果；组召回是0到1的分数，不可直接用二项式区间。总体区间遵循common_output_contract的抽样及聚类条件。同题多次检索/回答不增加独立题数；多组充分方案只是同一题内合法替代，不是多个独立样本。",
        "同论文重复10个chunk不算10份独立支持",
        "命中一条关键词不等于命中充分证据",
        "检索召回达标不证明个体训练建议有效"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-02": {
      "metric_id": "QAL-02",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "queries": [],
        "micro_precision_lower": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "macro_precision_lower": null
      },
      "unit": "比例 / 证据单元数 / token",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "同一query内的单元和同来源chunk相关，不得把所有chunk当独立二项式样本。query级宏平均可在符合抽样设计时整query/整user重采样；小型定向测试只报确切计数。标注争议与抽样不确定性分开。",
        "精度高不证明必要证据已找全",
        "重复文段不能增加独立证据精度或样本量",
        "检索得分不是科学证据等级"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-03": {
      "metric_id": "QAL-03",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "rendered_citation_count": 0,
        "unique_citation_associations": 0,
        "location_rate": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "support_precision": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "judgment_coverage": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "support_labels": {}
      },
      "unit": "比例 / 引用主张链接数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "同回答与同论文中的关联相关，按query/user聚类；引用数增加不等于独立样本增加。定位可由确定性验证给有限集合确切值，语义支持仍有标注误差；二者不应混为一个置信分数。",
        "有DOI不等于该句被支持",
        "引用整篇论文不自动支持全文外推",
        "定位率100%不能抵消错误解释"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-04": {
      "metric_id": "QAL-04",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "claim_support": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "labels": {},
        "intent_coverage": null
      },
      "unit": "比例 / 原子主张数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "主张之间相关，不能用总主张数当独立样本量。标注者分歧与重采样区间分别报告；若从固定30例得支持率，只能描述该集合，不能给出产品总体可靠率结论。",
        "部分支持不按0.5分随意并入支持率",
        "流畅性或引用数量不替代主张审阅",
        "高支持率不等于推荐干预已验证有效"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-05": {
      "metric_id": "QAL-05",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "applicability_error_rate": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "unjudged": 0,
        "error_types": {}
      },
      "unit": "比例 / 错配主张数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [
        "unknown_is_not_scope_match"
      ],
      "source_record_ids": [],
      "evidence_refs": [
        "R3a",
        "R3b",
        "S3",
        "S4",
        "S6",
        "S7"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "错误率是主张级，但总体区间按用户/query聚类。对于决定性条件的专业裁决存在不确定性，保存依据和分歧；不能用模型置信概率替代专家范围审查。",
        "话题相同不等于测量协议可互换",
        "来源证据等级高不自动消除间接性",
        "未知适用信息不默认为满足"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-06": {
      "metric_id": "QAL-06",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "unsupported_numeric": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "causal_overreach": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "unjudged_numeric": 0,
        "unjudged_causal": 0,
        "any_violation_answer_count": 0
      },
      "unit": "比例 / 违规断言数 / 涉及回答数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [
        "S4",
        "S6",
        "R7",
        "R8",
        "M2"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "按query/user聚类并保留分母；关键定向反例是有限集合正确性测试，不需要伪装总体区间。0次观察违规不能证明未来永不违规。",
        "数字有出处不等于它的用途有依据",
        "正确算术不等于正确科学模型",
        "一次建议后改善不证明建议导致改善"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-07": {
      "metric_id": "QAL-07",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "overanswer": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "underanswer": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "labels": {},
        "answerable_intents": 0,
        "insufficient_intents": 0
      },
      "unit": "比例 / 意图数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "两个条件错误率分别给合适区间，不能用多数可答题稀释罕见危险强答。人为平衡验收集的比例不是线上发生率；需要线上代表性抽样或给明确抽样权重才能估计真实平均。",
        "unknown不是自动失败或自动成功",
        "正确拒绝个体百分比不要求拒绝全部解释",
        "空回答不能当合格拒答"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-08": {
      "metric_id": "QAL-08",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "fallback_requests": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "trace_coverage": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "fallback_completion": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "event_count": 0,
        "reason_request_counts": {},
        "incident_clusters": 0
      },
      "unit": "比例 / 请求数 / 回退事件数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "同用户请求、同服务事故引发的大批失败相关；不要以请求总量计算独立二项式窄区间。历史窗口率可精确描述该窗口，预测未来需匹配抽样与时间结构。",
        "合理的证据不足回退不等于模型差",
        "减少回退不能靠强行输出无依据数值",
        "技术重试次数不是用户请求样本量"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-09": {
      "metric_id": "QAL-09",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "overall_fulltext_acquisition": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "licensed_retrievable_fetch": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "theory_review_completion": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "theory_activation_ready": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "feature_claim_coverage": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "source_states": {}
      },
      "unit": "比例 / 来源版本数 / 理论卡数 / 功能主张要求数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [
        "KB1",
        "KB2",
        "KB3",
        "KB5",
        "KB6",
        "KB7",
        "KB8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "这些是冻结工程清单的普查计数，默认不需要抽样置信区间；关键不确定性是身份/权利/审阅是否确实完成，应列状态与复核证据。若只抽查文件质量，抽查合格率是另一估计，不能替换完整清单覆盖。",
        "审核完成不等于审核通过",
        "来源获取率不等于功能理论覆盖率",
        "开放链接不等于当前用途的许可",
        "大量重复理论卡不能增加独立功能覆盖"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-10": {
      "metric_id": "QAL-10",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "request_violation_rate": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "decision_violation_rate": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "blocked_attempts": 0,
        "unverifiable_guard_gap": 0,
        "attack_families": [],
        "release_gate_passed": false
      },
      "unit": "事件数 / 涉及请求比例",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "确定性对抗测试中的任何实际越权均为发布失败；0次观察不等于线上泄漏概率0。多次攻击同一漏洞高度相关，报告攻击家族和独立路径覆盖，不能用重复请求数夸大验证强度。",
        "跨用户事实看似合理仍是越权",
        "科学原文不能授权访问或发送个人数据",
        "多领域路由不必然越权，取决于请求和授权"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-11": {
      "metric_id": "QAL-11",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "numeric_consistency": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "reference_coverage": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "issues": []
      },
      "unit": "比例 / 可核验数值断言数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "确定性算术与单位测试报告精确通过/失败计数，不需伪造统计区间。若从线上随机抽样估计数值错误率，按用户/query聚类并说明抽样；模型预测不确定性和算术一致性是不同问题。",
        "算得一致不证明模型在现实中准确",
        "四舍五入相等不证明不同公式常数相同",
        "同数值不同单位或负荷口径不是一致"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    },
    "QAL-12": {
      "metric_id": "QAL-12",
      "algorithm_version": "healthzip-science-1.3.0",
      "computed_at": "2026-11-11T12:00:00+00:00",
      "cutoff_time": "2026-11-11T12:00:00+00:00",
      "window": {
        "start": "2026-11-09T00:00:00+08:00",
        "end": "2026-11-16T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "closure": "[start,end)"
      },
      "value": {
        "identity_verified": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "active_material_compliance": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "noncompliant_active_ids": [],
        "release_gate_passed": false
      },
      "unit": "比例 / 来源版本数 / 违规激活事件数",
      "data_status": "insufficient",
      "evidence_status": "definition_based",
      "valid_n": 0,
      "total_n": 0,
      "n_sessions": 0,
      "count_domain": "evaluation_units",
      "coverage": [],
      "uncertainty": {
        "kind": "not_estimated",
        "lower": null,
        "upper": null,
        "level": null,
        "assumptions": []
      },
      "assumptions": [],
      "reason_codes": [],
      "source_record_ids": [],
      "evidence_refs": [
        "KB1",
        "KB2",
        "KB3",
        "KB5",
        "KB6",
        "KB7",
        "KB8"
      ],
      "parameter_set_id": null,
      "calibration_artifact_id": null,
      "limitations": [
        "冻结索引与来源清单的完整检查为普查计数，无需抽样CI。未被数据库发现的状态是覆盖限制，不是可用同一比例区间量化的随机误差。若抽样审计，报告抽样设计与未审范围，不能称全部验证。",
        "Crossref有记录不等于全文许可",
        "同DOI不等于同一可替换文本版本",
        "没有撤稿标记不等于保证从未存在问题",
        "旧指南被新指南更新不自动等于撤稿"
      ],
      "exclusions": [],
      "input_snapshot_n": 0,
      "input_available_n": 0
    }
  },
  "cutoff_time": "2026-11-11T12:00:00+00:00",
  "window_start": "2026-11-09T00:00:00+08:00",
  "window_end": "2026-11-16T00:00:00+08:00",
  "period": "week",
  "timezone": "Asia/Shanghai",
  "data_hash": "8a718d9a62f8abd11bbb518e9971ab3771453a03b754ad4cad0b4f7b9d08a668",
  "data_version": "12",
  "algorithm_version": "healthzip-v1.3",
  "legacy_unresolved_inventory": {
    "count": 0,
    "record_ids": [],
    "scope": "current_inventory_not_asof; execution_and_historical_visibility_unknown"
  },
  "retrospective": false
}
```

## 质量与缺口


## 实施限制

- 所有计算在本机完成，未调用 AI API。
- 原始 Apple 健康数据保留来源、单位、时间和导入批次；派生结论带算法版本。
- 需要更多数据时只展示缺口，不生成强行结论。
