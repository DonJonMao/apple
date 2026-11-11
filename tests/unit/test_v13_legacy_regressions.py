from datetime import date, datetime, timedelta, timezone

import pytest

from healthzip.ai.client import validate_ai_result
from healthzip.analytics.core import heart_analysis, weight_analysis
from healthzip.analytics.p1 import body_state, body_state_strength, strength_quality
from healthzip.db.repository import Repository
from healthzip.db.temporal_schema import samples_as_of
from healthzip.strength_log import save_strength_log
from healthzip.temporal import sleep_nights


def sample(repo, typ, value, day, *, category=None, end=None):
    batch = repo.create_batch(file_sha256=str(day)+typ+str(value)+str(category), file_name="synthetic", file_size=0, xml_member_path="")
    repo.insert_sample(batch, {"fingerprint": str(batch), "raw_type": typ, "canonical_type": typ,
        "normalized_value": value, "local_date": day.date().isoformat(), "start_utc": day.isoformat(),
        "end_utc": (end or day).isoformat(), "created_at": datetime.now(timezone.utc).isoformat(),
        "category_value": category, "utc_offset_minutes": 480, "source_name": "synthetic"})
    repo.conn.commit()


def test_heart_window_counts_days_and_weight_uses_real_spacing(tmp_path):
    repo = Repository(tmp_path / "test.sqlite3")
    today = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    for day in range(30):
        for hour in (1, 8, 16):
            sample(repo, "hrv_sdnn_ms", 45+day % 4, today-timedelta(days=day)+timedelta(hours=hour))
    card = heart_analysis(repo, 30)["cards"][1]
    assert card["facts"][0]["n_days"] == 30
    for week in range(5):
        sample(repo, "body_mass_kg", 80+week, today-timedelta(days=week*7))
    assert weight_analysis(repo, 30)["slope_kg_per_day"]*7 == pytest.approx(-1)
    repo.close()


def test_sleep_excludes_inbed_uses_local_wake_date_and_window():
    start = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
    def row(identity, stage, hours):
        return {"id": identity, "start_utc": start.isoformat(), "end_utc": (start+timedelta(hours=hours)).isoformat(),
                "category_value": stage, "utc_offset_minutes": 480}
    rows = [row(1, "HKCategoryValueSleepAnalysisInBed", 8), row(2, "HKCategoryValueSleepAnalysisAsleep", 7), row(3, "HKCategoryValueSleepAnalysisAsleepCore", 3)]
    nights = sleep_nights(rows, "2026-11-02", "2026-11-02")
    assert len(nights) == 1
    assert nights[0]["sleep_hours"] == 7
    assert sleep_nights(rows, "2026-11-03", "2026-11-03") == []


def test_source_revision_preserves_original_cutoff_after_edit_and_delete(tmp_path):
    repo = Repository(tmp_path / "test.sqlite3")
    event = datetime.now(timezone.utc)-timedelta(days=1)
    sample(repo, "resting_heart_rate_bpm", 60, event)
    original = dict(repo.one("SELECT * FROM source_revision ORDER BY revision_id LIMIT 1"))
    # Freeze an explicit deterministic knowledge-time boundary (not event time).
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-01T00:00:00Z'")
    repo.conn.execute("UPDATE health_sample SET normalized_value=62")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-03T00:00:00Z' WHERE revision_id>?", (original["revision_id"],))
    assert samples_as_of(repo, "2026-11-02T00:00:00Z")[0]["normalized_value"] == 60
    repo.conn.execute("UPDATE health_sample SET record_status='deleted'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-05T00:00:00Z' WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)")
    assert samples_as_of(repo, "2026-11-04T00:00:00Z")[0]["normalized_value"] == 62
    assert samples_as_of(repo, "2026-11-06T00:00:00Z") == []
    repo.close()


def test_future_and_backfilled_state_never_enters_training_pair(tmp_path):
    repo = Repository(tmp_path / "test.sqlite3")
    day = datetime.now(timezone.utc)-timedelta(days=2)
    save_strength_log(repo, session_date=day.date().isoformat(), started_at=day.isoformat(), name="synthetic", notes="",
                      sets=[{"exercise_name": "test", "weight_kg": 30, "reps": 10}])
    sample(repo, "resting_heart_rate_bpm", 60, day-timedelta(hours=2))  # received after session
    sample(repo, "hrv_sdnn_ms", 50, day+timedelta(days=1))  # future event
    assert body_state_strength(repo)["joins"][0]["body_state"] is None
    assert body_state(repo)  # still available for honest retrospective description
    repo.close()


def test_same_day_sessions_stay_separate_and_set_rpe_is_not_srpe(tmp_path):
    repo = Repository(tmp_path / "test.sqlite3")
    for name in ("morning", "evening"):
        save_strength_log(repo, session_date=date.today().isoformat(), name=name, notes="", started_at="",
                          sets=[{"exercise_name": "squat", "weight_kg": 50, "reps": 8, "rpe": 8}])
    sessions = strength_quality(repo)["sessions"]
    assert len(sessions) == 2
    assert all(x["session_rpe"] is None and x["session_rpe_load"] is None for x in sessions)
    repo.close()


@pytest.mark.parametrize("summary", ["睡眠不足导致力量下降。", "建议降低5%重量。", "57 kg", "静息心率下降57 bpm。", "明天静息心率为57 bpm。"])
def test_ai_summary_cannot_bypass_evidence(summary):
    card = {"id": "rhr", "summary": "今日静息心率57 bpm。", "window": {"start": "2026-11-01", "end": "2026-11-02"},
            "facts": [{"metric": "rhr", "value": 57, "unit": "bpm"}], "allowed_actions": ["observe"]}
    with pytest.raises(ValueError):
        validate_ai_result({"summary": summary, "evidence_ids": ["rhr"], "actions": ["observe"]}, {"evidence": [card]})


def test_ai_fact_unit_must_match():
    card = {"id": "rhr", "summary": "57 bpm", "facts": [{"metric": "rhr", "value": 57, "unit": "bpm"}], "allowed_actions": ["observe"]}
    with pytest.raises(ValueError):
        validate_ai_result({"summary": "57 bpm", "evidence_ids": ["rhr"], "actions": ["observe"],
                           "facts": [{"evidence_id": "rhr", "metric": "rhr", "value": 57, "unit": "kg"}]}, {"evidence": [card]})


def test_ai_cannot_hide_prescription_in_limitations():
    card = {"id": "rhr", "summary": "57 bpm", "limitations": ["样本有限"], "allowed_actions": ["observe"]}
    with pytest.raises(ValueError):
        validate_ai_result({"summary": "57 bpm", "evidence_ids": ["rhr"], "actions": ["observe"],
                           "limitations": ["请减重5%，因为睡眠会导致力量下降。"]}, {"evidence": [card]})
    result = validate_ai_result({"summary": "57 bpm", "evidence_ids": ["rhr"], "actions": ["observe"]}, {"evidence": [card]})
    assert "样本有限" in result["limitations"]
