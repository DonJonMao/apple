"""Normalization is prepared once per semantic operation, with unchanged identities."""
import copy
import json
from unittest.mock import patch

import pytest

from healthzip.science import semantics
from tests.science.test_contracts_and_strength import row


@pytest.mark.parametrize("operation", ["analysis_task", "outcome_series", "load_components", "condition_key"])
def test_one_record_is_normalized_once_per_semantic_operation(operation):
    record = row()
    with patch.object(semantics, "flatten_record", wraps=semantics.flatten_record) as prepare:
        value = getattr(semantics, operation)(record)
    assert value
    assert prepare.call_count == 1


@pytest.mark.parametrize("operation", ["comparable", "load_change"])
def test_comparison_prepares_each_record_once(operation):
    old, new = row(load_value=60), row(2, load_value=65)
    with patch.object(semantics, "flatten_record", wraps=semantics.flatten_record) as prepare:
        value = getattr(semantics, operation)(old, new)
    assert value
    assert prepare.call_count == 2


def test_nested_json_normalization_keeps_rir_zero_ranges_and_load_direction():
    record = row(load_value=999, rir=9)
    record["condition_json"] = json.dumps({"load_basis": "assistance_positive", "measurement_mode": "dynamic_reps"})
    record["actual_json"] = json.dumps({"load_value": 40, "rir": 0, "reps": 8, "stop_reason": "target_rir"})
    frozen = copy.deepcopy(record)
    normalized = semantics.flatten_record(record)
    assert (normalized["rir"], normalized["load_basis"], normalized["measurement_mode"]) == (0, "assistance_setting", "repetitions")
    assert semantics.load_components(record)["assistance_kg"] == 40
    next_record = {**record, "actual_json": json.dumps({"load_value": 35, "rir": 0, "reps": 8, "stop_reason": "target_rir"})}
    change = semantics.load_change(record, next_record)
    assert change["entered_change"] == -5 and change["direction"] == "harder"
    assert record == frozen
    record["actual_json"] = json.dumps({"load_value": 37, "rir": 3, "rir_qualifier": "at_least", "reps": 8})
    assert semantics.load_components(record)["assistance_kg"] == 37
    normalized = semantics.flatten_record(record)
    assert normalized["rir"] is None and normalized["rir_interval"] == {"lower": 3, "upper": None}


def test_unknown_conditions_keep_distinct_record_identity_and_output_isolation():
    first, second = row(1, equipment_instance_id=None), row(2, equipment_instance_id=None)
    a, b = semantics.analysis_task(first), semantics.analysis_task(second)
    assert a["condition_key"] is b["condition_key"] is None
    assert a["task_id"] != b["task_id"]
    outcome = semantics.outcome_series(first)
    outcome["reason_codes"].append("caller mutation")
    assert "caller mutation" not in semantics.outcome_series(first)["reason_codes"]
