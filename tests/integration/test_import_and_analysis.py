from zipfile import ZIP_DEFLATED, ZipFile

from healthzip.analytics import all_analysis, persist_analysis
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.quality import inventory, readiness


def test_stream_import_persists_supported_data_and_is_idempotent(fixture_zip, db_path):
    repo = Repository(db_path)
    first = import_apple_zip(fixture_zip, repo, include_cycle=True)
    assert first.status == "completed"
    assert first.records_inserted > 700
    assert repo.count("health_sample") > 700
    assert repo.count("workout") > 0
    count = repo.count("health_sample")
    second = import_apple_zip(fixture_zip, repo, include_cycle=True)
    assert second.status == "already_imported"
    assert repo.count("health_sample") == count
    assert inventory(repo)["sample_types"]
    q = readiness(repo)
    assert q["resting_heart_rate"]["status"] == "usable"
    result = all_analysis(repo)
    assert result["heart"]["cards"]
    # Historical nights remain visible, but no historical import is labelled
    # usable sleep in the last 24 hours without observations in that window.
    assert result["sleep"]["nights"]
    assert result["sleep"]["card"]["facts"][0]["value"] == result["v13"]["metrics"]["STATE-SLEEP-24H"]["value"]
    assert result["weight"]["card"]["status"] == "valid"
    assert result["weight"]["card"]["facts"][0]["value"] == result["v13"]["metrics"]["BODY-MASS-TREND"]["value"]
    persist_analysis(repo, result)
    assert repo.one("SELECT COUNT(*) AS n FROM insight")["n"] >= 5
    assert repo.one("SELECT COUNT(*) AS n FROM daily_feature")["n"] > 0
    repo.close()


def test_malformed_xml_is_reported_as_partial(tmp_path, db_path):
    p = tmp_path / "broken.zip"
    with ZipFile(p, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "nested/export.xml",
            '<HealthData><Record type="HKQuantityTypeIdentifierRestingHeartRate" value="55" unit="count/min" startDate="2026-11-01 08:00:00 +0800" endDate="2026-11-01 08:00:00 +0800"/><Record',
        )
    repo = Repository(db_path)
    result = import_apple_zip(p, repo)
    assert result.status == "partial_failed"
    assert result.errors_count >= 1
    repo.close()


def test_invalid_record_timestamp_is_skipped_and_reported(tmp_path, db_path):
    p = tmp_path / "invalid-date.zip"
    with ZipFile(p, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "export.xml",
            '<HealthData><Record type="HKQuantityTypeIdentifierRestingHeartRate" value="55" unit="count/min" startDate="not-a-date" endDate="not-a-date"/></HealthData>',
        )
    repo = Repository(db_path)
    result = import_apple_zip(p, repo)
    assert result.status == "partial_failed"
    assert result.records_skipped == 1
    assert repo.count("health_sample") == 0
    repo.close()
