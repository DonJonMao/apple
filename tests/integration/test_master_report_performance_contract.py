"""Report reuse preserves source revisions, independent tasks and frozen history."""
import json
import math
from contextlib import closing

from healthzip.analytics.cache import clear
from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.science.engine import evaluate_subset
from healthzip.workflows.contracts import scientific_identity
from healthzip.workflows.period_report import (
    _decode_content,
    _fast_json_compatible,
    create_report,
    load_report,
)
from healthzip.workflows.report_inputs import period_facts, shared_report_inputs
from healthzip.workflows.storage import load_run
from tests.health_change_fixture import CUTOFF, create_health_change_fixture


def test_subset_preparation_matches_independent_metric_execution(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    with closing(Repository(path)) as repo:
        rows, context = snapshot(repo, CUTOFF, window_start="2026-11-16T00:00:00+08:00", window_end=CUTOFF)
        args = {"cutoff_time": CUTOFF, "window_start": "2026-11-16T00:00:00+08:00", "window_end": CUTOFF,
                "context": {**context, "timezone": "Asia/Shanghai"}}
        mids = ["STR-01", "STR-09", "STR-11", "STR-19", "STR-20", "STR-22", "STR-24", "STATE-SLEEP-24H", "STATE-RHR"]
        shared = evaluate_subset(mids, rows, **args)
        for mid in mids:
            assert scientific_identity(shared[mid]) == scientific_identity(evaluate(mid, rows, **args))


def test_fast_report_decoder_preserves_extremes_and_unknown_metadata(monkeypatch):
    from healthzip.workflows import period_report
    ordinary = {"unknown_vendor_metadata": {"unicode": "合成🧪", "values": [-2**63, 2**64-1, 5e-324, 1.7976931348623157e308, -0.0, None, True]}}
    assert _fast_json_compatible(ordinary)
    encoded = json.dumps(ordinary, ensure_ascii=False)
    assert _decode_content(encoded, True) == json.loads(encoded)
    assert math.copysign(1, _decode_content(encoded, True)["unknown_vendor_metadata"]["values"][4]) == -1
    unsafe = {"unknown_vendor_metadata": {"big": 2**100, "negative": -(2**100), "nan": float("nan"), "infinity": float("inf")}}
    assert not _fast_json_compatible(unsafe)
    decoded = _decode_content(json.dumps(unsafe), False)["unknown_vendor_metadata"]
    assert type(decoded["big"]) is int and decoded["big"] == 2**100 and decoded["negative"] == -(2**100)
    assert math.isnan(decoded["nan"]) and decoded["infinity"] == float("inf")
    monkeypatch.setattr(period_report, "orjson", None)
    assert _decode_content(encoded, True) == json.loads(encoded)


def test_report_replay_cache_keeps_public_results_mutably_isolated(tmp_path):
    from healthzip.training.service import TrainingService, report_event_reads
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    with closing(Repository(path)) as repo, report_event_reads(repo):
        service = TrainingService(repo)
        first = service.events_as_of(cutoff_time=CUTOFF)
        expected = json.loads(json.dumps(first))
        first[0]["after"]["caller_only"] = {"mutable": [42]}
        second = service.events_as_of(cutoff_time="2026-11-21T16:00:00+00:00")
        assert second == expected
        second.clear()
        assert service.events_as_of(cutoff_time=CUTOFF) == expected
        future_cutoff = "2100-01-01T00:00:00+00:00"
        before_change = service.events_as_of(cutoff_time=future_cutoff)
        row = service.get_set(repo.one("SELECT id FROM strength_set LIMIT 1")[0])
        service.delete_set(row["id"], base_revision=row["revision"])
        after_change = service.events_as_of(cutoff_time=future_cutoff)
        assert len(after_change) > len(before_change)
        assert service.events_as_of(cutoff_time=CUTOFF) == expected


def test_baseline_variant_matches_all_independent_canonical_metrics(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    with closing(Repository(path)) as repo:
        context = {"baseline_window": {"start": "2026-10-25T00:00:00+08:00", "end": CUTOFF,
                    "timezone": "Asia/Shanghai"}, "baseline_completed_days": 28}
        expected = analyze(repo, cutoff_time=CUTOFF, period="week", context=context, use_cache=False)
        with shared_report_inputs(repo):
            actual = period_facts(repo, cutoff_time=CUTOFF, period="week", context=context)
        for mid in expected["metrics"]:
            assert scientific_identity(actual["metrics"][mid]) == scientific_identity(expected["metrics"][mid]), mid


def test_report_batch_preserves_all_global_metrics_and_each_actual_task(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    clear()
    with closing(Repository(path)) as repo:
        expected = analyze(repo, cutoff_time=CUTOFF, period="week", use_cache=False)
        report = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"},
                               period="week", knowledge_root=tmp_path / "empty-knowledge")
        assert len(report["current"]["metrics"]) == 77
        assert scientific_identity(report["current"]["metrics"]) == scientific_identity(expected["metrics"])
        expected_tasks = {task["task_id"]: task for task in expected["strength_tasks"]}
        actual_tasks = {task["task_id"]: task for task in report["current"]["strength_tasks"]}
        assert set(actual_tasks) == set(expected_tasks)
        for key, task in actual_tasks.items():
            assert task["source_record_ids"] == expected_tasks[key]["source_record_ids"]
            assert task["input_data_hash"] == expected_tasks[key]["input_data_hash"]
            assert scientific_identity(task["metrics"]["STR-11"]) == scientific_identity(expected_tasks[key]["metrics"]["STR-11"])
            assert task["task_metrics_scope"] == "requested_only"
        runs = [load_run(repo, key) for key in report["workflow_run_ids"]]
        inventory = [run for run in runs if run["request"].get("ordinary_inventory")]
        assert len(inventory) == 1
        assert {task["task_id"] for task in inventory[0]["task_selection"]["inventory_tasks"]} == set(expected_tasks)
        assert inventory[0]["nodes"][2]["long_term_review_trigger"] is False
        source_ids = {source for task in actual_tasks.values() for source in task["source_record_ids"]}
        actual_ids = {row["id"] for ctx in inventory[0]["supplements"]["training_session_contexts"] for row in ctx["actual_records"]}
        assert actual_ids == source_ids


def test_hot_report_is_new_freeze_and_source_correction_invalidates_content(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    clear()
    with closing(Repository(path)) as repo:
        fields = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        kwargs = {"period": "week", "knowledge_root": tmp_path / "empty-knowledge"}
        first = create_report(repo, fields, **kwargs)
        progress = []
        second = create_report(repo, fields, progress=progress.append, **kwargs)
        assert first["report_id"] != second["report_id"]
        assert first["markdown"] == second["markdown"]
        assert first["content_signature"] == second["content_signature"]
        stored = json.loads(repo.one("SELECT payload_json FROM joint_period_report WHERE report_id=?", (second["report_id"],))[0])
        assert stored == {key: value for key, value in second.items() if key != "markdown"}
        assert "复用已核对的报告内容" in progress
        row = repo.one("SELECT payload_json FROM source_revision WHERE table_name='health_sample' AND record_id=1")
        corrected = json.loads(row[0])
        corrected.update(normalized_value=71, raw_value="71")
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                          "VALUES('health_sample',1,?,?,'synthetic_correction')", (CUTOFF, json.dumps(corrected)))
        repo.conn.commit()
        progress = []
        third = create_report(repo, fields, progress=progress.append, **kwargs)
        assert "复用已核对的报告内容" not in progress
        assert third["current"]["data_hash"] != first["current"]["data_hash"]
        assert load_report(repo, first["report_id"]) == first
