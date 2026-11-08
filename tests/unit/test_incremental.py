import json
import sqlite3

from healthzip.db.repository import Repository
from healthzip.importers.incremental import import_json_payload, import_jsonl_file
from healthzip.strength_log import append_quick_strength_set


def _payload(value=60.0):
    return {
        "data": {
            "metrics": [
                {
                    "name": "resting_heart_rate",
                    "units": "count/min",
                    "data": [
                        {
                            "id": "rhr-1",
                            "qty": value,
                            "date": "2026-11-08T08:00:00+08:00",
                            "source": "Synthetic Watch",
                        }
                    ],
                }
            ],
            "workouts": [
                {
                    "id": "workout-1",
                    "name": "Traditional Strength Training",
                    "start": "2026-11-08T09:00:00+08:00",
                    "end": "2026-11-08T10:00:00+08:00",
                    "duration": 3600,
                    "source": "Synthetic Watch",
                }
            ],
        }
    }


def test_incremental_payload_is_idempotent_and_updates_active_rows(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    first = import_json_payload(_payload(), repo, source_name="phone")
    assert first.new == 2
    assert first.duplicate == 0
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE record_status='active'"
    )["n"] == 1
    assert repo.count("workout") == 1

    repeated = import_json_payload(_payload(), repo, source_name="phone")
    assert repeated.new == 0
    assert repeated.duplicate == 2
    assert repo.count("health_sample") == 1

    changed = import_json_payload(_payload(62.0), repo, source_name="phone")
    assert changed.updated == 1
    assert changed.duplicate == 1
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE record_status='active'"
    )["n"] == 1
    assert repo.one(
        "SELECT normalized_value FROM health_sample WHERE record_status='active'"
    )[0] == 62.0
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE record_status='superseded'"
    )["n"] == 1

    deleted = import_json_payload(
        {"data": {"deleted": [{"id": "rhr-1", "kind": "sample"}]}},
        repo,
        source_name="phone",
    )
    assert deleted.deleted == 1
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE record_status='active'"
    )["n"] == 0
    repo.close()


def test_jsonl_reads_only_complete_lines_and_resumes(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    path = tmp_path / "health.jsonl"
    first_line = json.dumps(_payload(), ensure_ascii=False) + "\n"
    path.write_text(first_line + '{"data": {"metrics": [', encoding="utf-8")

    results = import_jsonl_file(path, repo, source_name="jsonl")
    assert sum(item.new for item in results) == 2
    state = repo.one("SELECT last_offset,status FROM sync_file")
    assert state["last_offset"] == len(first_line.encode("utf-8"))
    assert state["status"] == "completed"

    path.write_text(first_line + json.dumps(_payload(61), ensure_ascii=False) + "\n", encoding="utf-8")
    results = import_jsonl_file(path, repo, source_name="jsonl")
    assert sum(item.updated for item in results) == 1
    assert sum(item.duplicate for item in results) == 1
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE record_status='active'"
    )["n"] == 1
    repo.close()


def test_aggregated_heart_rate_is_rejected_as_not_raw(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "heart_rate",
                    "units": "count/min",
                    "data": [
                        {
                            "Avg": 70,
                            "Min": 60,
                            "Max": 80,
                            "date": "2026-11-08T08:00:00+08:00",
                        }
                    ],
                }
            ]
        }
    }
    result = import_json_payload(payload, repo, source_name="phone")
    assert result.invalid == 1
    assert result.errors == ["aggregate_not_raw"]
    assert repo.count("health_sample") == 0
    repo.close()


def test_without_upstream_id_uses_logical_key_for_updates(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    payload = _payload()
    payload["data"]["metrics"][0]["data"][0].pop("id")
    first = import_json_payload(payload, repo, source_name="phone-no-id")
    assert first.new == 2
    payload["data"]["metrics"][0]["data"][0]["qty"] = 61.0
    changed = import_json_payload(payload, repo, source_name="phone-no-id")
    assert changed.updated == 1
    assert repo.one(
        "SELECT COUNT(*) AS n FROM health_sample WHERE source_kind='health_auto_export' "
        "AND record_status='active'"
    )["n"] == 1
    repo.close()


def test_schema_v2_sync_tables_and_status(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    version = repo.one("SELECT value FROM schema_meta WHERE key='schema_version'")
    assert version[0] == "2"
    status = repo.sync_status()
    assert status["sources"] == []
    repo.close()


def test_v1_database_is_upgraded_without_replacing_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES ('schema_version','1');
        CREATE TABLE import_batch (
            id INTEGER PRIMARY KEY, file_sha256 TEXT NOT NULL, file_name TEXT,
            file_size_bytes INTEGER, exported_at TEXT, imported_at TEXT NOT NULL,
            status TEXT NOT NULL, xml_member_path TEXT, records_seen INTEGER DEFAULT 0,
            records_inserted INTEGER DEFAULT 0, records_deduplicated INTEGER DEFAULT 0,
            records_skipped INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0,
            date_min TEXT, date_max TEXT, unknown_type_counts_json TEXT DEFAULT '{}',
            error_samples_json TEXT DEFAULT '[]'
        );
        CREATE TABLE health_sample (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            import_batch_id INTEGER NOT NULL, raw_type TEXT NOT NULL,
            canonical_type TEXT, raw_value TEXT, raw_unit TEXT, normalized_value REAL,
            normalized_unit TEXT, unit_status TEXT, category_value TEXT, start_utc TEXT,
            end_utc TEXT, creation_utc TEXT, local_datetime TEXT, local_date TEXT,
            utc_offset_minutes INTEGER, source_name TEXT, source_version TEXT, device TEXT,
            metadata_json TEXT DEFAULT '{}', quality_flags_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE workout (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            import_batch_id INTEGER NOT NULL, activity_type TEXT, start_utc TEXT,
            end_utc TEXT, local_date TEXT, duration_seconds REAL, distance_value REAL,
            distance_unit TEXT, energy_value REAL, energy_unit TEXT, source_name TEXT,
            source_version TEXT, device TEXT, metadata_json TEXT DEFAULT '{}',
            suspected_duplicate INTEGER DEFAULT 0
        );
        """
    )
    conn.execute(
        "INSERT INTO import_batch(file_sha256,imported_at,status) VALUES(?,?,?)",
        ("legacy", "2026-11-08T00:00:00Z", "completed"),
    )
    conn.commit()
    conn.close()

    repo = Repository(path)
    assert repo.one("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == "2"
    assert repo.one("SELECT COUNT(*) AS n FROM import_batch")["n"] == 1
    assert repo.one(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sample_source_record'"
    ) is not None
    repo.close()


def test_mobile_quick_log_keeps_identical_sets_and_deduplicates_retry(tmp_path):
    repo = Repository(tmp_path / "health.sqlite3")
    first = append_quick_strength_set(
        repo,
        session_key="mobile-session-1",
        session_date="2026-11-08",
        started_at="",
        exercise_name="深蹲",
        weight_kg=80,
        reps=5,
    )
    second = append_quick_strength_set(
        repo,
        session_key="mobile-session-1",
        session_date="2026-11-08",
        started_at="",
        exercise_name="深蹲",
        weight_kg=80,
        reps=5,
    )
    assert first["set_number"] == 1
    assert second["set_number"] == 2
    assert repo.one("SELECT COUNT(*) AS n FROM strength_set")["n"] == 2
    retry = repo.append_strength_set(
        session_key="mobile-session-1",
        session_date="2026-11-08",
        data={
            "set_date": "2026-11-08",
            "exercise_name": "深蹲",
            "weight_kg": 80,
            "reps": 5,
            "set_number": 2,
        },
        force_next=False,
    )
    assert retry["set_inserted"] is False
    assert repo.one("SELECT COUNT(*) AS n FROM strength_set")["n"] == 2
    repo.close()
