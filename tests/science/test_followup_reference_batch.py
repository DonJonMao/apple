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
