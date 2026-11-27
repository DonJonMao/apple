"""Independent synthetic checks for T08–T12; actual Repository and metric paths."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.db.repository import Repository
from healthzip.science.contracts import instant
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService
from healthzip.workflows.actions import (
    followup,
    outcome_options,
    save_feedback,
    select_action,
)

START = "2026-08-01T00:00:00Z"
END = "2026-08-05T00:00:00Z"
SELECTED = "2026-08-10T00:00:00Z"
STOP = "2026-08-14T00:00:00Z"


def sample(repo, identity, day, value, *, metric="resting_heart_rate_bpm", source="Synthetic A",
           posture=None, available=None):
    at = f"2026-08-{day:02d}T08:00:00Z"
    metadata = {"protocol_id": "declared-protocol"}
    if posture:
        metadata["posture"] = posture
    unit = "bpm" if metric == "resting_heart_rate_bpm" else "ms"
    payload = {"id": identity, "canonical_type": metric, "normalized_value": value,
               "normalized_unit": unit, "raw_value": str(value), "raw_unit": unit,
               "source_name": source, "device": "synthetic-device", "source_version": "1",
               "start_utc": at, "end_utc": at, "record_status": "active",
               "metadata_json": json.dumps(metadata)}
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic')",
        (identity, available or at, json.dumps(payload)))
    repo.conn.commit()


def baseline(repo, *, qid="W4"):
    return analyze_questions(repo, window_start=START, window_end=END, cutoff_time=END,
                             timezone_name="UTC", question_ids=[qid])[0]


def choose(repo, question, *, primary=None, due="2026-08-12T12:00:00Z"):
    return select_action(repo, question, question["steps"][0], due,
        selected_at=SELECTED, planned_start=SELECTED, primary=primary)


def populate(repo):
    for i, (day, value) in enumerate([(1, 60), (2, 61), (3, 90), (10, 64), (11, 66), (12, 65)], 1):
        sample(repo, i, day, value)
    for i, (day, value) in enumerate([(1, 30), (2, 90), (3, 60), (10, 20), (11, 30), (12, 10)], 100):
        sample(repo, i, day, value, metric="hrv_sdnn_ms")


def test_primary_fixed_order_invariant_and_period_median_not_last_record(tmp_path):
    repo = Repository(tmp_path / "fixed.sqlite")
    populate(repo)
    q = baseline(repo)
    q["rows"].append({"type": "metric", "metric": "hrv_sdnn_ms", "value": 999, "title": "背景"})
    primary = {"kind": "metric", "metric": "resting_heart_rate_bpm"}
    first_id = choose(repo, q, primary=primary)
    reversed_id = choose(repo, {**q, "rows": list(reversed(q["rows"]))}, primary=primary)
    a, b = (followup(repo, identity, cutoff_time=STOP)["review"] for identity in (first_id, reversed_id))
    assert a["summary"] == b["summary"]
    row = a["primary_observations"][0]
    assert (row["first_value"], row["value"], row["difference"]) == (61, 65, 4)
    assert row["baseline"]["recorded_days"] == row["current"]["recorded_days"] == 3
    assert row["baseline"]["window_days"] == row["current"]["window_days"] == 4
    assert len(row["baseline_source_record_ids"]) == len(row["source_record_ids"]) == 3
    assert a["secondary_observations"][0]["difference"] == -40
    assert "61.0 bpm → 65.0 bpm" in a["summary"] and "60.0 ms → 20.0 ms" not in a["summary"]
    repo.close()


@pytest.mark.parametrize("status", ["unknown", "not_executed", "partial", "executed", "stopped"])
def test_execution_does_not_imply_full_window_or_causal_success(tmp_path, status):
    repo = Repository(tmp_path / "execution.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    save_feedback(repo, identity, status, "合成执行反馈", None, event_id="feedback",
                  recorded_at="2026-08-12T09:00:00Z")
    review = followup(repo, identity, cutoff_time="2026-08-12T18:00:00Z")["review"]
    assert review["status"] == "partial_window" and review["review_due_reached"]
    assert review["definition"]["early_review"]
    assert review["execution"]["started_at"] is None
    assert review["execution_status"] == status
    assert "阶段观察" in review["summary"]
    assert "改善" not in review["summary"] and "成功" not in review["summary"]
    assert review["followup_window"]["planned_end"] == instant(STOP).isoformat()
    repo.close()


def test_late_start_early_stop_preserves_original_planned_window(tmp_path):
    repo = Repository(tmp_path / "late.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    save_feedback(repo, identity, "stopped", "提前停止", None, event_id="late",
        actual_start="2026-08-11T09:00:00Z", actual_end="2026-08-12T08:00:00Z",
        recorded_at="2026-08-12T10:00:00Z")
    review = followup(repo, identity, cutoff_time=STOP)["review"]
    assert review["followup_window"]["start"] == instant(SELECTED).isoformat()
    assert review["followup_window"]["end"] == instant(STOP).isoformat()
    assert "延迟开始" in review["summary"] and "提前结束" in review["summary"]
    with pytest.raises(ValueError, match="未执行"):
        save_feedback(repo, identity, "not_executed", "", None, event_id="bad",
            actual_start="2026-08-11T00:00:00Z")
    repo.close()


def test_measurement_action_primary_is_actual_conditions_unknown_stays_unknown(tmp_path):
    repo = Repository(tmp_path / "conditions.sqlite")
    for i, day in enumerate((1, 2, 10, 11), 1):
        sample(repo, i, day, 30 + i, metric="hrv_sdnn_ms")
    q = baseline(repo, qid="W6")
    assert outcome_options(q, q["steps"][0])[0]["kind"] == "measurement_conditions"
    identity = choose(repo, q)
    review = followup(repo, identity, cutoff_time=STOP)["review"]
    primary = review["primary_observations"][0]
    assert primary["type"] == "measurement_conditions"
    assert primary["current"]["record_count"] == 2
    assert primary["current"]["posture_known_count"] == 0
    assert primary["current"]["local_times"] == ["08:00:00"]
    assert not primary["current"]["condition_known"] and primary["difference"] is None
    assert "0 条明确记录姿势" in review["summary"]
    assert review["secondary_observations"][0]["metric"] == "hrv_sdnn_ms"
    repo.close()


def test_old_action_and_saved_feedback_are_not_rewritten_or_given_a_definition(tmp_path):
    repo = Repository(tmp_path / "legacy.sqlite")
    q = baseline(repo)
    frozen = json.dumps(q)
    repo.conn.execute("INSERT INTO review_action(action_id,user_id,question_id,selected_at,review_due,action_text,baseline_json,source_filter_json) VALUES(?,?,?,?,?,?,?,?)",
        ("old", "local", "W4", SELECTED, STOP, "旧行动原文", frozen, "[]"))
    repo.conn.execute("INSERT INTO review_action_event(event_id,action_id,recorded_at,status,notes,result_json) VALUES(?,?,?,?,?,?)",
        ("old-event", "old", "2026-08-11T00:00:00Z", "partial", "旧反馈", '{"old": "frozen"}'))
    repo.conn.commit()
    before = tuple(repo.one("SELECT * FROM review_action WHERE action_id='old'"))
    review = followup(repo, "old", cutoff_time=STOP)["review"]
    assert review["definition_status"] == "not_prespecified" and not review["primary_observations"]
    assert review["saved_feedback_result"] == {"old": "frozen"}
    assert tuple(repo.one("SELECT * FROM review_action WHERE action_id='old'")) == before
    assert repo.one("SELECT baseline_json FROM review_action WHERE action_id='old'")[0] == frozen
    repo.close()


def test_correction_new_review_preserves_old_freeze_and_historical_cutoff(tmp_path):
    repo = Repository(tmp_path / "revision.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    original = followup(repo, identity, cutoff_time=STOP)
    save_feedback(repo, identity, "partial", "第一次复评", original, event_id="v1", recorded_at=STOP)
    frozen = repo.one("SELECT result_json FROM review_action_event WHERE event_id='v1'")[0]
    sample(repo, 4, 10, 180, available="2026-08-15T00:00:00Z")
    # Compare the same observation window with a later availability cutoff.
    updated = followup(repo, identity, cutoff_time="2026-08-16T00:00:00Z")
    assert updated["review"]["primary_observations"][0]["value"] == 66
    assert updated["evaluation_id"] != original["evaluation_id"]
    assert followup(repo, identity, cutoff_time=STOP)["review"]["primary_observations"][0]["value"] == 65
    save_feedback(repo, identity, "partial", "更正后的复评", updated, event_id="v2", recorded_at="2026-08-16T00:00:00Z")
    assert repo.one("SELECT result_json FROM review_action_event WHERE event_id='v1'")[0] == frozen
    assert repo.one("SELECT count(*) FROM review_action_event")[0] == 2
    repo.close()


def test_method_change_and_cross_workspace_cannot_be_comparable(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "first.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    monkeypatch.setattr("healthzip.analytics.body_metrics.VERSION", "changed-statistical-definition")
    review = followup(repo, identity, cutoff_time=STOP)["review"]
    assert review["primary_observations"][0]["difference"] is None
    assert not review["primary_observations"][0]["method_matches"]
    other = Repository(tmp_path / "second.sqlite")
    with pytest.raises(ValueError, match="当前工作区不存在"):
        followup(other, identity, cutoff_time=STOP)
    row = dict(repo.one("SELECT * FROM review_action WHERE action_id=?", (identity,)))
    other.conn.execute("INSERT INTO review_action(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
    other.conn.commit()
    with pytest.raises(ValueError, match="不属于当前工作区"):
        followup(other, identity, cutoff_time=STOP)
    repo.close()
    other.close()


def test_training_baseline_and_followup_use_all_fixed_comparable_groups(tmp_path):
    repo = Repository(tmp_path / "training.sqlite")
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic rack", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
        "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
        "rom_protocol": "synthetic-full", "settings": {}, "settings_confirmed": True}
    for day, reps, rir in [(1, 8, None), (2, 9, 0), (3, 12, 1), (10, 10, None), (11, 11, 0), (12, 10, 1)]:
        at = datetime.fromisoformat(f"2026-08-{day:02d}T14:00:00Z")
        recorded = (at + timedelta(hours=1)).isoformat()
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else recorded):
            session = service.start_session("合成实际训练", started_at=at.isoformat())
            instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            service.add_set(instance["id"], actual={"completion_state": "completed", "set_type": "work",
                "load_value": 30, "load_unit": "kg", "reps": reps, "rir": rir,
                "ended_at": (at + timedelta(minutes=5)).isoformat()})
            service.end_session(session["id"], ended_at=recorded)
    identity = choose(repo, baseline(repo), primary={"kind": "training"})
    review = followup(repo, identity, cutoff_time=STOP)["review"]
    row = review["primary_observations"][0]
    assert (row["first_value"], row["value"], row["difference"]) == (9, 10, 1)
    assert row["baseline"]["record_count"] == row["current"]["record_count"] == 3
    assert sorted(v for v in row["baseline"]["rir_values"] if v is not None) == [0, 1]
    assert None in row["baseline"]["rir_values"]
    assert all(not r.get("is_reference") for r in row["baseline"]["records"])
    repo.close()


def test_action_w4_frozen_report_exact_result_identity_and_revision(tmp_path):
    from healthzip.analytics.cache import clear
    from healthzip.workflows.period_report import create_report, load_report

    repo = Repository(tmp_path / "report.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    save_feedback(repo, identity, "partial", "合成真实执行反馈", None, event_id="first-feedback",
        actual_start="2026-08-11T09:00:00Z", recorded_at="2026-08-12T09:00:00Z")
    direct = followup(repo, identity, cutoff_time=STOP)["review"]
    questions = analyze_questions(repo, window_start=SELECTED, window_end=STOP, cutoff_time=STOP,
        timezone_name="UTC", question_ids=["W4"], period="week")
    assert questions[0]["action_reviews"] == [direct]
    first = create_report(repo, {"cutoff_time": STOP, "timezone": "UTC"},
        period="week", knowledge_root=tmp_path / "no-private-knowledge")
    frozen = next(q for q in first["questions"] if q["id"] == "W4")["action_reviews"]
    assert frozen == [direct]
    assert direct["summary"] in first["markdown"]
    assert frozen[0]["primary_observations"][0]["baseline_source_record_ids"] == direct["primary_observations"][0]["baseline_source_record_ids"]
    saved_json = repo.one("SELECT payload_json FROM joint_period_report WHERE report_id=?", (first["report_id"],))[0]
    save_feedback(repo, identity, "executed", "仅执行反馈改变，健康数据未修改", None,
                  event_id="feedback-only", recorded_at="2026-08-13T09:00:00Z")
    feedback_report = create_report(repo, {"cutoff_time": STOP, "timezone": "UTC"},
        period="week", knowledge_root=tmp_path / "no-private-knowledge")
    feedback_review = next(q for q in feedback_report["questions"] if q["id"] == "W4")["action_reviews"][0]
    assert feedback_review["execution_status"] == "executed"
    assert feedback_review["evaluation_id"] != direct["evaluation_id"]
    assert feedback_report["content_signature"] != first["content_signature"]
    assert load_report(repo, first["report_id"]) == first
    sample(repo, 4, 10, 190, available="2026-08-13T10:00:00Z")
    clear()
    changed = create_report(repo, {"cutoff_time": STOP, "timezone": "UTC"},
        period="week", knowledge_root=tmp_path / "no-private-knowledge")
    current = next(q for q in changed["questions"] if q["id"] == "W4")["action_reviews"][0]
    assert current["primary_observations"][0]["value"] == 66
    assert current["evaluation_id"] != direct["evaluation_id"]
    assert load_report(repo, first["report_id"]) == first
    assert repo.one("SELECT payload_json FROM joint_period_report WHERE report_id=?", (first["report_id"],))[0] == saved_json
    repo.close()


def test_migration_preserves_legacy_action_and_feedback_bytes(tmp_path):
    path = tmp_path / "migration.sqlite"
    repo = Repository(path)
    frozen, result = '{"original": "基线原文"}', '{"original": "反馈原文"}'
    repo.conn.execute("INSERT INTO review_action(action_id,user_id,question_id,selected_at,review_due,action_text,baseline_json,source_filter_json) VALUES(?,?,?,?,?,?,?,?)",
        ("old", "local", "W4", SELECTED, STOP, "旧行动", frozen, "[]"))
    repo.conn.execute("INSERT INTO review_action_event(event_id,action_id,recorded_at,status,notes,result_json) VALUES(?,?,?,?,?,?)",
        ("old-event", "old", STOP, "partial", "旧反馈", result))
    # Reconstruct the prior additive schema only in this synthetic database.
    repo.conn.execute("ALTER TABLE review_action DROP COLUMN definition_json")
    repo.conn.execute("ALTER TABLE review_action_event DROP COLUMN execution_json")
    repo.conn.execute("UPDATE schema_meta SET value='5' WHERE key='repository_migration_revision'")
    repo.conn.commit()
    repo.close()
    migrated = Repository(path)
    row = migrated.one("SELECT * FROM review_action")
    event = migrated.one("SELECT * FROM review_action_event")
    assert row["baseline_json"] == frozen and row["definition_json"] is None
    assert event["result_json"] == result and event["execution_json"] is None
    migrated.close()


def test_first_primary_measurement_invalidates_w4_even_if_baseline_had_none(tmp_path):
    repo = Repository(tmp_path / "first-measurement.sqlite")
    q = baseline(repo, qid="W6")
    identity = choose(repo, q)
    kwargs = dict(window_start=SELECTED, window_end=STOP, cutoff_time=STOP,
                  timezone_name="UTC", question_ids=["W4"])
    before = analyze_questions(repo, **kwargs)[0]
    assert before["action_reviews"][0]["primary_observations"] == []
    sample(repo, 1, 11, 44, metric="hrv_sdnn_ms")
    after = analyze_questions(repo, **kwargs)[0]
    assert after["fact_id"] != before["fact_id"]
    review = after["action_reviews"][0]
    assert review["action_id"] == identity
    assert review["primary_observations"][0]["current"]["record_count"] == 1
    assert review["primary_observations"][0]["first_value"] is None
    assert "后续 1 条测量" in review["summary"]
    repo.close()


def test_unknown_training_records_are_all_retained_without_false_pairing(tmp_path):
    repo = Repository(tmp_path / "unknown-training.sqlite")
    service = TrainingService(repo)
    expected = []
    for day, reps in [(1, 8), (2, 9), (10, 10), (11, 11)]:
        at = datetime.fromisoformat(f"2026-08-{day:02d}T14:00:00Z")
        recorded = (at + timedelta(hours=1)).isoformat()
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else recorded):
            session = service.start_session("合成未知条件", started_at=at.isoformat())
            instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press",
                {"load_basis": "external_total_kg", "load_basis_confirmed": True})
            actual = service.add_set(instance["id"], actual={"completion_state": "completed", "set_type": "work",
                "load_value": 30, "load_unit": "kg", "reps": reps,
                "ended_at": (at + timedelta(minutes=5)).isoformat()})
            expected.append(actual["set_uuid"])
            service.end_session(session["id"], ended_at=recorded)
    identity = choose(repo, baseline(repo), primary={"kind": "training"})
    rows = followup(repo, identity, cutoff_time=STOP)["review"]["primary_observations"]
    assert len(rows) == 4 and all(r["difference"] is None for r in rows)
    identities = {identity for r in rows for part in (r.get("baseline"), r.get("current"))
                  if part for identity in part["source_record_ids"]}
    assert identities == set(expected)
    repo.close()


def test_latest_feedback_is_ordered_by_visibility_time_not_append_order(tmp_path):
    from healthzip.workflows.actions import list_actions
    repo = Repository(tmp_path / "feedback-order.sqlite")
    populate(repo)
    identity = choose(repo, baseline(repo), primary={"kind": "metric", "metric": "resting_heart_rate_bpm"})
    save_feedback(repo, identity, "executed", "较新的实际反馈", None, event_id="newer",
                  recorded_at="2026-08-13T00:00:00Z")
    save_feedback(repo, identity, "partial", "后来补入较早反馈", None, event_id="older",
                  recorded_at="2026-08-12T00:00:00Z")
    assert list_actions(repo)[0]["status"] == "executed"
    assert followup(repo, identity, cutoff_time=STOP)["review"]["execution_status"] == "executed"
    assert followup(repo, identity, cutoff_time="2026-08-12T12:00:00Z")["review"]["execution_status"] == "partial"
    repo.close()
