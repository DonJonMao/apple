"""Actual event/training timelines and frozen actions through public question APIs."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from healthzip.advice import save_profile
from healthzip.analytics.body_metrics import analyze_questions
from healthzip.db.repository import Repository
from healthzip.science.contracts import instant
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService
from healthzip.workflows.actions import save_feedback, select_action
from tests.master_science_fixture import CUTOFF, RANGE_START, create_master_science_fixture

START = "2026-11-01T00:00:00+08:00"
SELECTED = "2026-11-15T00:00:00+08:00"


def ask(repo, qid, **kw):
    return analyze_questions(repo, question_ids=[qid], **{
        "window_start": START, "window_end": CUTOFF, "cutoff_time": CUTOFF, **kw})[0]


def add_record(repo, table, identity, at, **values):
    row = {"id": identity, "record_status": "active", **values}
    if table == "health_sample":
        row.update(start_utc=at, end_utc=at, source_name="合成测试设备",
                   source_version="1", device="synthetic", raw_type=row["canonical_type"],
                   metadata_json=json.dumps({"protocol_id": "fixed"}))
    else:
        row.update(observed_at=at, day=at[:10])
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES(?,?,?,?,'synthetic_acceptance')",
                      (table, identity, at, json.dumps(row)))
    repo.conn.commit()


def add_training(repo, *, unknown=False):
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic rack", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
                 "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
                 "rom_protocol": "synthetic-full", "settings": {}, "settings_confirmed": True}
    if unknown:
        condition = {"load_basis": "external_total_kg", "load_basis_confirmed": True}
    sessions = []
    for day, reps in ((10, 8), (20, 10)):
        at = datetime.fromisoformat(f"2026-11-{day}T17:00:00+08:00")
        recorded = (at + timedelta(hours=1)).isoformat()
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else recorded):
            session = service.start_session("合成时间链", started_at=at.isoformat())
            instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            service.add_set(instance["id"], actual={"completion_state": "completed", "set_type": "work",
                "load_value": 40, "load_unit": "kg", "reps": reps, "rir": 2,
                "ended_at": (at + timedelta(minutes=5)).isoformat()})
            service.end_session(session["id"], ended_at=(at + timedelta(minutes=45)).isoformat())
        sessions.append(session["id"])
    return sessions


def test_e_reads_actual_symptoms_timing_training_and_excludes_future(tmp_path):
    repo = Repository(tmp_path / "events.sqlite")
    sessions = add_training(repo)
    add_record(repo, "health_sample", 1, "2026-11-20T16:30:00+08:00",
               canonical_type="high_hr_event", category_value="reported")
    add_record(repo, "subjective_log", 1, "2026-11-20T18:00:00+08:00", symptoms="本人记录头晕", pain_level=2)
    add_record(repo, "subjective_log", 2, "2026-11-23T18:00:00+08:00", symptoms="未来症状")
    result = ask(repo, "E")
    assert "本人记录头晕" in result["observation"] and "未来症状" not in str(result)
    links = [r for r in result["rows"] if r["type"] == "event_training"]
    event = next(r for r in links if "高心率" in r["event_title"])
    subjective = next(r for r in links if r["event_title"] == "已记录的主观状态")
    assert event["temporal_relation"] == "记录结束在训练开始之前"
    assert subjective["temporal_relation"] == "记录开始在训练结束之后"
    assert event["session_id"] == sessions[1]
    assert float(event["actual_sets"][0]["load"]) == 40 and event["actual_sets"][0]["reps"] == 10
    assert event["actual_sets"][0]["condition_known"]
    repo.close()


@pytest.mark.parametrize("unknown", [False, True])
def test_w8_uses_repeated_actual_events_and_preserves_unknown_conditions(tmp_path, unknown):
    repo = Repository(tmp_path / "cycle.sqlite")
    sessions = add_training(repo, unknown=unknown)
    service = TrainingService(repo)
    other = service.create_exercise("合成无关动作", "repetitions", "barbell", "external_total_kg",
                                    exercise_id="custom.unrelated")["exercise_id"]
    for day in (10, 20):
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else f"2026-11-{day}T20:00:00+08:00"):
            session = service.start_session("相邻其他动作场次", started_at=f"2026-11-{day}T18:00:00+08:00")
            item = service.add_exercise(session["id"], other, {"load_basis": "external_total_kg", "load_basis_confirmed": True})
            service.add_set(item["id"], actual={"completion_state": "completed", "set_type": "work",
                "load_value": 20, "load_unit": "kg", "reps": 6, "ended_at": f"2026-11-{day}T18:10:00+08:00"})
            service.end_session(session["id"], ended_at=f"2026-11-{day}T18:30:00+08:00")
    for i, day in enumerate((10, 20), 1):
        add_record(repo, "health_sample", i, f"2026-11-{day}T16:00:00+08:00",
                   canonical_type="menstrual_flow", category_value="light")
    result = ask(repo, "W8")
    pairs = [r for r in result["rows"] if r["type"] == "event_set_pair" and r["exercise"] == "杠铃平板卧推"]
    assert len(pairs) == 1 and pairs[0]["first_session_id"] == sessions[0]
    assert pairs[0]["first_value"] == 8 and pairs[0]["value"] == 10
    assert pairs[0]["difference"] == (None if unknown else 2)
    assert pairs[0]["comparable"] is not unknown
    assert any("不按日历推测相位" in text for text in result["limitations"])
    assert all("phase" not in r for r in result["rows"])
    repo.close()


def test_w3_w7_keep_estimate_support_and_version_ceiling(tmp_path):
    path = tmp_path / "master.sqlite"
    create_master_science_fixture(path)
    repo = Repository(path)
    for qid in ("W3", "W7"):
        result = ask(repo, qid, window_start=RANGE_START)
        row = next(r for r in result["rows"] if r.get("metric") == "six_minute_walk_m")
        assert row["observation_count"] == 2
        assert row["publication_count"] == 0  # observation timestamps are not publication timestamps
        assert row["estimate_support"]["overlaps_prior_window"]
        assert row["estimate_support"]["upper_limit_m"] is None
        assert row["estimate_support"]["at_reportable_limit"] is None
        assert len(row["estimate_observations"]) == 2
        assert "独立测试" in row["support_limitation"]
        assert any("重叠窗口" in text for text in result["limitations"])
    repo.close()


def test_w4_empty_repo_and_profile_action_feedback_cache_asof(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "actions.sqlite")
    empty = ask(repo, "W4")
    assert empty["goal_context"]["title"] == "尚未选择目标" and not empty["action_reviews"]
    add_training(repo)
    save_profile(repo, {"training_goal": "strength"})
    repo.conn.execute("UPDATE advice_profile_revision SET recorded_at=?", (START,))
    repo.conn.commit()
    baseline = ask(repo, "W4", window_end=SELECTED, cutoff_time=SELECTED)
    identity = select_action(repo, baseline, baseline["steps"][0], "2026-11-30T00:00:00+08:00", selected_at=SELECTED)
    monkeypatch.setattr("healthzip.workflows.actions.followup", lambda *_a, **_k: pytest.fail("recursive followup"))
    frozen_json = repo.one("SELECT baseline_json FROM review_action WHERE action_id=?", (identity,))[0]
    first = ask(repo, "W4", timezone_name="UTC")
    review = first["action_reviews"][0]
    assert first["goal_context"]["goal"] == "strength"
    assert review["execution_status"] == "unreported" and review["method_matches"]
    assert not review["view_timezone_matches"]
    assert review["followup_window"]["timezone"] == "Asia/Shanghai"
    strength = next(o for o in review["observations"] if o["type"] == "strength")
    assert (strength["first_value"], strength["value"], strength["difference"]) == (8, 10, 2)
    assert review["status"] == "partial_window"
    save_feedback(repo, identity, "executed", "已按实际计划执行", None, event_id="feedback")
    repo.conn.execute("UPDATE review_action_event SET recorded_at='2026-11-21T12:00:00+08:00'")
    repo.conn.commit()
    second = ask(repo, "W4", timezone_name="UTC")
    assert second["fact_id"] != first["fact_id"]
    assert second["action_reviews"][0]["execution_label"] == "已执行"
    historical = ask(repo, "W4", cutoff_time="2026-11-21T00:00:00+08:00")
    save_feedback(repo, identity, "stopped", "未来反馈", None, event_id="future")
    repo.conn.execute("UPDATE review_action_event SET recorded_at='2026-11-23T12:00:00+08:00' WHERE event_id='future'")
    save_profile(repo, {"training_goal": "hypertrophy"})
    repo.conn.execute("UPDATE advice_profile_revision SET recorded_at='2026-11-23T12:00:00+08:00' WHERE revision=(SELECT max(revision) FROM advice_profile_revision)")
    repo.conn.commit()
    assert ask(repo, "W4", cutoff_time="2026-11-21T00:00:00+08:00") == historical
    assert ask(repo, "W4", timezone_name="UTC") == second
    repo.conn.execute("UPDATE advice_profile_revision SET recorded_at='2026-11-21T12:00:00+08:00' WHERE revision=(SELECT max(revision) FROM advice_profile_revision)")
    repo.conn.commit()
    assert ask(repo, "W4")["goal_context"]["goal"] == "hypertrophy"
    assert repo.one("SELECT baseline_json FROM review_action WHERE action_id=?", (identity,))[0] == frozen_json
    repo.close()


def test_action_dynamic_metric_dependency_and_source_identity(tmp_path):
    repo = Repository(tmp_path / "dynamic.sqlite")
    add_training(repo)
    def oxygen(i, at, value, version="1"):
        add_record(repo, "health_sample", i, at, canonical_type="oxygen_saturation_fraction",
                   normalized_value=value, normalized_unit="fraction", raw_unit="fraction", raw_value=str(value))
        if version != "1":
            payload = json.loads(repo.one("SELECT payload_json FROM source_revision WHERE table_name='health_sample' AND record_id=?", (i,))[0])
            payload["source_version"] = version
            repo.conn.execute("UPDATE source_revision SET payload_json=? WHERE table_name='health_sample' AND record_id=?", (json.dumps(payload),i))
            repo.conn.commit()
    oxygen(1, "2026-11-10T08:00:00+08:00", 0.97)
    baseline = ask(repo, "W6", window_end=SELECTED, cutoff_time=SELECTED, source_filter=["合成测试设备"])
    assert any(r.get("metric") == "oxygen_saturation_fraction" for r in baseline["rows"])
    select_action(repo, baseline, baseline["steps"][0], "2026-11-30T00:00:00+08:00", selected_at=SELECTED)
    prior = ask(repo, "W4")
    oxygen(2, "2026-11-20T08:00:00+08:00", 0.98)
    current = ask(repo, "W4")
    assert prior["fact_id"] != current["fact_id"]
    observed = next(o for o in current["action_reviews"][0]["observations"] if o.get("metric") == "oxygen_saturation_fraction")
    assert observed["difference"] == pytest.approx(0.01)
    oxygen(3, "2026-11-21T08:00:00+08:00", 0.90, version="2")
    revised = ask(repo, "W4")
    observed = next(o for o in revised["action_reviews"][0]["observations"] if o.get("metric") == "oxygen_saturation_fraction")
    assert observed["value"] == 0.98
    assert instant(revised["action_reviews"][0]["followup_window"]["end"]) == instant(CUTOFF)
    repo.close()
