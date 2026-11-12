"""Synthetic event-history scale checks using real service-shaped fixtures.

Bulk fixture seeding is not a measurement of UI recording or import throughput.
Run each size in a fresh process. --code-root can select an isolated source archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from unittest.mock import patch

TABLES = (
    "strength_session", "training_session_exercise", "strength_set",
    "training_event", "training_invalidation",
)
HISTORICAL_CLOCK = "2020-01-01T12:00:00+00:00"
NUMERIC_ID_TOKEN = "__synthetic_numeric_identity__"
QUERY_INDEXES = {
    "training_event_support", "training_event_session_versions", "training_conflict_event",
    "training_recommendation_created", "training_recommendation_followup",
    "training_feedback_support", "training_feedback_candidate", "training_unprojected_legacy",
    "idx_strength_date",
    "idx_training_active_session",
    "training_invalidation_pending",
    "training_event_recent",
}
PROJECTION_TRIGGERS = {"training_event_candidates_" + operation for operation in ("insert", "update", "delete")}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def count_rows(repo, table):
    assert table in TABLES
    return repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def table_content_hashes(repo, upper_rowids=None, restore_invalidations=None):
    """Stream every persisted value without retaining histories in Python."""
    hashes = {}
    original_factory = repo.conn.text_factory
    repo.conn.text_factory = bytes
    try:
        for table in TABLES:
            state = hashlib.sha256()
            where = " WHERE rowid<=?" if upper_rowids is not None else ""
            cursor = repo.conn.execute(f"SELECT rowid AS cohort_rowid,* FROM {table}{where} ORDER BY rowid",
                                       (upper_rowids[table],) if upper_rowids is not None else ())
            columns = [column[0] for column in cursor.description]
            for record in cursor:
                values = list(record)
                if table == "training_invalidation" and restore_invalidations and values[0] in restore_invalidations:
                    for name, value in restore_invalidations[values[0]].items():
                        values[columns.index(name)] = value
                for value in values[1:]:
                    if isinstance(value, bytes):
                        # All textual source columns in these five tables have
                        # TEXT affinity. Avoid decoding/re-encoding their JSON.
                        tag, raw = b"str:", value
                    elif isinstance(value, str):
                        tag, raw = b"str:", value.encode()
                    elif value is None:
                        tag, raw = b"", b"null"
                    else:
                        tag, raw = (type(value).__name__ + ":").encode(), str(value).encode()
                    state.update((len(tag) + len(raw)).to_bytes(8, "big"))
                    state.update(tag)
                    state.update(raw)
            hashes[table] = state.hexdigest()
    finally:
        repo.conn.text_factory = original_factory
    return hashes


def reset_derived_query_objects(repo):
    """Only discard reproducible query objects in the isolated synthetic copy."""
    present = {row[0] for row in repo.conn.execute("SELECT name FROM sqlite_master")}
    removed = []
    for name in sorted(PROJECTION_TRIGGERS):
        repo.conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        removed.append(name)
    repo.conn.execute("DROP TABLE IF EXISTS training_event_set_candidate")
    removed.extend(("training_event_set_candidate", "training_last_values_candidates"))
    for name in sorted(QUERY_INDEXES):
        repo.conn.execute(f'DROP INDEX IF EXISTS "{name}"')
        removed.append(name)
    repo.conn.execute("DELETE FROM schema_meta WHERE key IN ('training_event_query_projection','training_last_values_projection')")
    repo.conn.commit()
    return [name for name in removed if name in present]


def service_session(service, condition, prefix, clock):
    """Ten actual service mutations, including six revisions of the same set."""
    import healthzip.training.service as training

    original_timestamp = training.timestamp
    recorded = datetime.fromisoformat(clock)
    started = (recorded - timedelta(hours=2)).isoformat()
    with patch.object(training, "timestamp", lambda value=None: (
            original_timestamp(value) if value is not None else clock)):
        session = service.start_session("Synthetic event-history benchmark", started_at=started,
            session_id=prefix + "-session", event_id=prefix + "-start")
        exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition,
            session_exercise_id=prefix + "-exercise", event_id=prefix + "-add-exercise")
        row = service.add_set(exercise["id"], {
            "completion_state": "completed", "load_value": 40, "load_unit": "kg", "reps": 8,
            "started_at": (recorded - timedelta(hours=2) + timedelta(minutes=5)).isoformat(),
            "ended_at": (recorded - timedelta(hours=2) + timedelta(minutes=6)).isoformat(),
        }, set_id=prefix + "-set", event_id=prefix + "-add-set")
        for index in range(6):
            row = service.edit_set(row["set_uuid"], {"notes": f"synthetic revision {index}"},
                base_revision=row["revision"], event_id=prefix + f"-revise-{index}")
        service.end_session(session["id"], ended_at=(recorded - timedelta(hours=1)).isoformat(),
                            event_id=prefix + "-end")
    return row


def fixture(repo, historical_events, cutoff):
    from healthzip.training.service import TrainingService

    assert historical_events > 0 and historical_events % 10 == 0
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic benchmark barbell", "barbell",
        equipment_id="synthetic-benchmark-equipment", event_id="synthetic-benchmark-equipment-event")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
        "load_basis_confirmed": True, "settings_confirmed": True, "settings": {}, "side": "both",
        "repetition_semantics": "simultaneous", "rom_protocol": "user_confirmed_full"}
    service_session(service, condition, "synthetic-prototype", HISTORICAL_CLOCK)
    prototypes = {table: [dict(row) for row in repo.conn.execute(f"SELECT * FROM {table}")]
                  for table in TABLES}
    prototypes["training_event"] = [row for row in prototypes["training_event"]
                                   if row["entity_type"] != "equipment"]
    assert len(prototypes["training_event"]) == 10
    assert len(prototypes["strength_set"]) == len(prototypes["strength_session"]) == 1
    # Seed old invalidations as already recomputed; retain every audit row. The
    # ten current mutations below remain pending and take the normal UI path.
    for row in prototypes["training_invalidation"]:
        row.update(status="recomputed", analysis_version="synthetic-prior-analysis")
    group_count = historical_events // 10
    columns = {table: tuple(rows[0]) for table, rows in prototypes.items()}
    insert_sql = {table: f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})"
                  for table, names in columns.items()}
    # Numeric session/set IDs happen to be 1 in this isolated prototype. Only
    # identity fields are rewritten; versions, values, conditions stay intact.
    def clone_value(value, group, key=None):
        if isinstance(value, dict):
            return {name: clone_value(item, group, name) for name, item in value.items()}
        if isinstance(value, list):
            return [clone_value(item, group) for item in value]
        if isinstance(value, str):
            return value.replace("synthetic-prototype", f"synthetic-history-{group:06d}")
        if isinstance(value, int) and key in {"id", "session_id"}:
            assert value == 1, (key, value)
            return group
        return value

    for table in reversed(TABLES):
        if table == "training_event":
            repo.conn.execute("DELETE FROM training_event WHERE entity_type!='equipment'")
        else:
            repo.conn.execute(f"DELETE FROM {table}")
    templates = {}
    for table, rows in prototypes.items():
        templates[table] = []
        for row in rows:
            templates[table].append({name: json.loads(value) if name.endswith("_json") and value is not None else value
                                     for name, value in row.items()})
    # Pre-encode the repeated JSON graph once. Replacing an explicit quoted
    # identity token preserves every byte produced by the recursive reference
    # implementation, without rebuilding large dictionaries a million times.
    def tokenize(value, key=None):
        if isinstance(value, dict):
            return {name: tokenize(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [tokenize(item) for item in value]
        if isinstance(value, int) and key in {"id", "session_id"}:
            assert value == 1
            return NUMERIC_ID_TOKEN
        return value

    compiled = {}
    for table, rows in templates.items():
        compiled[table] = []
        for template in rows:
            row = dict(template)
            if table == "training_invalidation":
                row.pop("id")
            row = tokenize(row)
            for name, value in list(row.items()):
                if name.endswith("_json") and value is not None:
                    row[name] = encoded(value)
            compiled[table].append(row)

    def rendered(template, table, group, ordinal):
        row = {}
        for name, value in template.items():
            if value == NUMERIC_ID_TOKEN:
                value = group
            elif isinstance(value, str):
                value = value.replace("synthetic-prototype", f"synthetic-history-{group:06d}")
                value = value.replace('"' + NUMERIC_ID_TOKEN + '"', str(group))
            row[name] = value
        if table == "training_invalidation":
            row["id"] = (group - 1) * len(compiled[table]) + ordinal + 1
        if table == "training_event":
            row["payload_hash"] = digest(row["payload_json"].encode())
        return tuple(row[name] for name in columns[table])

    for group in (2, 127):
        for table, rows in templates.items():
            for ordinal, template in enumerate(rows):
                raw = dict(template)
                if table == "training_invalidation":
                    raw.pop("id")
                row = clone_value(raw, group)
                if table == "training_invalidation":
                    row["id"] = (group - 1) * len(rows) + ordinal + 1
                for name in columns[table]:
                    if name.endswith("_json") and row[name] is not None:
                        row[name] = encoded(row[name])
                if table == "training_event":
                    row["payload_hash"] = digest(row["payload_json"].encode())
                assert rendered(compiled[table][ordinal], table, group, ordinal) == tuple(
                    row[name] for name in columns[table])

    started = time.perf_counter()
    for first in range(1, group_count + 1, 250):
        batches = {table: [] for table in TABLES}
        for group in range(first, min(first + 250, group_count + 1)):
            for table, rows in compiled.items():
                for ordinal, template in enumerate(rows):
                    batches[table].append(rendered(template, table, group, ordinal))
        for table, batch in batches.items():
            repo.conn.executemany(insert_sql[table], batch)
        repo.conn.commit()
    seeding_seconds = time.perf_counter() - started
    repo.conn.execute("UPDATE schema_meta SET value=? WHERE key='training_data_version'", (str(historical_events),))
    repo.conn.commit()
    current_clock = (datetime.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
    current = service_session(service, condition, "synthetic-current", current_clock)
    repo.conn.commit()
    counts = {table: count_rows(repo, table) for table in TABLES}
    assert counts["training_event"] == historical_events + 11  # one equipment plus ten current events
    assert counts["strength_set"] == counts["strength_session"] == group_count + 1
    assert not repo.conn.execute("PRAGMA foreign_key_check").fetchall()
    return {"counts": counts, "fixture_seeding_seconds": seeding_seconds,
            "historical_sessions": group_count, "current_set_uuid": current["set_uuid"]}


def worker(count, code_root, cutoff=None, reuse_database=None):
    from streamlit.testing.v1 import AppTest

    import healthzip
    import healthzip.training.service as training
    from healthzip.analytics.cache import clear
    from healthzip.analytics.v13 import analyze
    from healthzip.db.repository import Repository

    actual_root = Path(healthzip.__file__).resolve().parents[2]
    assert actual_root == code_root.resolve(), "The imported package must match --code-root"
    benchmark_hash = digest(Path(__file__).read_bytes())
    source_files = [*actual_root.glob("src/healthzip/**/*.py"), *actual_root.glob("src/healthzip/**/*.sql"), actual_root / "app.py"]
    hashes = {str(path.relative_to(actual_root)): digest(path.read_bytes()) for path in sorted(source_files)}
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()

    def progress(phase):
        print(json.dumps({"historical_events": count, "phase": phase,
                          "at": datetime.now(timezone.utc).isoformat()}), file=sys.stderr, flush=True)

    def summary(result):
        return {key: {name: metric.get(name) for name in (
            "value", "unit", "data_status", "evidence_status", "valid_n", "total_n", "count_domain")}
                for key, metric in result["metrics"].items()}

    def semantic(value):
        if isinstance(value, dict):
            return {key: semantic(item) for key, item in value.items()
                    if key not in {"computed_at", "algorithm_version"}}
        return [semantic(item) for item in value] if isinstance(value, list) else value

    def app_ok(app):
        assert not app.exception and not app.error, [item.value for item in app.exception] + [item.value for item in app.error]

    with tempfile.TemporaryDirectory(prefix="healthzip-synthetic-training-scale-") as folder:
        path = Path(folder) / "synthetic.sqlite3"
        progress("fixture_preparation")
        if reuse_database is not None:
            assert count == 1000000 and reuse_database.is_file()
            before = time.perf_counter()
            shutil.copyfile(reuse_database, path)
            preparation_seconds = time.perf_counter() - before
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            repo = SimpleNamespace(conn=connection, close=connection.close)
            assert connection.execute("SELECT COUNT(*) FROM health_sample").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM strength_session WHERE name!='Synthetic event-history benchmark'").fetchone()[0] == 0
            seeded = {"counts": {table: count_rows(repo, table) for table in TABLES},
                "fixture_seeding_seconds": None, "historical_sessions": count // 10,
                "current_set_uuid": "synthetic-current-set"}
            assert seeded["counts"]["training_event"] == count + 11
            assert seeded["counts"]["strength_set"] == count // 10 + 1
            fixture_origin = "consistent copy of the retained stage1 synthetic million-event fixture; original retained file is not opened for writing"
        else:
            repo = Repository(path)
            before = time.perf_counter()
            seeded = fixture(repo, count, cutoff)
            preparation_seconds = time.perf_counter() - before
            fixture_origin = "new service-shaped synthetic fixture"
        baseline_counts = {table: count_rows(repo, table) for table in TABLES}
        highwater = {table: repo.conn.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0] for table in TABLES}
        original_pending = {row["id"]: {"status": row["status"], "analysis_version": row["analysis_version"]}
                            for row in repo.conn.execute("SELECT * FROM training_invalidation WHERE status='pending'")}
        assert len(original_pending) == 10
        progress("original_table_hashes_before_cold_migration")
        before_content = table_content_hashes(repo)
        removed = reset_derived_query_objects(repo)
        repo.close()
        progress("cold_schema_and_projection_migration")
        before = time.perf_counter()
        repo = Repository(path)
        cold_seconds = time.perf_counter() - before
        assert {table: count_rows(repo, table) for table in TABLES} == baseline_counts
        object_names = {row[0] for row in repo.conn.execute("SELECT name FROM sqlite_master")}
        assert QUERY_INDEXES | PROJECTION_TRIGGERS | {"training_event_set_candidate", "training_last_values_candidates"} <= object_names
        markers = dict(repo.conn.execute("SELECT key,value FROM schema_meta WHERE key IN ('training_event_query_projection','training_last_values_projection')"))
        assert markers == {"training_event_query_projection": "1", "training_last_values_projection": "1"}
        repo.close()
        before = time.perf_counter()
        repo = Repository(path)
        warm_seconds = time.perf_counter() - before
        progress("original_table_hashes_after_cold_and_warm_migration")
        after_upgrade_content = table_content_hashes(repo)
        assert before_content == after_upgrade_content
        upgrade = {"cold_schema_and_projection_upgrade_seconds": cold_seconds,
            "warm_reopen_seconds": warm_seconds, "discarded_derived_objects": removed,
            "restored_markers": markers, "all_original_table_values_unchanged": True,
            "pre_upgrade_table_content_sha256": before_content,
            "post_cold_and_warm_reopen_table_content_sha256": after_upgrade_content}
        decode_counts = Counter()
        original_decode = training._decode

        def counted(row):
            if row is not None:
                keys = row.keys()
                kind = "training_event" if "event_id" in keys and "after_json" in keys else "other"
                decode_counts[kind] += 1
            return original_decode(row)

        progress("canonical_first_analysis")
        clear()
        before = time.perf_counter()
        with patch.object(training, "_decode", counted):
            first = analyze(repo, 30, cutoff_time=cutoff, timezone_name="UTC")
        first_seconds = time.perf_counter() - before
        first_decodes = dict(decode_counts)
        metric_values = summary(first)
        completed = first["metrics"]["STR-02"]
        assert len(completed["value"]) == 1 and completed["value"][0]["reps"] == 8, completed
        assert completed["value"][0]["id"] == "strength_set:" + seeded["current_set_uuid"]
        assert first["metrics"]["STR-01"]["value"]["completed_work_parent_sets"] == 1
        repeats = []
        for _ in range(10):
            before = time.perf_counter()
            again = analyze(repo, 30, cutoff_time=cutoff, timezone_name="UTC")
            repeats.append(time.perf_counter() - before)
            assert again == first

        progress("setup_active_training_target_and_last_values")
        service = training.TrainingService(repo)
        condition = service.get_session_exercise("synthetic-current-exercise")["condition"]
        target = service.start_session("Synthetic benchmark active target",
            session_id="synthetic-active-target-session", event_id="synthetic-active-target-start")
        instance = service.add_exercise(target["id"], "psa.ex.barbell_bench_press", condition,
            session_exercise_id="synthetic-active-target-exercise", event_id="synthetic-active-target-exercise-event")
        decode_counts.clear()
        before = time.perf_counter()
        with patch.object(training, "_decode", counted):
            previous = service.last_values(instance["id"])
        last_values_seconds = time.perf_counter() - before
        last_values_decodes = dict(decode_counts)
        assert previous["source_set_id"] == seeded["current_set_uuid"]
        assert previous["suggested_actual"]["completion_state"] == "draft"
        assert previous["suggested_actual"]["reps"] == 8
        assert float(previous["suggested_actual"]["load_value"]) == 40

        clear()
        import healthzip.config as configuration
        configuration.DEFAULT_DB_PATH = path
        progress("app_initial_overview")
        before = time.perf_counter()
        app = AppTest.from_file(str(actual_root / "app.py")).run(timeout=180)
        ui_initial = time.perf_counter() - before
        app_ok(app)
        progress("app_strength_restore_active_session")
        before = time.perf_counter()
        app.radio(key="main_workspace").set_value("力量").run(timeout=180)
        strength_first_seconds = time.perf_counter() - before
        app_ok(app)
        assert app.selectbox(key="resume_training").value == target["id"]
        assert app.button(key="last_" + instance["id"])
        before = time.perf_counter()
        app.button(key="last_" + instance["id"]).click().run(timeout=180)
        copy_seconds = time.perf_counter() - before
        app_ok(app)
        drafts = service.get_session_exercise(instance["id"])["sets"]
        assert len(drafts) == 1
        draft = drafts[0]
        assert draft["completion_state"] == "draft" and draft["reps"] == 8 and float(draft["load_value"]) == 40
        assert draft["started_at"] is None and draft["ended_at"] is None
        assert service.last_values(instance["id"])["source_set_id"] == seeded["current_set_uuid"]
        history_pages = []
        total_sessions = baseline_counts["strength_session"] + 1
        last_page = (total_sessions + 49) // 50
        if last_page > 1:
            for page in dict.fromkeys((2, last_page, 1)):
                progress("app_history_page_" + str(page))
                before = time.perf_counter()
                app.number_input(key="training_history_page").set_value(page).run(timeout=180)
                elapsed = time.perf_counter() - before
                app_ok(app)
                selector = app.selectbox(key="training_history_session")
                assert len(selector.options) <= 50
                assert app.selectbox(key="resume_training").value == target["id"]
                if page == last_page:
                    assert service.get_session(selector.value)["session_uuid"].startswith("synthetic-history-")
                history_pages.append({"page": page, "seconds": elapsed,
                    "visible_session_options": len(selector.options), "selected_session_id": selector.value})
            assert len({item["selected_session_id"] for item in history_pages}) >= 2
        cold_pages = [{"page": "力量", "seconds": strength_first_seconds}]
        labels = ("心率 / HRV", "睡眠", "报告", "数据质量")
        for label in labels:
            progress("app_first_" + label)
            before = time.perf_counter()
            app.radio(key="main_workspace").set_value(label).run(timeout=180)
            cold_pages.append({"page": label, "seconds": time.perf_counter() - before})
            app_ok(app)
        cached_pages = []
        for label in ("力量", *labels) * 3:
            progress("app_cached_" + label)
            before = time.perf_counter()
            app.radio(key="main_workspace").set_value(label).run(timeout=180)
            cached_pages.append({"page": label, "seconds": time.perf_counter() - before})
            app_ok(app)
        progress("verify_new_ui_mutations_and_original_cohort")
        final_counts = {table: count_rows(repo, table) for table in TABLES}
        added = {table: final_counts[table] - baseline_counts[table] for table in TABLES}
        assert added == {"strength_session": 1, "training_session_exercise": 1, "strength_set": 1,
                         "training_event": 3, "training_invalidation": 3}, added
        for table in TABLES:
            assert repo.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE rowid<=?", (highwater[table],)).fetchone()[0] == baseline_counts[table]
        invalidation_changes = []
        for identity, original in original_pending.items():
            row = dict(repo.conn.execute("SELECT * FROM training_invalidation WHERE id=?", (identity,)).fetchone())
            assert row["status"] == "recomputed" and row["analysis_version"] == first["algorithm_version"]
            invalidation_changes.append({"id": identity, "before": original,
                "after": {key: row[key] for key in original}})
        preserved_content = table_content_hashes(repo, upper_rowids=highwater, restore_invalidations=original_pending)
        assert preserved_content == before_content
        after_ui = analyze(repo, 30, cutoff_time=cutoff, timezone_name="UTC", use_cache=False)
        assert semantic(summary(after_ui)) == semantic(metric_values)
        repo.close()
        final_source_files = [*actual_root.glob("src/healthzip/**/*.py"), *actual_root.glob("src/healthzip/**/*.sql"), actual_root / "app.py"]
        assert hashes == {str(p.relative_to(actual_root)): digest(p.read_bytes()) for p in final_source_files}
        assert digest(Path(__file__).read_bytes()) == benchmark_hash
        p95 = sorted(item["seconds"] for item in cached_pages)[-1]
        training_p95 = max(item["seconds"] for item in cached_pages if item["page"] == "力量")
        progress("worker_completed")
        return {"historical_training_events": count, "historical_sessions": seeded["historical_sessions"],
            "setup_events": 1, "current_events_before_ui": 10, "fixture_origin": fixture_origin,
            "fixture_preparation_seconds": preparation_seconds, "fixture_seeding_seconds": seeded["fixture_seeding_seconds"],
            "seeding_scope": "bulk SQL clones of ten real service mutations, or a complete retained synthetic copy; not UI/import throughput",
            "original_table_counts_before_ui": baseline_counts, "final_table_counts_after_ui": final_counts,
            "intentional_ui_record_additions": added, "original_table_rowid_highwater": highwater,
            "original_pending_invalidations_recomputed": invalidation_changes,
            "original_cohort_sha256_after_ui_with_only_documented_invalidation_fields_restored": preserved_content,
            "all_original_records_preserved": True, "old_cutoff_metric_summaries_unchanged_after_new_ui_events": True,
            "historical_event_clock": HISTORICAL_CLOCK, "current_set_preserved": True,
            "first_analysis_seconds": first_seconds, "first_analysis_decode_calls": first_decodes,
            "first_analysis_query_plan": first["query_plan"], "current_window_metric_values": metric_values,
            "repeat_analysis_seconds": repeats, "repeat_analysis_median_seconds": median(repeats),
            "last_values_seconds": last_values_seconds, "last_values_decode_calls": last_values_decodes,
            "last_values_source_set_id": previous["source_set_id"], "last_values_suggested_actual": previous["suggested_actual"],
            "streamlit_initial_seconds": ui_initial, "streamlit_strength_restore_seconds": strength_first_seconds,
            "streamlit_copy_last_values_to_draft_seconds": copy_seconds,
            "draft_actual_verified": {"completion_state": draft["completion_state"], "load_value": draft["load_value"],
                "load_unit": draft["load_unit"], "reps": draft["reps"], "started_at": draft["started_at"], "ended_at": draft["ended_at"]},
            "source_binding_scope": "last_values identity and actual copied draft verified; UI does not persist a separate draft-origin identity",
            "streamlit_history_page_changes": history_pages, "all_historical_sessions_remain_reachable": bool(history_pages),
            "streamlit_cold_page_changes": cold_pages, "streamlit_cached_page_changes": cached_pages,
            "streamlit_cached_page_change_p95_seconds": p95, "streamlit_cached_training_page_p95_seconds": training_p95,
            "cold_index_upgrade": upgrade, "reopen_migration_seconds": warm_seconds,
            "maxrss_kib_whole_worker_including_fixture_seeding": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "source_file_sha256_at_worker_start": hashes, "source_files_unchanged_during_worker": True,
            "benchmark_script_sha256": benchmark_hash, "product_budget_seconds": 2, "budget_kind": "product_parameter",
            "cached_streamlit_budget_met": p95 <= 2, "cached_training_page_budget_met": training_p95 <= 2,
            "scope_limits": ["Synthetic shared-host workload, not the user's target device or private export",
                "Historical event records outside the 30-day window; one current completed set and deliberate UI additions",
                "No scaled recommendation/feedback corpus; their throughput is not established",
                "Revision/move/delete/conflict/follow-up correctness additionally requires the separate regression suite"]}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int)
    parser.add_argument("--counts", default="10000,100000,1000000")
    parser.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--cutoff", help="Explicit synthetic analysis cutoff for matched before/after fixtures")
    parser.add_argument("--reuse-million-database", type=Path,
                        help="Read only a retained synthetic million-event database and measure an isolated copy")
    parser.add_argument("--log-root", type=Path, default=Path(".local/training-history-benchmark/logs"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/v14/performance/training-scale-results.json"))
    args = parser.parse_args()
    if args.worker is not None:
        print(json.dumps(worker(args.worker, args.code_root, args.cutoff, args.reuse_million_database), ensure_ascii=False))
        return
    assert not args.output.exists(), "Choose a new output; existing runs are immutable"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": datetime.now(timezone.utc).isoformat(), "source_label": args.source_label,
        "benchmark_schema_version": 3,
        "schema_note": "Version 3 retains stage1's incomplete million-event run separately and adds actual training-page restoration/draft/history navigation, last_values, all derived query migrations, immutable original cohorts and explicit UI mutation accounting. Reused million-event data is copied before measurement.",
        "hardware": {"machine": platform.machine(), "system": platform.system(), "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(), "available_cpu_count": len(os.sched_getaffinity(0)),
            "host_reported_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")},
        "data_kind": "synthetic", "private_export_tested": False, "results": []}
    args.log_root.mkdir(parents=True, exist_ok=True)
    for count in map(int, args.counts.split(",")):
        env = {**os.environ, "PYTHONPATH": str(args.code_root.resolve() / "src")}
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(count),
            "--code-root", str(args.code_root.resolve()), "--source-label", args.source_label]
        if args.cutoff:
            command += ["--cutoff", args.cutoff]
        if args.reuse_million_database is not None and count == 1000000:
            command += ["--reuse-million-database", str(args.reuse_million_database.resolve())]
        stderr_path = args.log_root / (args.output.stem + f"-{count}.stderr.txt")
        stdout_path = args.log_root / (args.output.stem + f"-{count}.stdout.json")
        with stderr_path.open("x") as diagnostics:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=diagnostics, text=True, env=env)
        with stdout_path.open("x") as raw:
            raw.write(result.stdout)
        if result.returncode:
            payload["failed_worker"] = {"historical_training_events": count, "exit_code": result.returncode,
                "complete": False, "private_stdout_stderr_retained": True}
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            raise RuntimeError(f"Synthetic worker failed ({result.returncode}); private diagnostics: {stderr_path}")
        item = json.loads(result.stdout)
        payload["results"].append(item)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: item[key] for key in ("historical_training_events", "first_analysis_seconds",
            "repeat_analysis_median_seconds", "first_analysis_decode_calls", "streamlit_cached_page_change_p95_seconds")}), flush=True)


if __name__ == "__main__":
    main()
