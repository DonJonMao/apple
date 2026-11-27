"""Workflow storage sharing preserves actual records and offline historical reads."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

from healthzip.analytics.cache import clear
from healthzip.db.repository import Repository
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, load_run, run_workflow
from healthzip.workflows.dependencies import input_version
from healthzip.workflows.period_report import create_report, load_report
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report

START = "2025-03-31T00:00:00+08:00"
CUTOFF = "2025-04-06T00:00:00+08:00"


def records(path):
    with closing(Repository(path)) as repo:
        service = TrainingService(repo)
        machine = service.create_equipment("Synthetic fixed bench", "barbell")
        condition = {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg",
            "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
            "rom_protocol": "user-full", "settings": {"position": "fixed"}, "settings_confirmed": True}
        identities = []
        for day, reps, rir in ((1, 10, None), (2, 11, 0), (3, 12, 2)):
            observed = datetime.fromisoformat(f"2025-04-{day:02}T17:00:00+08:00")
            with patch("healthzip.training.service.timestamp", side_effect=lambda value=None:
                    timestamp(value) if value else (observed + timedelta(hours=1)).isoformat()):
                session = service.start_session("Synthetic frozen trajectory", started_at=observed.isoformat())
                exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
                row = service.add_set(exercise["id"], actual={"completion_state": "completed", "set_type": "work",
                    "load_value": 30, "load_unit": "kg", "reps": reps, "rir": rir,
                    "ended_at": (observed + timedelta(minutes=3)).isoformat()})
                identities.append(row["set_uuid"])
                if day == 3:
                    for unknown in range(2):
                        other = service.add_exercise(session["id"], "psa.ex.barbell_bench_press",
                            {"load_basis": "external_total_kg", "load_basis_confirmed": True})
                        row = service.add_set(other["id"], actual={"completion_state": "completed", "set_type": "work",
                            "load_value": 30, "load_unit": "kg", "reps": 8 + unknown,
                            "ended_at": (observed + timedelta(minutes=5 + unknown)).isoformat()})
                        identities.append(row["set_uuid"])
                service.end_session(session["id"], ended_at=(observed + timedelta(minutes=45)).isoformat())
        return identities


def request(wid="W2"):
    return WorkflowRequest(wid, cutoff_time=CUTOFF, window_start=START, window_end=CUTOFF,
        result_metric_id="STR-11" if wid == "W4" else None, ordinary_inventory=wid == "W4")


def stored(repo, identity):
    return json.loads(repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (identity,))[0])


def test_workflows_share_frozen_training_but_return_complete_independent_values(tmp_path):
    path = tmp_path / "sharing.sqlite3"
    identities = records(path)
    with closing(Repository(path)) as repo:
        before = input_version(repo, None)
        runs = [run_workflow(repo, request(wid), knowledge_root=tmp_path / "missing") for wid in ("W4", "W2", "W5")]
        ordinary = runs[0]["supplements"]["ordinary_training"]
        assert ordinary["record_count"] == 5
        assert all(r["supplements"]["ordinary_training"] == ordinary for r in runs)
        manifests = [stored(repo, r["run_id"]) for r in runs]
        assert all(m.get("storage_format") == "workflow-training-references-1" for m in manifests)
        references = [m["supplements"]["ordinary_training"] for m in manifests]
        assert all(set(reference) == {"$frozen_object"} for reference in references)
        assert references[0] == references[1] == references[2]
        assert repo.one("SELECT count(*) FROM report_content_object WHERE kind='ordinary-training'")[0] == 1
        assert repo.one("SELECT count(*) FROM report_content_object WHERE kind='ordinary-training-series'")[0] == len(ordinary["series"])
        assert repo.one("SELECT count(*) FROM report_content_object WHERE kind='ordinary-training-index'")[0] == 0
        points = [point for group in ordinary["series"] for point in group["points"]]
        assert {p["record_id"] for p in points} == set(identities)
        assert {p["record_id"]: p["rir"] for p in points}[identities[0]] is None
        assert {p["record_id"]: p["rir"] for p in points}[identities[1]] == 0
        assert len({g["series_id"] for g in ordinary["series"] if any(p["record_id"] in identities[-2:] for p in g["points"])}) == 2
        for run in runs:
            assert load_run(repo, run["run_id"]) == run
            assert run_workflow(repo, request(run["workflow_id"]), knowledge_root=tmp_path / "missing") == run
        queries = []
        repo.conn.set_trace_callback(queries.append)
        copy = load_run(repo, runs[0]["run_id"])
        repo.conn.set_trace_callback(None)
        # One root read and one batch for all scientific groups, rather than
        # one independent query per group in a large ordinary inventory.
        assert len([q for q in queries if "FROM report_content_object" in q]) == 2
        copy["supplements"]["ordinary_training"]["series"][0]["points"][0]["reps"] = 999
        assert load_run(repo, runs[0]["run_id"]) == runs[0]
        assert input_version(repo, None) == before


def test_workflow_failure_rolls_back_new_training_objects_and_can_retry(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    records(path)
    with closing(Repository(path)) as repo:
        repo.conn.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON workflow_run BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            run_workflow(repo, request(), knowledge_root=tmp_path / "missing")
        for table in ("workflow_run", "analysis_run", "report_content_object"):
            assert repo.one(f"SELECT count(*) FROM {table}")[0] == 0
        assert not repo.conn.in_transaction
        repo.conn.execute("DROP TRIGGER synthetic_abort")
        run = run_workflow(repo, request(), knowledge_root=tmp_path / "missing")
        assert load_run(repo, run["run_id"]) == run
        assert repo.one("SELECT count(*) FROM report_content_object")[0] > 0


def test_concurrent_identical_workflows_commit_one_complete_shared_snapshot(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    records(path)
    barrier = Barrier(3)

    def submit(_):
        with closing(Repository(path)) as repo:
            barrier.wait(timeout=10)
            return run_workflow(repo, request(), knowledge_root=tmp_path / "missing")

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(submit, range(3)))
    assert results[0] == results[1] == results[2]
    with closing(Repository(path)) as repo:
        assert repo.one("SELECT count(*) FROM workflow_run")[0] == 1
        assert repo.one("SELECT count(*) FROM report_content_object WHERE kind='ordinary-training'")[0] == 1
        assert load_run(repo, results[0]["run_id"]) == results[0]


def test_legacy_inline_run_and_old_bytes_survive_new_results_and_source_revision(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    identities = records(path)
    with closing(Repository(path)) as repo:
        original = run_workflow(repo, request(), knowledge_root=tmp_path / "missing")
        # Seed the previously shipped inline representation before checking
        # preservation; application operations must never migrate this row.
        old_bytes = json.dumps(original, ensure_ascii=False, indent=2)
        repo.conn.execute("UPDATE workflow_run SET result_json=? WHERE run_id=?", (old_bytes, original["run_id"]))
        repo.conn.commit()
        assert run_workflow(repo, request(), knowledge_root=tmp_path / "missing") == original
        before_objects = [tuple(r) for r in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")]
        service = TrainingService(repo)
        actual = service.get_set(identities[0])
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None:
                   timestamp(value) if value else "2025-04-05T12:00:00+08:00"):
            service.edit_set(actual["id"], {"reps": 13}, base_revision=actual["revision"])
        successor = run_workflow(repo, request(), knowledge_root=tmp_path / "missing")
        assert successor["run_id"] != original["run_id"]
        assert successor["supplements"]["ordinary_training"] != original["supplements"]["ordinary_training"]
        clear()
        assert load_run(repo, original["run_id"]) == original
        assert repo.one("SELECT result_json FROM workflow_run WHERE run_id=?", (original["run_id"],))[0] == old_bytes
        after_objects = {tuple(r) for r in repo.rows("SELECT * FROM report_content_object")}
        assert all(row in after_objects for row in before_objects)


def test_audit_actual_file_restores_each_workflow_without_database_or_current_records(tmp_path):
    from healthzip.workflows.report_objects import reconstruct_workflow

    path = tmp_path / "audit.sqlite3"
    records(path)
    with closing(Repository(path)) as repo:
        report = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"},
                               period="week", knowledge_root=tmp_path / "missing", include_details=True)
        bundle = audit_bundle(repo, report["report_id"])
        assert bundle["format"] == "healthzip-frozen-audit-3"
        expected = {identity: load_run(repo, identity) for identity in bundle["workflow_runs"]}
        assert any(r["supplements"].get("ordinary_training", {}).get("record_count") for r in expected.values())
        compact = [value for value in bundle["workflow_runs"].values() if value.get("storage_format")]
        assert compact and all(set(r["supplements"]["ordinary_training"]) == {"$frozen_object"} for r in compact)
        objects_before = [tuple(r) for r in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")]
        frozen_rows = [tuple(r) for r in repo.rows("SELECT * FROM joint_period_report ORDER BY report_id")]
        export = tmp_path / "audit.json"
        export.write_text(json.dumps(bundle, ensure_ascii=False))
        clear()
        assert load_report(repo, report["report_id"], include_details=True) == report
        assert [tuple(r) for r in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")] == objects_before
        assert [tuple(r) for r in repo.rows("SELECT * FROM joint_period_report ORDER BY report_id")] == frozen_rows
    path.rename(tmp_path / "original-database-not-at-its-former-path.sqlite3")
    from_file = json.loads(export.read_text())
    assert reconstruct_report(from_file) == report
    assert {identity: reconstruct_workflow(from_file, identity) for identity in expected} == expected
    # A legacy inline run may coexist in the same self-contained bundle.
    legacy_id = next(iter(expected))
    mixed = deepcopy(from_file)
    mixed["workflow_runs"][legacy_id] = expected[legacy_id]
    assert reconstruct_workflow(mixed, legacy_id) == expected[legacy_id]
    legacy = {"format": "healthzip-frozen-audit-2", "workflow_runs": {legacy_id: expected[legacy_id]}, "content_objects": {}}
    assert reconstruct_workflow(legacy, legacy_id) == expected[legacy_id]
    # Missing frozen content fails; it cannot be filled from latest rows/web.
    broken = deepcopy(from_file)
    chosen = next(identity for identity, run in expected.items() if run["supplements"].get("ordinary_training", {}).get("record_count"))
    reference = broken["workflow_runs"][chosen]["supplements"]["ordinary_training"]["$frozen_object"]
    group_id = broken["content_objects"][reference]["series"][0]["$frozen_object"]
    del broken["content_objects"][group_id]
    with pytest.raises((KeyError, ValueError)):
        reconstruct_workflow(broken, chosen)


def test_frozen_workflow_backup_is_portable_but_other_workspace_cannot_resolve_refs(tmp_path):
    from healthzip.workflows.report_objects import read_workflow

    path = tmp_path / "origin.sqlite3"
    records(path)
    backup = tmp_path / "backup.sqlite3"
    with closing(Repository(path)) as repo:
        run = run_workflow(repo, request(), knowledge_root=tmp_path / "missing")
        manifest = stored(repo, run["run_id"])
        with closing(sqlite3.connect(backup)) as copy:
            repo.conn.backup(copy)
    with closing(Repository(backup)) as copied:
        assert load_run(copied, run["run_id"]) == run
    with closing(Repository(tmp_path / "other.sqlite3")) as other:
        with pytest.raises(ValueError, match="missing"):
            read_workflow(other, manifest)


def test_workflow_training_roundtrip_keeps_precision_empty_fields_and_group_order(tmp_path):
    from healthzip.workflows.report_objects import read_workflow, save_workflow

    group = {"series_id": "same-name-independent-group", "record_count": 1, "summary": "合成🧪",
             "points": [{"record_id": "independent-1", "revision": 2**80 + 1, "rir": None, "load": -0.0}]}
    second = {**group, "series_id": "other-condition", "points": [{"record_id": "independent-2", "rir": 0}]}
    ordinary = {"version": "synthetic-precision-1", "window": {"start": START, "end": CUTOFF},
                "record_count": 3, "series": [group, second, group], "empty": [], "unknown": None}
    result = {"run_id": "synthetic-no-inference", "supplements": {"ordinary_training": ordinary, "other": {"keep": True}}}
    original = deepcopy(result)
    with closing(Repository(tmp_path / "precision.sqlite3")) as repo:
        repo.conn.execute("BEGIN IMMEDIATE")
        frozen = save_workflow(repo, result)
        repo.conn.commit()
        assert result == original and "storage_format" not in result
        restored = read_workflow(repo, json.loads(json.dumps(frozen)))
        assert json.dumps(restored, ensure_ascii=False, sort_keys=True) == json.dumps(original, ensure_ascii=False, sort_keys=True)
        assert [g["series_id"] for g in restored["supplements"]["ordinary_training"]["series"]] == [group["series_id"], second["series_id"], group["series_id"]]
        restored["supplements"]["ordinary_training"]["series"][0]["points"].clear()
        assert read_workflow(repo, frozen) == original


def test_offline_workflow_repeated_references_restore_independent_values():
    from healthzip.workflows.report_objects import reconstruct_workflow

    bundle = {
        "format": "healthzip-frozen-audit-3",
        "workflow_runs": {"synthetic-run": {"run_id": "synthetic-run", "storage_format": "workflow-training-references-1",
            "supplements": {"ordinary_training": {"$frozen_object": "root"}}}},
        "content_objects": {
            "root": {"series": [{"$frozen_object": "group"}, {"$frozen_object": "group"}]},
            "group": {"series_id": "preserved-repeat", "points": [{"record_id": "synthetic-record", "rir": None}],
                      "notes": [{"$frozen_object": "note"}, {"$frozen_object": "note"}]},
            "note": {"limitations": ["unknown_condition"]},
        },
    }
    original_bundle = deepcopy(bundle)
    restored = reconstruct_workflow(bundle, "synthetic-run")
    original_result = deepcopy(restored)
    series = restored["supplements"]["ordinary_training"]["series"]
    assert series[0] == series[1]
    assert series[0] is not series[1]
    assert series[0]["notes"][0] is not series[0]["notes"][1]
    series[0]["points"].clear()
    series[0]["notes"][0]["limitations"].clear()
    assert series[1] == original_result["supplements"]["ordinary_training"]["series"][1]
    assert series[0]["notes"][1]["limitations"] == ["unknown_condition"]
    assert bundle == original_bundle
    assert reconstruct_workflow(bundle, "synthetic-run") == original_result


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_workflow_storage_keeps_strict_finite_json_boundary(tmp_path, value):
    from healthzip.workflows.report_objects import save_workflow

    result = {"supplements": {"ordinary_training": {"series": [
        {"series_id": "synthetic-bad-number", "points": [{"rir": value}]}]}}}
    with closing(Repository(tmp_path / "nonfinite.sqlite3")) as repo:
        repo.conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="Out of range float"):
            save_workflow(repo, result)
        repo.conn.rollback()
        assert repo.one("SELECT count(*) FROM report_content_object")[0] == 0


def scope_fixture():
    first = {"series_id": "unknown-condition-1", "condition_key": None, "record_count": 1,
             "summary": "合成🧪", "points": [{"record_id": "first", "revision": 2**80 + 1,
                                             "load": -0.0, "rir": None}]}
    second = {**first, "series_id": "unknown-condition-2",
              "points": [{"record_id": "second", "load": 30.125, "rir": 0}]}
    return {"version": "synthetic-scope-1", "window": {"start": START, "end": CUTOFF},
            "record_count": 3, "series": [first, second, first], "empty": [], "unknown": None}


@pytest.mark.parametrize("include_preview", [False, True])
def test_training_scope_batch_keeps_legacy_ids_bytes_order_and_offline_reconstruction(tmp_path, include_preview):
    from healthzip.workflows.report_objects import (
        _save_training,
        read_workflow,
        reconstruct_workflow,
    )

    ordinary = scope_fixture()
    original = deepcopy(ordinary)
    with closing(Repository(tmp_path / "scope-contract.sqlite3")) as repo:
        expected = {}

        def legacy_reference(kind, payload):
            # The shipped content-addressing contract is the compatibility oracle.
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
            scope = json.dumps([str(repo.path.resolve()), repo.path.stat().st_ino, "local", kind])
            identity = hashlib.sha256((scope + "\0" + encoded).encode()).hexdigest()
            expected[identity] = ("local", kind, encoded)
            return {"$frozen_object": identity}

        groups = [legacy_reference("ordinary-training-series", group) for group in ordinary["series"]]
        header = {key: value for key, value in ordinary.items() if key != "series"}
        root = legacy_reference("ordinary-training", {**header, "series": groups})
        preview = None
        if include_preview:
            index = [{"series_id": group["series_id"], "summary": group["summary"],
                      "record_count": group["record_count"], "reference": reference}
                     for group, reference in zip(ordinary["series"], groups)]
            preview = {key: value for key, value in header.items() if key in {
                "version", "window", "record_count", "limitations", "identity"}}
            preview["index_ref"] = legacy_reference("ordinary-training-index", index)
        with repo.transaction():
            assert _save_training(repo, ordinary, include_preview=include_preview, allow_nan=False) == (root, preview)
        stored_rows = {row["object_id"]: (row["user_id"], row["kind"], row["payload_json"])
                       for row in repo.rows("SELECT * FROM report_content_object")}
        assert stored_rows == expected
        old_rows = [tuple(row) for row in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")]
        with repo.transaction():
            assert _save_training(repo, ordinary, include_preview=include_preview, allow_nan=False) == (root, preview)
        assert [tuple(row) for row in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")] == old_rows
        manifest = {"run_id": "synthetic-scope", "storage_format": "workflow-training-references-1",
                    "supplements": {"ordinary_training": root}}
        public = {"run_id": "synthetic-scope", "supplements": {"ordinary_training": ordinary}}
        assert read_workflow(repo, manifest) == public
        bundle = {"format": "healthzip-frozen-audit-3", "workflow_runs": {"synthetic-scope": manifest},
                  "content_objects": {key: json.loads(value[2]) for key, value in expected.items()}}
        restored = reconstruct_workflow(json.loads(json.dumps(bundle)), "synthetic-scope")
        assert json.dumps(restored, sort_keys=True) == json.dumps(public, sort_keys=True)
        series = restored["supplements"]["ordinary_training"]["series"]
        assert [group["series_id"] for group in series] == ["unknown-condition-1", "unknown-condition-2", "unknown-condition-1"]
        assert groups[0] == groups[2] and groups[0] != groups[1]
        series[0]["points"].clear()
        assert series[2]["points"] == ordinary["series"][2]["points"]
        assert ordinary == original


@pytest.mark.parametrize("group_count", [1, 17])
def test_training_scope_preparation_is_per_batch_not_per_group(tmp_path, group_count):
    from healthzip.workflows.report_objects import _save_training

    ordinary = {"series": [{"series_id": f"independent-unknown-{index}", "condition_key": None,
                             "points": [{"record_id": f"record-{index}"}]} for index in range(group_count)]}
    with closing(Repository(tmp_path / "scope-count.sqlite3")) as repo:
        resolve = Path.resolve
        with patch.object(Path, "resolve", autospec=True, side_effect=resolve) as observed:
            with repo.transaction():
                _save_training(repo, ordinary, include_preview=False, allow_nan=False)
        # Prepare the series scope, verify it at the batch boundary, then save
        # its separately typed parent. This count must not grow with groups.
        assert observed.call_count == 3
        assert repo.one("SELECT count(*) FROM report_content_object WHERE kind='ordinary-training-series'")[0] == group_count


@pytest.mark.parametrize(("via_report", "pending_caller_write"), [(False, False), (True, False), (True, True)])
def test_training_scope_change_during_batch_refuses_freeze_and_rolls_back(tmp_path, via_report, pending_caller_write):
    from healthzip.workflows.report_objects import save_content, save_object, save_workflow

    original_path = tmp_path / "scope-original.sqlite3"
    other_path = tmp_path / "scope-other.sqlite3"
    with closing(Repository(original_path)) as original, closing(Repository(other_path)) as other:
        with original.transaction():
            old = save_object(original, "existing-frozen", {"preserve": "original"})
        with other.transaction():
            save_object(other, "existing-frozen", {"preserve": "other"})
        old_original_rows = [tuple(row) for row in original.rows("SELECT * FROM report_content_object")]
        old_other_rows = [tuple(row) for row in other.rows("SELECT * FROM report_content_object")]
    alias = tmp_path / "scope-alias.sqlite3"
    alias.symlink_to(original_path)
    with closing(Repository(alias)) as repo:
        if pending_caller_write:
            save_object(repo, "pending-caller", {"preserve": "not part of this failed freeze"})
            assert repo.conn.in_transaction
            old_original_rows = [tuple(row) for row in repo.rows("SELECT * FROM report_content_object")]
        changed = False

        def retarget_after_first_insert(statement):
            nonlocal changed
            if not changed and statement.startswith("INSERT OR IGNORE INTO report_content_object"):
                alias.unlink()
                alias.symlink_to(other_path)
                changed = True

        repo.conn.set_trace_callback(retarget_after_first_insert)
        with pytest.raises(ValueError, match="frozen_report_workspace_changed_during_batch"):
            if via_report:
                # save_content owns its production commit/rollback boundary;
                # wrapping it in a test transaction would hide a leaked write.
                save_content(repo, {"current": {}, "analysis_run_id": "synthetic-analysis",
                    "questions": [{"id": "W1", "ordinary_training": scope_fixture()}]})
            else:
                with repo.transaction():
                    save_workflow(repo, {"supplements": {"ordinary_training": scope_fixture()}})
        repo.conn.set_trace_callback(None)
        assert changed and repo.conn.in_transaction is pending_caller_write
        assert [tuple(row) for row in repo.rows("SELECT * FROM report_content_object")] == old_original_rows
        # A later caller commit preserves its earlier write, never any failed
        # batch objects. The no-transaction report path also remains clean.
        repo.conn.commit()
    with closing(Repository(original_path)) as original, closing(Repository(other_path)) as other:
        assert [tuple(row) for row in original.rows("SELECT * FROM report_content_object")] == old_original_rows
        assert [tuple(row) for row in other.rows("SELECT * FROM report_content_object")] == old_other_rows
        assert original.one("SELECT object_id FROM report_content_object")[0] == old["$frozen_object"]


def test_training_scope_is_fresh_across_workspaces_and_same_path_recreation(tmp_path):
    from healthzip.workflows.report_objects import read_workflow, save_workflow

    path = tmp_path / "recreated.sqlite3"
    public = {"supplements": {"ordinary_training": scope_fixture()}}
    with closing(Repository(path)) as repo:
        original_inode = path.stat().st_ino
        with repo.transaction():
            original = save_workflow(repo, public)
        original_rows = [tuple(row) for row in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")]
    retained = tmp_path / "retained-original.sqlite3"
    path.rename(retained)
    manifests = [original]
    for destination in (path, tmp_path / "different-workspace.sqlite3"):
        with closing(Repository(destination)) as repo:
            if destination == path:
                assert destination.stat().st_ino != original_inode
            with repo.transaction():
                manifest = save_workflow(repo, public)
            assert read_workflow(repo, manifest) == public
            for prior in manifests:
                assert manifest != prior
                with pytest.raises(ValueError, match="frozen_report_content_missing"):
                    read_workflow(repo, prior)
            manifests.append(manifest)
    with closing(Repository(retained)) as repo:
        assert read_workflow(repo, original) == public
        assert [tuple(row) for row in repo.rows("SELECT * FROM report_content_object ORDER BY object_id")] == original_rows


def test_training_scope_batch_leaves_successful_commit_to_caller(tmp_path):
    from healthzip.workflows.report_objects import save_workflow

    path = tmp_path / "caller-commit.sqlite3"
    with closing(Repository(path)) as repo, closing(Repository(path)) as observer:
        frozen = save_workflow(repo, {"supplements": {"ordinary_training": scope_fixture()}})
        assert frozen["storage_format"] == "workflow-training-references-1"
        assert repo.conn.in_transaction
        assert repo.one("SELECT count(*) FROM report_content_object")[0] == 3
        assert observer.one("SELECT count(*) FROM report_content_object")[0] == 0
        repo.conn.rollback()
        assert repo.one("SELECT count(*) FROM report_content_object")[0] == 0


@pytest.mark.parametrize("ordinary", [{"version": "synthetic-empty"}, {"version": "synthetic-empty", "series": []}])
def test_training_scope_keeps_absent_and_empty_series_distinct(tmp_path, ordinary):
    from healthzip.workflows.report_objects import read_workflow, save_workflow

    public = {"supplements": {"ordinary_training": ordinary}}
    with closing(Repository(tmp_path / "empty-scope.sqlite3")) as repo:
        with repo.transaction():
            frozen = save_workflow(repo, public)
        assert read_workflow(repo, frozen) == public
        assert repo.one("SELECT count(*) FROM report_content_object")[0] == 1
        assert repo.one("SELECT kind FROM report_content_object")[0] == "ordinary-training"


def test_training_scope_preserves_existing_permissive_json_boundary(tmp_path):
    from healthzip.workflows.report_objects import _save_training

    group = {"series_id": "legacy-nonfinite", "points": [{"value": float("nan")}],
             "record_count": 1, "summary": "legacy value retained"}
    with closing(Repository(tmp_path / "permissive-scope.sqlite3")) as repo:
        encoded = json.dumps(group, ensure_ascii=False, sort_keys=True, allow_nan=True)
        scope = json.dumps([str(repo.path.resolve()), repo.path.stat().st_ino, "local", "ordinary-training-series"])
        expected = hashlib.sha256((scope + "\0" + encoded).encode()).hexdigest()
        with repo.transaction():
            _save_training(repo, {"series": [group]}, include_preview=True, allow_nan=True)
        row = repo.one("SELECT object_id,payload_json FROM report_content_object WHERE kind='ordinary-training-series'")
        assert tuple(row) == (expected, encoded)
