"""Typed body queries stay bounded without changing historical revision selection."""

import json
import sqlite3

import pytest

from healthzip.db.repository import REPOSITORY_MIGRATION_REVISION, Repository
from healthzip.db.temporal_schema import QUERY_PROJECTION_VERSION, TYPE_EVENT_INDEX, samples_as_of

WINDOW = {"window_start": "2026-11-01T00:00:00Z", "window_end": "2026-11-20T00:00:00Z"}
CUTOFF = "2026-11-21T00:00:00Z"


def _revision(repo, identity, canonical, *, when="2026-11-10T12:00:00Z",
              available="2026-11-11T00:00:00Z", status="active"):
    repo.conn.execute(
        "INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
        "VALUES('health_sample',?,?,?,'synthetic')",
        (identity, available, json.dumps({"id": identity, "canonical_type": canonical,
         "start_utc": when, "end_utc": when, "record_status": status, "normalized_value": 60})),
    )


def _query(repo, cutoff=CUTOFF):
    return samples_as_of(repo, cutoff, canonical_types=["resting_heart_rate_bpm", "hrv_sdnn_ms"], **WINDOW)


def _instructions(repo):
    count = 0

    def progress():
        nonlocal count
        count += 1
        return 0

    repo.conn.set_progress_handler(progress, 1)
    try:
        rows = _query(repo)
    finally:
        repo.conn.set_progress_handler(None, 0)
    return rows, count


def test_typed_query_cost_does_not_grow_with_unrelated_in_window_samples(tmp_path):
    repo = Repository(tmp_path / "synthetic-typed.sqlite3")
    try:
        _revision(repo, 1, "resting_heart_rate_bpm")
        _revision(repo, 2, "hrv_sdnn_ms")
        repo.conn.commit()
        expected, before = _instructions(repo)
        for identity in range(3, 5003):
            _revision(repo, identity, "heart_rate_bpm")
        repo.conn.commit()
        actual, after = _instructions(repo)
        assert actual == expected
        # Count SQLite work instead of imposing machine-dependent milliseconds.
        # A scan/JSON filter over all 5,000 raw rows exceeds this by orders of magnitude.
        assert after <= before + 50, (before, after)
    finally:
        repo.close()


@pytest.mark.parametrize("change", ["type", "time", "delete"])
def test_typed_candidate_uses_latest_visible_revision_before_final_filter(tmp_path, change):
    repo = Repository(tmp_path / "synthetic-revisions.sqlite3")
    try:
        _revision(repo, 1, "resting_heart_rate_bpm")
        _revision(repo, 1, "heart_rate_bpm" if change == "type" else "resting_heart_rate_bpm",
                  when="2025-01-01T00:00:00Z" if change == "time" else "2026-11-10T12:00:00Z",
                  available="2026-11-18T00:00:00.000001Z", status="deleted" if change == "delete" else "active")
        repo.conn.commit()
        # The coarse SQL date index must not make the later revision visible early.
        assert len(_query(repo, "2026-11-18T00:00:00Z")) == 1
        assert _query(repo) == []
        _revision(repo, 1, "resting_heart_rate_bpm", available="2026-11-19T00:00:00Z")
        repo.conn.commit()
        assert len(_query(repo)) == 1
    finally:
        repo.close()


def test_existing_43_upgrade_is_additive_and_preserves_ledger_bytes(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-upgrade.sqlite3"
    repo = Repository(path)
    _revision(repo, 1, "resting_heart_rate_bpm")
    original = [tuple(row) for row in repo.rows("SELECT * FROM source_revision")]
    repo.conn.execute(f"DROP INDEX {TYPE_EVENT_INDEX}")
    repo.conn.execute("UPDATE schema_meta SET value='4.3' WHERE key='temporal_query_projection'")
    repo.conn.execute("UPDATE schema_meta SET value='1' WHERE key='repository_migration_revision'")
    repo.conn.commit()
    repo.close()
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    upgraded = Repository(path)
    try:
        assert [tuple(row) for row in upgraded.rows("SELECT * FROM source_revision")] == original
        assert upgraded.one("SELECT value FROM schema_meta WHERE key='temporal_query_projection'")[0] == QUERY_PROJECTION_VERSION
        assert upgraded.one("SELECT value FROM schema_meta WHERE key='repository_migration_revision'")[0] == str(REPOSITORY_MIGRATION_REVISION)
        assert len(_query(upgraded)) == 1
        assert not any("INSERT INTO source_revision" in sql or "UPDATE health_sample SET temporal_provenance" in sql
                       for sql in statements)
    finally:
        upgraded.close()
