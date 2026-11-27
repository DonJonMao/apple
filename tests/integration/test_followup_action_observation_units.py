"""R03: real Repository observations preserve estimate support and action identity."""
import json
from contextlib import closing

import pytest

from healthzip.analytics.body_metrics import analyze_body_metric, analyze_questions
from healthzip.db.repository import Repository
from healthzip.workflows.actions import (
    followup,
    metric_outcome,
    proposed_definition,
    save_feedback,
    select_action,
)

START = "2026-09-01T00:00:00Z"
END = "2026-09-08T00:00:00Z"
SELECTED = "2026-09-10T00:00:00Z"
STOP = "2026-09-16T12:00:00Z"


def estimate(repo, identity, at, value, *, support=None, algorithm="fixture-method-1",
             published=None, available=None, definition=None, estimate_at=None):
    meta = {"protocol_id": "synthetic-walking-protocol", "algorithm_version": algorithm,
            "method": "passive_estimate"}
    if support:
        meta.update(support_start=support[0], support_end=support[1])
    if published:
        meta["published_at"] = published
    if definition:
        meta["estimate_definition"] = definition
    if estimate_at:
        meta["estimate_at"] = estimate_at
    payload = {"id": identity, "canonical_type": "six_minute_walk_m", "normalized_value": value,
               "normalized_unit": "m", "raw_value": str(value), "raw_unit": "m",
               "source_name": "Synthetic handset", "device": "Synthetic mobile", "source_version": "1",
               "start_utc": at, "end_utc": at, "record_status": "active", "metadata_json": json.dumps(meta)}
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                      "VALUES('health_sample',?,?,?,'synthetic')", (identity, available or at, json.dumps(payload)))
    repo.conn.commit()


def choose(repo):
    question = analyze_questions(repo, window_start=START, window_end=END, cutoff_time=END,
                                 timezone_name="UTC", question_ids=["W7"])[0]
    primary = {"kind": "metric", "metric": "six_minute_walk_m"}
    identity = select_action(repo, question, question["steps"][0], STOP,
                             selected_at=SELECTED, planned_start=SELECTED, primary=primary)
    return identity, question


def test_estimate_definition_and_same_day_support_are_not_daily_measurements(tmp_path):
    with closing(Repository(tmp_path / "support.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420,
                 support=("2026-08-09T00:00:00Z", "2026-09-06T00:00:00Z"))
        identity, question = choose(repo)
        definition = proposed_definition(question, question["steps"][0], STOP, selected_at=SELECTED,
            primary={"kind": "metric", "metric": "six_minute_walk_m"})
        assert definition["statistic"] == "source_estimate_points"
        estimate(repo, 2, "2026-09-16T09:00:00Z", 445,
                 support=("2026-08-20T00:00:00Z", "2026-09-16T00:00:00Z"),
                 published="2026-09-16T09:00:00Z")
        review = followup(repo, identity, cutoff_time=STOP)["review"]
        row = review["primary_observations"][0]
        assert (row["first_value"], row["value"]) == (420, 445)
        point = row["current"]["estimate_observations"][0]
        assert point["estimate_support"]["start"] == "2026-08-20T00:00:00Z"
        assert point["planned_support_relation"] == "crosses_start"
        assert point["overlaps_baseline_support"] is True
        assert point["published_at"] == "2026-09-16T09:00:00Z"
        assert row["current"]["independent_measurement_count"] is None
        assert "不能据此判断这次行动的效果" in review["summary"]
        assert "期间中位数" not in review["summary"]


APPLE_DEFINITION = {
    "document_url": "https://images.apple.com/healthcare/docs/site/Using_Apple_Watch_to_Estimate_Six_Minute_Walk_Distance.pdf",
    "document_version": "2021-05", "device_family": "Apple Watch", "device_generation": "Series 4", "os_major": 7,
}


@pytest.mark.parametrize("definition,expected_limit", [(None, None), (APPLE_DEFINITION, 500),
    ({**APPLE_DEFINITION, "os_major": 11}, None), ({**APPLE_DEFINITION, "device_family": "Other"}, None)])
def test_official_window_and_ceiling_require_explicit_matching_protocol(tmp_path, definition, expected_limit):
    with closing(Repository(tmp_path / "official.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 500, algorithm="Apple-6MWD-2021",
                 definition=definition, estimate_at="2026-09-06T00:00:00Z")
        result = analyze_body_metric(repo, "six_minute_walk_m", window_start=START,
                                    window_end=END, cutoff_time=END, timezone_name="UTC")
        point = result["value"]["streams"][0]["points"][0]
        support = point["estimate_support"]
        assert support["upper_limit_m"] == expected_limit
        assert support["start"] == ("2026-08-09T00:00:00+00:00" if expected_limit else None)
        assert support["basis"] == ("official_definition_derived_from_source_estimate_time" if expected_limit else "unknown")
        assert point["observations"][0]["published_at"] is None
        assert point["observations"][0]["available_at"]


def test_ceiling_and_actual_execution_relation_are_retained(tmp_path):
    with closing(Repository(tmp_path / "ceiling.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 500, algorithm="Apple-6MWD-2021", definition=APPLE_DEFINITION,
                 support=("2026-08-09T00:00:00Z", "2026-09-06T00:00:00Z"))
        identity, _ = choose(repo)
        estimate(repo, 2, "2026-09-16T09:00:00Z", 500, algorithm="Apple-6MWD-2021", definition=APPLE_DEFINITION,
                 support=("2026-09-10T00:00:00Z", "2026-09-14T00:00:00Z"))
        save_feedback(repo, identity, "stopped", "synthetic", None, event_id="actual",
                      actual_start="2026-09-12T00:00:00Z", actual_end="2026-09-15T00:00:00Z", recorded_at=STOP)
        review = followup(repo, identity, cutoff_time=STOP)["review"]
        point = review["primary_observations"][0]["current"]["estimate_observations"][0]
        assert point["planned_support_relation"] == "within_window"
        assert point["execution_support_relation"] == "crosses_start"
        assert point["estimate_support"]["at_reportable_limit"]
        assert "上限值相同不能判断能力没有变化" in review["summary"]
        assert review["definition"]["followup_window"]["start"] == "2026-09-10T00:00:00+00:00"


def test_old_estimate_definition_is_not_silently_reinterpreted_and_new_action_is_linked(tmp_path):
    with closing(Repository(tmp_path / "history.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420)
        identity, question = choose(repo)
        saved = repo.one("SELECT definition_json FROM review_action WHERE action_id=?", (identity,))[0]
        legacy = json.loads(saved)
        legacy["version"] = "action-outcomes-2.0"
        legacy["statistic"] = "complete_local_day_median"
        legacy["primary"].pop("observation_kind")
        old_json = json.dumps(legacy)
        repo.conn.execute("UPDATE review_action SET definition_json=? WHERE action_id=?", (old_json, identity))
        repo.conn.commit()
        old_result = {"action_id": identity, "baseline": question, "cutoff_time": SELECTED,
                      "review": {"summary": "原冻结历史口径，测试保留"}}
        save_feedback(repo, identity, "unknown", "historical", old_result, event_id="old", recorded_at=SELECTED)
        before = repo.one("SELECT result_json FROM review_action_event WHERE event_id='old'")[0]
        review = followup(repo, identity, cutoff_time=STOP)["review"]
        assert review["status"] == "legacy_observation_unit"
        assert review["primary_observations"] == []
        assert review["saved_feedback_result"] == old_result
        newer = select_action(repo, question, question["steps"][0], STOP, selected_at=SELECTED,
                              primary={"kind": "metric", "metric": "six_minute_walk_m"}, supersedes_action_id=identity)
        assert newer != identity
        new_definition = json.loads(repo.one("SELECT definition_json FROM review_action WHERE action_id=?", (newer,))[0])
        assert new_definition["supersedes_action_id"] == identity
        assert new_definition["statistic"] == "source_estimate_points"
        assert repo.one("SELECT definition_json FROM review_action WHERE action_id=?", (identity,))[0] == old_json
        assert repo.one("SELECT result_json FROM review_action_event WHERE event_id='old'")[0] == before


def test_existing_catalog_types_select_appropriate_observation_units():
    assert metric_outcome("resting_heart_rate_bpm")["statistic"] == "complete_local_day_median"
    assert metric_outcome("sleep_stage")["statistic"] == "complete_local_day_median"
    assert metric_outcome("steps")["statistic"] == "complete_local_daily_total_median"
    assert metric_outcome("high_hr_event")["statistic"] == "recorded_event_count"
    assert metric_outcome("oxygen_saturation_fraction")["statistic"] == "complete_local_day_sample_median"


def test_repeat_unknown_version_and_late_visibility_preserve_records(tmp_path):
    with closing(Repository(tmp_path / "repeats.sqlite")) as repo:
        support = ("2026-08-09T00:00:00Z", "2026-09-06T00:00:00Z")
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420, support=support)
        identity, _ = choose(repo)
        estimate(repo, 2, "2026-09-11T09:00:00Z", 420, support=support)
        estimate(repo, 3, "2026-09-12T09:00:00Z", 420, support=support)
        estimate(repo, 4, "2026-09-13T09:00:00Z", 480, algorithm="fixture-method-2")
        estimate(repo, 5, "2026-09-14T09:00:00Z", 499, available="2026-09-18T00:00:00Z")
        review = followup(repo, identity, cutoff_time=STOP)["review"]
        row = review["primary_observations"][0]
        assert row["source_record_ids"] == ["health_sample:2", "health_sample:3"]
        points = row["current"]["estimate_observations"]
        assert all(p["repeated_publication"] for p in points)
        assert all(p["planned_support_relation"] == "before_start" for p in points)
        assert all(p["published_at"] is None for p in points)
        assert row["current"]["record_count"] == 2
        assert row["current"]["distinct_known_support_windows"] == 1
        changed = next(r for r in review["primary_observations"] if "health_sample:4" in r["source_record_ids"])
        assert changed["difference"] is None
        assert changed["current"]["estimate_observations"][0]["planned_support_relation"] == "unknown"
        assert all("health_sample:5" not in r["source_record_ids"] for r in review["primary_observations"])


def test_nonoverlapping_support_is_description_not_independent_effect(tmp_path):
    with closing(Repository(tmp_path / "nonoverlap.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420,
                 support=("2026-09-01T00:00:00Z", "2026-09-06T00:00:00Z"))
        identity, _ = choose(repo)
        estimate(repo, 2, "2026-09-16T09:00:00Z", 440,
                 support=("2026-09-10T00:00:00Z", "2026-09-16T00:00:00Z"))
        row = followup(repo, identity, cutoff_time=STOP)["review"]["primary_observations"][0]
        point = row["current"]["estimate_observations"][0]
        assert point["planned_support_relation"] == "within_window"
        assert point["overlaps_baseline_support"] is False
        assert point["execution_support_relation"] == "unknown"
        assert row["difference"] == 20
        assert row["current"]["independent_measurement_count"] is None


def test_same_estimate_points_reach_detail_question_action_and_frozen_report(tmp_path):
    from healthzip.analytics.cache import clear
    from healthzip.workflows.period_report import create_report, load_report
    from healthzip.workflows.report_objects import read_question

    with closing(Repository(tmp_path / "consumers.sqlite")) as repo:
        estimate(repo, 1, "2026-09-06T09:00:00Z", 420,
                 support=("2026-08-09T00:00:00Z", "2026-09-06T00:00:00Z"))
        identity, _ = choose(repo)
        estimate(repo, 2, "2026-09-16T09:00:00Z", 445,
                 support=("2026-08-20T00:00:00Z", "2026-09-16T00:00:00Z"))
        args = dict(window_start=SELECTED, window_end=STOP, cutoff_time=STOP,
                    timezone_name="UTC", previous={"start": START, "end": END})
        detail = analyze_body_metric(repo, "six_minute_walk_m", **args)["value"]["streams"][0]
        question = analyze_questions(repo, question_ids=["W7"], **args)[0]
        row = next(r for r in question["rows"] if r.get("metric") == "six_minute_walk_m")
        review = followup(repo, identity, cutoff_time=STOP)["review"]
        outcome = review["primary_observations"][0]
        assert row["statistic_kind"] == "source_estimate_points"
        assert (row["value"], row["first_value"], row["difference"]) == (445, 420, 25)
        assert row["comparison"]["current"] == detail["current"]
        assert row["source_record_ids"] == outcome["source_record_ids"] == ["health_sample:2"]
        assert row["estimate_observations"][0]["estimate_support"] == outcome["current"]["estimate_observations"][0]["estimate_support"]
        report = create_report(repo, {"cutoff_time": STOP, "timezone": "UTC"},
                               period="week", knowledge_root=tmp_path / "public-knowledge-empty")
        saved = read_question(repo, next(q for q in report["questions"] if q["id"] == "W4"))
        assert saved["action_reviews"][0] == review
        assert review["summary"] in report["markdown"]
        before = json.dumps(saved, sort_keys=True)
        # A later visible revision of the original source record changes only
        # new evaluations; previous cutoffs and the frozen object remain intact.
        estimate(repo, 2, "2026-09-16T09:00:00Z", 460,
                 support=("2026-08-20T00:00:00Z", "2026-09-16T00:00:00Z"), available="2026-09-18T00:00:00Z")
        clear()
        assert followup(repo, identity, cutoff_time=STOP)["review"] == review
        assert followup(repo, identity, cutoff_time="2026-09-19T00:00:00Z")["review"]["primary_observations"][0]["value"] == 460
        reopened = load_report(repo, report["report_id"])
        frozen = read_question(repo, next(q for q in reopened["questions"] if q["id"] == "W4"))
        assert json.dumps(frozen, sort_keys=True) == before
        assert reopened["markdown"] == report["markdown"]
