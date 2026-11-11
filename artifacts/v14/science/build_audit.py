"""Rebuild the non-QAL metric audit from checked-in specifications and test XML.

Run from the repository root with the project Python after the documented suite.
No private records, user database, scientific-validation claim or network access.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from healthzip.science import evaluate_all

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/v14/science"
matrix = json.loads((ROOT / "Apple_v1.4_Codex_Execution_Pack/metric_revision_matrix.json").read_text())
metrics = [m for m in matrix["metrics"] if not m["metric_id"].startswith("QAL-")]
assert len(metrics) == 65

extra = {}
def link(ids, *names):
    for identity in ids.split():
        extra.setdefault(identity, []).extend("tests/science/test_v14_science.py::" + name for name in names)

link("STATE-RHR STATE-SDNN STATE-REFERENCE-MEDIAN STATE-REFERENCE-MAD STATE-DEVIATION BODY-MASS-DAILY BODY-MASS-TREND BODY-MASS-RELATIVE REPORT-STATE-SUMMARY",
     "test_f01_legacy_unverified_normalized_number_is_reprocessed_only_from_known_raw_unit", "test_f01_missing_or_unknown_units_never_enter_daily_baselines")
link("STATE-SLEEP-MAIN STATE-SLEEP-24H STATE-SLEEP-STAGE REPORT-STATE-SUMMARY", "test_f09_irrelevant_inbed_source_does_not_block_asleep_observation")
link("STATE-SLEEP-COVERAGE REPORT-PERIOD-COVERAGE ENERGY-RECORD-COVERAGE", "test_f02_sleep_coverage_uses_clipped_half_open_local_dates", "test_f02_one_metric_failure_does_not_abort_independent_analysis")
link("STR-07 STR-08 STR-29", "test_f07_exposure_layers_and_training_frequency_include_ordinary_sessions")
link("STR-05 STR-06", "test_muscle_counts_consume_frozen_mapping_versions_and_ignore_live_context",
     "test_invalid_or_late_mapping_snapshot_stays_unknown", "test_same_mapping_version_cannot_have_contradictory_frozen_content")
link("STR-15", "test_within_session_repetition_change_uses_actual_mass_not_equal_unit_labels")
link("STR-12 STR-14", "test_f07_intervening_load_does_not_hide_same_load_raw_change")
link("STR-03 STR-13 STR-19 STR-20 STR-22 STR-24", "test_f07_multiple_loads_preserve_separate_descriptive_series", "test_f07_equivalent_exact_mass_units_share_series_without_losing_raw_values")
link("STR-20 STR-24", "test_f07_series_receipt_cannot_be_reused_for_another_load_or_cutoff")
link("STR-21 STR-22 PRED-B1", "test_f08_scope_subset_cannot_broaden_calibration_and_audit_fields_do_not_narrow_it", "test_f08_actual_task_scope_wins_over_contradictory_caller_labels", "test_f08_str22_rejects_same_equivalence_unit_mismatch_as_str21")
link("STR-11 STR-23 STR-25 STR-26 STATE-PAIN", "test_f04_restricted_or_unknown_reference_cannot_license_harder_task", "test_f03_current_nonreference_observation_vetoes_good_historical_baseline", "test_f03_current_unknown_observation_timestamp_cannot_disappear_as_empty_normal_context")
link("STR-25 STR-26", "test_candidate_requires_specific_rule_action_permission")
link("STR-25", "test_double_progression_partial_or_invalid_plan_has_no_numeric_task")
link("STR-26", "test_optional_trial_rir_preserves_unknown_and_blocks_invalid_effort_target")
link("STR-26", "test_repetition_trial_uses_only_explicit_higher_user_upper_target", "test_repetition_trial_current_symptoms_or_unknown_block_numeric_target")
link("STR-18", "test_metric_matrix_retest_requires_same_task_and_reports_zero_error_limit")
link("STR-30", "test_metric_matrix_relative_strength_requires_verified_mass_and_numerator_unit")
link("ENERGY-BASAL ENERGY-ACTIVE ENERGY-DEVICE-TOTAL REPORT-ENERGY-SUMMARY", "test_f01_registry_and_runtime_agree_cumulative_energy_is_kcal")
link("ENERGY-IDENTIFIABILITY", "test_metric_matrix_independent_flags_do_not_establish_energy_identifiability")
link("ENERGY-ABSOLUTE-INTAKE", "test_metric_matrix_each_energy_scenario_bound_must_be_ordered")
link("LOAD-DURATION LOAD-SRPE-AU", "test_metric_matrix_elapsed_and_pause_adjusted_duration_are_distinct")
link("REPORT-PERIOD-COVERAGE", "test_period_coverage_preserves_source_protocol_denominators_without_double_counting_dates")
link("STR-27 STR-28 REPORT-RECOMMENDATION-FOLLOWUP", "test_metric_matrix_followup_strata_keep_unknown_and_unique_candidate_denominators")
for identity in "ENERGY-BASAL ENERGY-ACTIVE ENERGY-DEVICE-TOTAL STATE-SDNN BODY-MASS-DAILY REPORT-ENERGY-SUMMARY".split():
    extra.setdefault(identity, []).append("tests/integration/test_v14_science_import.py::test_f01_real_import_checks_units_before_energy_and_physiology")
for identity in "STATE-SLEEP-MAIN STATE-SLEEP-24H REPORT-STATE-SUMMARY".split():
    extra.setdefault(identity, []).append("tests/integration/test_v14_science_import.py::test_f09_actual_zip_with_inbed_phone_and_asleep_watch")
extra.setdefault("STR-19", []).append("tests/integration/test_v14_science_import.py::test_f07_real_training_service_preserves_load_layers_in_analysis")
extra.setdefault("STR-25", []).append("tests/integration/test_v14_advice_flow.py::test_partial_visible_targets_freeze_missing_conditions_without_crashing")
extra.setdefault("STR-26", []).append("tests/integration/test_v14_choice_validation.py::test_repetition_choice_cannot_silently_change_load")
for identity in ("STR-07", "STR-08"):
    extra.setdefault(identity, []).append("tests/integration/test_v14_period_review.py::test_recorded_frequency_counts_local_observation_dates")
extra.setdefault("STR-20", []).append("tests/integration/test_v14_period_review.py::test_interval_without_look_keeps_observed_point_estimate")
for identity in ("STR-19", "STR-22", "REPORT-PERIOD-COVERAGE"):
    extra.setdefault(identity, []).append("tests/integration/test_v14_period_review.py::test_e2e06_visible_period_report_shows_its_own_load_layers")
for identity in ("STR-05", "STR-06"):
    extra.setdefault(identity, []).append("tests/integration/test_v14_anatomy_history.py::test_str05_06_real_history_keeps_mapping_versions_and_unknown_legacy")

# JUnit can embed local usernames/absolute paths in failures and metadata.
for path in OUT.glob("*.xml"):
    value = path.read_text()
    value = value.replace(str(ROOT), "<workspace>")
    value = re.sub(r"/tmp/pytest-of-[^/\s]+", "<pytest-temp>", value)
    value = re.sub(r' hostname="[^"]*"', '', value)
    value = value.replace("<workspace>", "[workspace]").replace("<pytest-temp>", "[pytest-temp]")
    path.write_text(value)
suite = ET.parse(OUT / "verification.xml").getroot()
cases = list(suite.iter("testcase"))
passed = {c.attrib["name"] for c in cases if not any(c.find(k) is not None for k in ("failure", "error", "skipped"))}
assert len(passed) == len(cases), "verification must have no failures, errors or skips"
def verified(reference):
    name = reference.split("::")[-1]
    return name in passed or any(case.split("[")[0] == name for case in passed)

empty = evaluate_all([], cutoff_time="2026-11-11T12:00:00Z", window_start="2026-11-01T00:00:00Z", window_end="2026-11-12T00:00:00Z")
rows = []
for metric in metrics:
    identity = metric["metric_id"]
    references = metric["existing_test_refs"] + extra.get(identity, [])
    assert all(verified(r) for r in references), (identity, [r for r in references if not verified(r)])
    assert "metric_execution_failed" not in empty[identity]["reason_codes"]
    files = [r["path"] for r in metric["implementation_refs"]]
    rows.append({"metric_id": identity, "revision_action": metric["revision_action"],
                 "planned_behavior_reviewed": metric["planned_behavior"],
                 "targeted_acceptance_reviewed": metric["targeted_acceptance"],
                 "review_result": "implementation_reviewed_and_bounded_software_cases_passed",
                 "runtime_unit": empty[identity]["unit"], "empty_input_data_status": empty[identity]["data_status"],
                 "implementation_paths": files, "passed_test_refs": references,
                 "scientific_validation_boundary": metric["scientific_validation_boundary"],
                 "coverage_limit": "The linked cases cover specified inputs; they are not proof of every possible input, full UI acceptance, source-rule review, personal prediction validity or causal benefit."})
summary = {"review_baseline": matrix["review_head"], "metric_count": len(rows),
           "algorithm_version": next(iter(empty.values()))["algorithm_version"],
           "verification_test_cases": len(cases), "all_verification_cases_passed": True,
           "new_real_calibration_artifacts_created": 0, "new_human_or_expert_approvals_created": 0,
           "scope": "science/normalize and bounded real-entry synthetic import/TrainingService tests; root owns final UI/knowledge integration",
           "metrics": rows}
(OUT / "metric_audit_65.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"metric_count": len(rows), "passed_cases": len(cases), "real_calibrations_created": 0}))
