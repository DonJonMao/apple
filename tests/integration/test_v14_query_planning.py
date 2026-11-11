"""Window planning must preserve latest-visible revisions without loading history."""
from datetime import datetime, timedelta, timezone

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.db.temporal_schema import samples_as_of


def _sample(repo, identity, when, value=60):
    repo.insert_sample(1, {
        "fingerprint": identity, "canonical_type": "resting_heart_rate_bpm",
        "raw_type": "HKQuantityTypeIdentifierRestingHeartRate", "raw_value": str(value),
        "raw_unit": "count/min", "normalized_value": value, "normalized_unit": "bpm",
        "unit_status": "canonical", "start_utc": when, "end_utc": when,
        "local_date": when[:10], "source_name": "Synthetic Query Test", "created_at": when,
    })


def _repo(tmp_path):
    repo = Repository(tmp_path / "synthetic-query.sqlite3")
    repo.create_batch(file_sha256="synthetic", file_name="synthetic", file_size=0, xml_member_path="")
    return repo


def test_f13_outside_history_is_not_deserialized_for_default_analysis(tmp_path):
    repo = _repo(tmp_path)
    for i in range(1000):
        _sample(repo, str(i), (datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat())
    repo.conn.commit()
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    counts = []
    original = repo.rows

    def counted(sql, parameters=()):
        rows = original(sql, parameters)
        if "source_revision" in sql and "payload_json" in sql:
            counts.append(len(rows))
        elif "SELECT * FROM source_revision" in sql:
            counts.append(len(rows))
        return rows

    repo.rows = counted
    result = analyze(repo, 30, cutoff_time=cutoff.isoformat())
    assert result["metrics"]["STATE-RHR"]["value"] is None
    assert counts and sum(counts) == 0, "Window-external payloads must stay in SQLite"
    repo.close()


def test_f13_window_filter_cannot_revive_moved_or_deleted_revision(tmp_path):
    repo = _repo(tmp_path)
    _sample(repo, "moving", "2026-11-01T12:00:00+00:00")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-02T00:00:00Z'")
    repo.conn.execute("UPDATE health_sample SET start_utc='2025-01-01T12:00:00Z',end_utc='2025-01-01T12:00:00Z'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-04T00:00:00Z' WHERE revision_id=2")
    window = {"window_start": "2026-11-01T00:00:00Z", "window_end": "2026-11-03T00:00:00Z"}
    original = samples_as_of(repo, "2026-11-03T00:00:00Z", **window)
    assert len(original) == 1 and original[0]["normalized_value"] == 60
    assert samples_as_of(repo, "2026-11-05T00:00:00Z", **window) == []
    repo.conn.execute("UPDATE health_sample SET start_utc='2026-11-01T12:00:00Z',end_utc='2026-11-01T12:00:00Z',record_status='deleted'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-06T00:00:00Z' WHERE revision_id=3")
    assert samples_as_of(repo, "2026-11-07T00:00:00Z", **window) == []
    assert samples_as_of(repo, "2026-11-03T00:00:00Z", **window)[0]["record_status"] == "active"
    repo.close()


def test_f13_interval_overlap_and_points_keep_half_open_bounds(tmp_path):
    repo = _repo(tmp_path)
    for identity, when in (("start", "2026-11-01T00:00:00Z"), ("end", "2026-11-02T00:00:00Z")):
        _sample(repo, identity, when)
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-02T01:00:00Z'")
    rows = samples_as_of(repo, "2026-11-03T00:00:00Z", window_start="2026-11-01T00:00:00Z", window_end="2026-11-02T00:00:00Z")
    assert [r["fingerprint"] for r in rows] == ["start"]
    repo.close()


def test_cache_reuses_exact_snapshot_and_invalidates_input_timezone_and_context(tmp_path):
    repo = _repo(tmp_path)
    at = datetime.now(timezone.utc) - timedelta(days=1)
    _sample(repo, "cached", at.isoformat())
    repo.conn.commit()
    cutoff = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
    first = analyze(repo, cutoff_time=cutoff)
    calls = []
    original = repo.rows

    def counted(sql, parameters=()):
        calls.append(sql)
        return original(sql, parameters)

    repo.rows = counted
    second = analyze(repo, cutoff_time=cutoff)
    assert first == second and not calls
    second["metrics"].clear()
    assert analyze(repo, cutoff_time=cutoff)["metrics"], "Caller mutation cannot corrupt cached facts"
    repo.conn.execute("UPDATE health_sample SET raw_value='72',normalized_value=72")
    repo.conn.commit()
    revised = analyze(repo, cutoff_time=cutoff)
    assert calls and revised["data_hash"] != first["data_hash"]
    calls.clear()
    changed_zone = analyze(repo, cutoff_time=cutoff, timezone_name="UTC")
    assert changed_zone["timezone"] == "UTC" and calls
    calls.clear()
    analyze(repo, cutoff_time=cutoff, context={"protocol_version": "new"})
    assert calls
    repo.close()


def test_apple_child_metadata_and_normalization_version_survive_import(tmp_path):
    import json
    from zipfile import ZipFile

    from healthzip.importers.apple_xml import import_apple_zip
    from healthzip.normalize import UNIT_CONVERSION_VERSION

    path = tmp_path / "synthetic-metadata.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", '<HealthData><Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" '
            'unit="s" value="0.05" startDate="2026-11-01 12:00:00 +0800" endDate="2026-11-01 12:00:00 +0800">'
            '<MetadataEntry key="HKWasUserEntered" value="1"/><MetadataEntry key="HKMetadataKeySyncIdentifier" value="synthetic-id"/>'
            '<MetadataEntry key="duplicate-key" value="first"/><MetadataEntry key="duplicate-key" value="second"/>'
            '</Record></HealthData>')
    repo = _repo(tmp_path)
    result = import_apple_zip(path, repo)
    assert result.records_inserted == 1
    sample = dict(repo.one("SELECT * FROM health_sample"))
    metadata = json.loads(sample["metadata_json"])
    assert len(metadata["MetadataEntry"]) == 4
    assert metadata["MetadataEntry"][-1]["value"] == "second"
    assert metadata["unit_normalization"]["version"] == UNIT_CONVERSION_VERSION
    assert sample["normalized_value"] == 50 and sample["raw_value"] == "0.05"
    repo.close()


def test_index_padding_never_relaxes_exact_microsecond_cutoff_or_window(tmp_path):
    repo = _repo(tmp_path)
    _sample(repo, "micro", "2026-11-01T12:00:00.000001Z")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-02T00:00:00.000001Z'")
    repo.conn.execute("UPDATE health_sample SET normalized_value=80,raw_value='80'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-02T00:00:00.000002Z' WHERE revision_id=2")
    bounds = {"window_start": "2026-11-01T12:00:00.000000Z", "window_end": "2026-11-01T12:00:00.000002Z"}
    assert samples_as_of(repo, "2026-11-02T00:00:00.000001Z", **bounds)[0]["normalized_value"] == 60
    assert samples_as_of(repo, "2026-11-02T00:00:00.000002Z", **bounds)[0]["normalized_value"] == 80
    bounds["window_end"] = "2026-11-01T12:00:00.000001Z"
    assert samples_as_of(repo, "2026-11-02T00:00:00.000002Z", **bounds) == []
    repo.close()
