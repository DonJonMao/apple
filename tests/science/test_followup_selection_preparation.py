"""As-of preparation preserves revisions, boundaries and unknown visibility."""
import json
from collections import Counter
from copy import deepcopy
from unittest.mock import patch

import pytest

from healthzip.science import contracts


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("retrospective", [False, True])
def test_window_parsing_is_constant_without_changing_selected_record_identities(overlap, retrospective):
    window = contracts.Window("2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00",
                              "2026-11-03T00:00:00Z", "America/New_York")
    rows = [{"id": f"ordinary-{i}", "event_start": "2026-11-01T05:10:00Z",
             "event_end": "2026-11-01T05:20:00Z", "available_at": "2026-11-01T06:00:00Z"}
            for i in range(1000)]
    rows += [
        {"id": "start", "event_end": window.start, "available_at": "2026-11-01T06:00:00Z"},
        {"id": "end", "event_end": window.end, "available_at": "2026-11-02T06:00:00Z"},
        {"id": "unknown", "event_end": "2026-11-01T07:00:00Z", "available_at": None},
        {"id": "old", "source_record_id": "correction", "event_end": "2026-11-01T07:00:00Z",
         "available_at": "2026-11-01T08:00:00Z"},
        {"id": "corrected-future", "source_record_id": "correction", "event_end": "2026-12-01T07:00:00Z",
         "available_at": "2026-11-02T08:00:00Z"},
        {"id": "deleted", "event_end": "2026-11-01T07:00:00Z", "available_at": "2026-11-01T08:00:00Z",
         "record_status": "deleted"},
        {"id": "conflict", "event_end": "2026-11-01T07:00:00Z", "available_at": "2026-11-01T08:00:00Z",
         "conflicted": True},
    ]
    frozen = deepcopy(rows)
    with patch.object(contracts, "instant", wraps=contracts.instant) as parse:
        selected, excluded = contracts.select_as_of(rows, window, overlap=overlap, retrospective=retrospective)
    expected = {f"ordinary-{i}" for i in range(1000)}
    if not overlap:
        expected.add("start")
    if retrospective:
        expected.add("unknown")
    assert {r["_source_id"] for r in selected} == expected
    reasons = {row["id"]: row["reason"] for row in excluded}
    assert reasons["old"] == "superseded_as_of"
    assert reasons["corrected-future"] == "event_after_cutoff"
    assert reasons["end"] == "outside_window"
    assert reasons["deleted"] == "deleted_as_of"
    assert reasons["conflict"] == "unresolved_record_conflict"
    if not retrospective:
        assert reasons["unknown"] == "available_at_unknown"
    else:
        assert next(r for r in selected if r["id"] == "unknown")["_retrospective_snapshot"] is True
    assert rows == frozen
    calls = Counter(call.args[0] for call in parse.call_args_list)
    # One boundary preparation plus that boundary's deliberately placed event.
    assert calls[window.start] <= 3
    assert calls[window.end] <= 3
    # Each ordinary availability is parsed once, then reused for revision rank.
    assert calls["2026-11-01T06:00:00Z"] == 1001


@pytest.mark.parametrize("retrospective", [False, True])
def test_normalized_strength_inputs_match_public_semantic_adapters(retrospective):
    from healthzip.science import engine, semantics
    from tests.science.test_contracts_and_strength import CUTOFF, END, START, row

    records = [row(i, is_reference=False, equipment_instance_id=None) for i in range(1, 10)]
    records += [row(10, actual_json=json.dumps({"rir": 0, "load_value": 35}),
                    condition_json=json.dumps({"load_basis": "assistance_positive"})),
                row(11, actual_json=json.dumps({"rir": 3, "rir_qualifier": "at_least"})),
                row(12, load_basis="per_dumbbell_kg", implement_count=2),
                row(13, load_basis="plates_per_side_kg", symmetric_loading=True, effective_bar_mass_kg=20),
                row(14, available_at=None), row(15, record_status="deleted"), row(16, conflicted=True)]
    frozen = deepcopy(records)
    arguments = dict(cutoff_time=CUTOFF, window_start=START, window_end=END,
                     context={"retrospective": retrospective})
    metric_ids = [f"STR-{i:02}" for i in range(1, 31)]
    with patch.object(semantics, "flatten_record", wraps=semantics.flatten_record) as prepare:
        actual = engine.evaluate_subset(metric_ids, records, **arguments)
    prepared_calls = prepare.call_count
    calculator = engine.strength_metric

    def direct_semantics(*args, **kwargs):
        kwargs["_normalized"] = False
        return calculator(*args, **kwargs)

    with patch.object(engine, "strength_metric", direct_semantics), \
            patch.object(semantics, "flatten_record", wraps=semantics.flatten_record) as prepare:
        expected = engine.evaluate_subset(metric_ids, records, **arguments)

    def without_clock(value):
        if isinstance(value, dict):
            return {k: without_clock(v) for k, v in value.items() if k != "computed_at"}
        if isinstance(value, list):
            return [without_clock(v) for v in value]
        return value

    assert prepared_calls < prepare.call_count
    assert without_clock(actual) == without_clock(expected)
    assert len(actual) == 30
    assert records == frozen


def test_load_arithmetic_is_shared_only_within_one_selected_request():
    from healthzip.science import engine, strength
    from tests.science.test_contracts_and_strength import CUTOFF, END, START, row

    records = [row(1, is_reference=False, load_value=40, rir=0),
               row(2, is_reference=False, load_basis="assistance_setting", load_value=35),
               row(3, is_reference=False, load_basis="plates_per_side_kg", load_value=20,
                   symmetric_loading=True, effective_bar_mass_kg=20),
               row(4, is_reference=False, load_value=None)]
    arguments = dict(cutoff_time=CUTOFF, window_start=START, window_end=END)
    mids = ["STR-03", "STR-04", "STR-16", "STR-17"]
    with patch.object(strength, "_load_components", wraps=strength._load_components) as calculate:
        first = engine.evaluate_subset(mids, records, **arguments)
    assert calculate.call_count == len(records)
    loads = first["STR-03"]["value"]
    assert [r["total_load_kg"] for r in loads] == [40, None, 60, None]
    assert loads[1]["assistance_kg"] == 35
    assert "larger_value_means_more_assistance" in loads[1]["reason_codes"]
    assert "load_missing" in loads[3]["reason_codes"]
    loads[0]["reason_codes"].append("caller mutation")
    records[0]["load_value"] = 42
    with patch.object(strength, "_load_components", wraps=strength._load_components) as calculate:
        later = engine.evaluate_subset(mids, records, **arguments)
    assert calculate.call_count == len(records)
    assert later["STR-03"]["value"][0]["total_load_kg"] == 42
    assert "caller mutation" not in later["STR-03"]["value"][0]["reason_codes"]
    assert first["STR-03"]["value"][0]["total_load_kg"] == 40
