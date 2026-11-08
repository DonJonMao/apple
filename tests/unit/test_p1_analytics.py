from datetime import date, timedelta

from healthzip.analytics import (
    all_analysis,
    period_report,
    persist_analysis,
    strength_quality,
    today_training_setup,
)
from healthzip.db.repository import Repository
from healthzip.normalize import stable_fingerprint
from healthzip.strength_log import save_strength_log


def _save_set(repo: Repository, day: date, weight: float) -> None:
    save_strength_log(
        repo,
        session_date=day.isoformat(),
        started_at="",
        name="推训练习",
        notes="",
        sets=[
            {
                "exercise_name": "卧推",
                "equipment": "杠铃",
                "variation": "平板",
                "weight_kg": weight,
                "reps": 8,
                "rir": 2,
                "rpe": 8,
                "warmup": False,
                "set_number": 1,
            }
        ],
    )


def test_p1_strength_quality_setup_and_persistence(db_path):
    repo = Repository(db_path)
    today = date.today()
    _save_set(repo, today - timedelta(days=14), 60)
    _save_set(repo, today - timedelta(days=7), 62)
    _save_set(repo, today - timedelta(days=1), 64)
    subjective_day = (today - timedelta(days=1)).isoformat()
    repo.insert_external(
        "subjective_log",
        {
            "fingerprint": stable_fingerprint([subjective_day, "fatigue", 3]),
            "day": subjective_day,
            "energy_level": 7,
            "fatigue": 3,
            "soreness": 2,
            "stress": 2,
            "sleep_quality": 7,
        },
        [
            "fingerprint",
            "day",
            "energy_level",
            "fatigue",
            "soreness",
            "stress",
            "sleep_quality",
        ],
    )

    quality = strength_quality(repo)
    assert quality["series"][0]["exposures"] == 3
    assert quality["series"][0]["e1rm_change_kg"] > 0
    assert quality["card"]["source_feature_ids"]

    setup = today_training_setup(
        repo,
        "卧推",
        equipment="杠铃",
        variation="平板",
        today=today.isoformat(),
    )
    assert setup["range_kg"]["low"] == 60.8
    assert setup["range_kg"]["high"] == 64.0

    report = period_report(repo, "week", today.isoformat())
    assert report["card"]["status"] == "usable"
    assert report["recommendations"]
    assert report["association"]["paired_metrics"]
    analysis = all_analysis(repo, 30)
    persist_analysis(repo, analysis)
    assert repo.one("SELECT COUNT(*) AS n FROM insight")["n"] >= 10
    assert (
        repo.one("SELECT COUNT(*) AS n FROM daily_feature WHERE metric='strength_volume'")["n"] > 0
    )
    feature = repo.one(
        "SELECT algorithm_version,source_ids_json,sample_count FROM daily_feature "
        "WHERE metric='strength_volume' ORDER BY local_date DESC LIMIT 1"
    )
    assert feature["algorithm_version"] == "p1-0.1.0"
    assert "strength_set:" in feature["source_ids_json"]
    assert feature["sample_count"] == 1
    repo.close()


def test_same_day_strength_sessions_with_different_sets_are_not_merged(db_path):
    repo = Repository(db_path)
    day = date.today().isoformat()
    first = {
        "exercise_name": "卧推",
        "weight_kg": 60,
        "reps": 8,
        "set_number": 1,
    }
    second = {
        "exercise_name": "深蹲",
        "weight_kg": 80,
        "reps": 5,
        "set_number": 1,
    }
    save_strength_log(
        repo,
        session_date=day,
        started_at="",
        name="训练 A",
        notes="",
        sets=[first],
    )
    save_strength_log(
        repo,
        session_date=day,
        started_at="",
        name="训练 A",
        notes="",
        sets=[second],
    )
    assert repo.one("SELECT COUNT(*) AS n FROM strength_session")["n"] == 2
    assert repo.one("SELECT COUNT(*) AS n FROM strength_set")["n"] == 2
    duplicate = save_strength_log(
        repo,
        session_date=day,
        started_at="",
        name="训练 A",
        notes="",
        sets=[first],
    )
    assert duplicate["session_inserted"] is False
    assert duplicate["sets_inserted"] == 0
    repo.close()
