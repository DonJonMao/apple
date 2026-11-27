"""The ordinary inventory fast path equals the public STR-11 calculator."""
from unittest.mock import patch

import pytest

from healthzip.science import engine
from healthzip.science.contracts import Window, select_as_of
from healthzip.science.semantics import flatten_record
from healthzip.workflows.contracts import scientific_identity
from tests.science.test_contracts_and_strength import row

WINDOW = Window("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")


def calculated(rows, context):
    return engine.evaluate("STR-11", rows, cutoff_time=WINDOW.cutoff_time,
                           window_start=WINDOW.start, window_end=WINDOW.end, context=context)


@pytest.mark.parametrize("retrospective", [False, True])
def test_ordinary_reference_batch_matches_public_calculator_with_asof_and_context(retrospective):
    originals = [row(1, is_reference=False), row(2, is_reference=False, equipment_instance_id=None),
        row(3, is_reference=False, available_at=None), row(4, is_reference=False, record_status="deleted"),
        row(5, is_reference=False, conflicted=True), row(6, is_reference=True),
        row(7, is_reference=False, available_at="2026-12-01T00:00:00Z")]
    context = {"timezone": "UTC", "retrospective": retrospective,
               "comparison_pair": [row(8, available_at="2026-12-01T00:00:00Z")]}
    selected, excluded = select_as_of([flatten_record(r) for r in originals], WINDOW, retrospective=retrospective)
    assert len(selected) == (4 if retrospective else 3)
    assert {e["reason"] for e in excluded} >= {"deleted_as_of", "unresolved_record_conflict", "available_after_cutoff"}
    bounded = engine._bounded_context(context, WINDOW)
    templates = {}
    for item in selected:
        expected = calculated([item], context)
        actual = engine._ordinary_reference_result([item], WINDOW, context, bounded, templates)
        assert scientific_identity(actual) == scientific_identity(expected)
        assert actual["source_record_ids"] == [item["_source_id"]]


def test_explicit_reference_nomination_does_not_reuse_absence_template():
    records, _ = select_as_of([flatten_record(row(i, is_reference=False)) for i in (1, 2)], WINDOW)
    templates = {}
    empty_context = {"timezone": "UTC"}
    absent = engine._ordinary_reference_result([records[0]], WINDOW, empty_context,
                                               engine._bounded_context(empty_context, WINDOW), templates)
    assert absent["value"] is None
    context = {"timezone": "UTC", "reference_set_ids": [records[1]["set_id"]]}
    actual = engine._ordinary_reference_result([records[1]], WINDOW, context,
                                               engine._bounded_context(context, WINDOW), templates)
    assert actual["valid_n"] == 1
    assert scientific_identity(actual) == scientific_identity(calculated([records[1]], context))


def test_thousand_unknown_tasks_keep_ids_without_thousand_metric_executions():
    context = {"timezone": "UTC"}
    bounded = engine._bounded_context(context, WINDOW)
    # All records are in the same real time interval but their unknown
    # conditions retain distinct task and source identities.
    records = [row(1, id=f"unknown-{i}", set_id=f"unknown-{i}", session_id=f"session-{i // 4}",
                   is_reference=False, equipment_instance_id=None) for i in range(1000)]
    selected, _ = select_as_of([flatten_record(r) for r in records], WINDOW)
    templates = {}
    with patch.object(engine, "evaluate", wraps=engine.evaluate) as executor:
        results = [engine._ordinary_reference_result([r], WINDOW, context, bounded, templates) for r in selected]
    assert executor.call_count == 1
    assert len(results) == 1000
    assert {rid for result in results for rid in result["source_record_ids"]} == {r["id"] for r in records}
    assert all(r["valid_n"] == 0 and r["total_n"] == 1 and r["n_sessions"] == 1 for r in results)
    results[0]["evidence_refs"].append("caller change")
    results[0]["reason_codes"].append("caller change")
    results[0]["window"]["timezone"] = "caller change"
    assert "caller change" not in results[1]["evidence_refs"]
    assert "caller change" not in templates["no_designated_reference"]["reason_codes"]
    assert results[1]["window"]["timezone"] == "UTC"


def test_clone_matches_deepcopy_and_isolates_nested_aliases():
    from copy import deepcopy

    from healthzip.science.contracts import validate_result

    prototype = calculated([row(1, is_reference=False)], {"timezone": "UTC"})
    shared = [{"values": [1.25, None, False, "measured"]}]
    prototype["assumptions"] = prototype["uncertainty"]["assumptions"] = shared
    pair = (shared, ("immutable", 7, None))
    prototype["copy_contract_probe"] = {"pair": pair, "same_pair": pair}
    validate_result(prototype)
    expected = deepcopy(prototype)
    actual = engine._clone_ordinary_reference_result(prototype)
    sibling = engine._clone_ordinary_reference_result(prototype)
    assert actual == expected == sibling == prototype
    assert type(actual["copy_contract_probe"]["pair"]) is tuple
    assert actual["copy_contract_probe"]["pair"] is actual["copy_contract_probe"]["same_pair"]
    assert actual["assumptions"] is actual["uncertainty"]["assumptions"]
    assert actual["assumptions"] is actual["copy_contract_probe"]["pair"][0]
    assert actual["assumptions"] is not shared
    assert actual["copy_contract_probe"]["pair"][1] is pair[1]  # deepcopy reuses this immutable tuple.
    actual["copy_contract_probe"]["pair"][0][0]["values"].append("only this result")
    actual["window"]["timezone"] = "caller mutation"
    assert prototype == expected == sibling
    assert "only this result" not in shared[0]["values"]


@pytest.mark.parametrize("base_type,initial", [(dict, {}), (list, []), (str, "label")])
@pytest.mark.parametrize("subclass_first", [False, True])
def test_clone_preserves_subclass_metadata_and_aliases_across_fallback(base_type, initial, subclass_first):
    from copy import deepcopy

    class Annotated(base_type):
        pass

    shared = {"notes": ["original"]}
    annotated = Annotated(initial)
    annotated.metadata = shared
    items = [("annotated", annotated), ("shared", shared)]
    prototype = dict(items if subclass_first else reversed(items))
    actual = engine._clone_ordinary_reference_result(prototype)
    expected = deepcopy(prototype)
    assert actual == expected
    assert type(actual["annotated"]) is type(expected["annotated"]) is Annotated
    assert actual["annotated"].metadata == expected["annotated"].metadata
    assert actual["annotated"].metadata is actual["shared"]
    assert actual["shared"] is not shared
    actual["annotated"].metadata["notes"].append("caller change")
    assert shared == {"notes": ["original"]}


def test_reference_reuse_remains_exact_to_normal_evaluation_and_validates_every_copy(monkeypatch):
    from datetime import datetime, timezone

    from healthzip.science import contracts

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 2, 4, 5, 6, tzinfo=timezone.utc)

    monkeypatch.setattr(contracts, "datetime", FixedClock)
    context = {"timezone": "UTC", "comparison_pair": [row(8, available_at="2026-12-01T00:00:00Z")]}
    bounded = engine._bounded_context(context, WINDOW)
    templates = {}
    for indexes in ((1,), (2, 3, 4), (5, 6)):
        records = [row(i, is_reference=False, equipment_instance_id=None, rir=None) for i in indexes]
        selected, _ = select_as_of([flatten_record(r) for r in records], WINDOW)
        expected = calculated(records, context)
        actual = engine._ordinary_reference_result(selected, WINDOW, context, bounded, templates)
        assert actual == expected  # Includes algorithm/selection versions, source IDs and all fields.
        actual["uncertainty"]["assumptions"].append("caller mutation")
        assert templates["no_designated_reference"]["uncertainty"]["assumptions"] == []
    templates["no_designated_reference"]["valid_n"] = 20
    with pytest.raises(ValueError, match="invalid_denominator"):
        engine._ordinary_reference_result(selected, WINDOW, context, bounded, templates)


def test_clone_preserves_string_subclass_key_metadata_without_sharing_mutable_values():
    from copy import deepcopy

    class AnnotatedKey(str):
        pass

    shared = {"notes": ["recorded condition"]}
    key = AnnotatedKey("condition")
    key.metadata = shared
    prototype = {"before": shared, key: {"same": shared}}
    actual = engine._clone_ordinary_reference_result(prototype)
    expected = deepcopy(prototype)
    assert actual == expected
    actual_key = next(k for k in actual if type(k) is AnnotatedKey)
    expected_key = next(k for k in expected if type(k) is AnnotatedKey)
    assert actual_key is not key
    assert actual_key.metadata == expected_key.metadata
    assert actual_key.metadata is actual["before"] is actual[key]["same"]
    assert actual_key.metadata is not shared
    actual_key.metadata["notes"].append("only this result")
    assert key.metadata == {"notes": ["recorded condition"]}
