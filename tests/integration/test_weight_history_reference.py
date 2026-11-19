"""An empty weight window can show dated history without changing its metrics."""

import pytest

from healthzip.analytics.workspaces import analyze_workspace
from healthzip.db.repository import Repository

CUTOFF = "2026-11-18T12:00:00+00:00"


def add_sample(repo, name, event, value, unit="kg", *, available="2026-10-18T00:00:00+00:00"):
    assert repo.insert_sample(1, {"fingerprint": name, "raw_type": "HKQuantityTypeIdentifierBodyMass",
        "canonical_type": "body_mass_kg", "raw_value": str(value), "raw_unit": unit,
        "normalized_value": value, "normalized_unit": unit, "start_utc": event,
        "end_utc": event, "local_date": event[:10], "source_name": "合成称重来源",
        "created_at": available})
    identifier = repo.one("SELECT id FROM health_sample WHERE fingerprint=?", (name,))[0]
    repo.conn.execute("UPDATE source_revision SET available_at=? "
                      "WHERE table_name='health_sample' AND record_id=?", (available, identifier))
    return identifier


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repository = Repository(tmp_path / "synthetic-weight-history.sqlite3")
    repository.create_batch(file_sha256="synthetic", file_name="synthetic", file_size=0, xml_member_path="")
    try:
        yield repository
    finally:
        repository.close()


def test_recent_history_retains_actual_date_units_and_visibility_outside_window(repo):
    add_sample(repo, "older", "2025-05-01T02:00:00+00:00", 70)
    latest_id = add_sample(repo, "latest", "2026-09-15T23:30:00+00:00", 180, "lb")
    add_sample(repo, "unit-unknown", "2026-10-01T02:00:00+00:00", 99, "unknown")
    add_sample(repo, "late-import", "2026-10-02T02:00:00+00:00", 75,
               available="2026-11-19T00:00:00+00:00")
    repo.conn.commit()
    output = analyze_workspace(repo, "体重 / 有氧", cutoff_time=CUTOFF)
    assert output["weight"]["daily"] == []
    metrics = output["workspace_scope"]["metrics"]
    assert metrics["BODY-MASS-DAILY"]["value"] is None
    assert metrics["BODY-MASS-TREND"]["value"] is None
    point, = output["weight"]["latest_observations"]
    assert point["date"] == "2026-09-16"  # Actual event in the selected display timezone.
    assert point["event_end"] == "2026-09-15T23:30:00+00:00"
    assert point["value"] == pytest.approx(180 * 0.45359237) and point["unit"] == "kg"
    assert point["source_record_ids"] == [f"health_sample:{latest_id}"]
    assert point["numeric_provenance"]["raw_unit"] == "lb"
    scope = output["workspace_scope"]["history_reference"]
    assert scope["scope"] == "outside_selected_window" and not scope["included_in_window_metrics"]
    assert scope["searched_time_pages"] == 1
    assert not repo.conn.in_transaction


def test_visible_moved_and_deleted_records_do_not_resurrect_old_weight(repo):
    older = add_sample(repo, "older", "2025-05-01T02:00:00+00:00", 70)
    moved = add_sample(repo, "moved", "2026-09-15T02:00:00+00:00", 72)
    add_sample(repo, "unit-unknown", "2026-09-20T02:00:00+00:00", 99, "unknown")
    repo.conn.execute("UPDATE health_sample SET start_utc='2026-12-01T00:00:00Z',"
                      "end_utc='2026-12-01T00:00:00Z' WHERE id=?", (moved,))
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-17T00:00:00Z' "
                      "WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision WHERE record_id=?)", (moved,))
    repo.conn.commit()
    result = analyze_workspace(repo, "体重 / 有氧", cutoff_time=CUTOFF)
    assert result["weight"]["latest_observations"][0]["date"] == "2025-05-01"
    assert result["workspace_scope"]["history_reference"]["searched_time_pages"] == 2
    repo.conn.execute("UPDATE health_sample SET record_status='deleted' WHERE id=?", (older,))
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-17T00:00:00Z' "
                      "WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision WHERE record_id=?)", (older,))
    repo.conn.commit()
    assert analyze_workspace(repo, "体重 / 有氧", cutoff_time=CUTOFF)["weight"]["latest_observations"] == []


def test_history_page_start_boundary_keeps_its_true_date(repo):
    add_sample(repo, "page-start", "2025-10-19T12:00:00+00:00", 71)
    repo.conn.commit()
    output = analyze_workspace(repo, "体重 / 有氧", cutoff_time=CUTOFF)
    point, = output["weight"]["latest_observations"]
    assert point["event_end"] == "2025-10-19T12:00:00+00:00"
    assert output["workspace_scope"]["history_reference"]["searched_time_pages"] == 1


def test_body_measurement_history_uses_its_own_timestamp_source_and_unit(repo):
    repo.conn.execute("INSERT INTO body_measurement(fingerprint,measured_at,local_date,value,unit,canonical_type,source) "
                      "VALUES('synthetic-body','2026-09-20T00:00:00Z','2026-09-20',154,'lb','body_mass_kg','手工称重')")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-09-21T00:00:00Z' "
                      "WHERE table_name='body_measurement'")
    repo.conn.commit()
    output = analyze_workspace(repo, "体重 / 有氧", cutoff_time=CUTOFF)
    point, = output["weight"]["latest_observations"]
    assert point["date"] == "2026-09-20" and point["source"] == "手工称重"
    assert point["value"] == pytest.approx(154 * 0.45359237)
    assert point["source_record_ids"][0].startswith("body_measurement:")
    assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 0
