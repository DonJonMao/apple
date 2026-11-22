"""Independent public-calculator equivalence for shared task preparation."""

from contextlib import closing

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate, evaluate_all
from healthzip.science.contracts import Window, select_as_of
from healthzip.science.engine import TASK_METRICS
from healthzip.science.semantics import analysis_task, flatten_record
from healthzip.workflows.contracts import scientific_identity
from tests.health_change_fixture import CUTOFF, create_health_change_fixture
from tests.science.test_contracts_and_strength import row


def test_reference_task_preparation_preserves_all_public_metric_results():
    records = [row(i) for i in range(1, 8)]
    records += [row(8, equipment_instance_id="other-bar"), row(9, equipment_instance_id=None),
                row(10, equipment_instance_id=None)]
    window = Window("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")
    context = {"timezone": "UTC", "data_version": "test", "daily_metric_facts": [],
               "energy_days": [], "sleep_episodes": []}
    args = {"cutoff_time": window.cutoff_time, "window_start": window.start, "window_end": window.end}
    batch = evaluate_all(records, context=context, **args)
    normalized = [flatten_record(r) for r in records]
    visible, _ = select_as_of(normalized, window)
    groups = {}
    for record in visible:
        groups.setdefault(analysis_task(record)["task_id"], []).append(record)
    assert len(groups) == 4  # Two unknown-condition records remain different tasks.
    for mid in TASK_METRICS:
        children = {task["task_id"]: task for task in batch[mid]["task_results"]}
        assert set(children) == set(groups)
        for identity, group in groups.items():
            child = children[identity]
            expected = evaluate(mid, group, context={**context, "task_id": identity,
                "reference_inventory": normalized, "data_snapshot_hash": child["data_snapshot_hash"]}, **args)
            assert scientific_identity(child["metric"]) == scientific_identity(expected), (mid, identity)


def test_ordinary_task_preparation_preserves_public_execution_without_merging_unknowns(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    with closing(Repository(path)) as repo:
        batch = analyze(repo, cutoff_time=CUTOFF, use_cache=False)
        records, inherited = snapshot(repo, CUTOFF, window_start=batch["window_start"], window_end=batch["window_end"])
        window = Window(batch["window_start"], batch["window_end"], CUTOFF, batch["timezone"])
        visible, _ = select_as_of([flatten_record(r) for r in records if r.get("record_kind") == "strength_set"], window)
        groups = {}
        for record in visible:
            groups.setdefault(analysis_task(record)["task_id"], []).append(record)
        assert len(groups) == len(batch["strength_tasks"]) == 12
        args = {"cutoff_time": CUTOFF, "window_start": window.start, "window_end": window.end}
        for task in batch["strength_tasks"]:
            assert task["condition_key"] is None
            context = {**inherited, "plan_snapshot": None, "timezone": batch["timezone"],
                       "task_id": task["task_id"], "data_snapshot_hash": task["data_snapshot_hash"]}
            for mid in TASK_METRICS:
                expected = evaluate(mid, groups[task["task_id"]], context=context, **args)
                assert scientific_identity(task["metrics"][mid]) == scientific_identity(expected), (mid, task["task_id"])
