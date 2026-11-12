"""Accepted ISO offsets must keep their meaning at SQLite query boundaries."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from healthzip.analytics.v13 import snapshot
from healthzip.db.repository import Repository
from healthzip.training.followup import freeze_window
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService


@pytest.fixture
def recorded_trial(tmp_path, monkeypatch):
    import healthzip.training.service as service_module

    clock = [datetime(2026, 1, 1, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(service_module, "timestamp", lambda value=None: timestamp(value) if value is not None else clock[0].isoformat())
    repo = Repository(tmp_path / "synthetic-compact-offset.sqlite3")
    service = TrainingService(repo)
    condition = {"load_basis": "external_total_kg", "load_basis_confirmed": True}
    session = service.start_session("Synthetic baseline")
    instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    baseline = service.add_set(instance["id"], {"completion_state": "completed",
        "load_value": 40, "load_unit": "kg", "reps": 6,
        "started_at": clock[0].isoformat(), "ended_at": clock[0].isoformat()})
    clock[0] = datetime(2026, 1, 2, 8, tzinfo=timezone.utc)
    session = service.start_session("Synthetic execution")
    instance = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
    draft = service.add_set(instance["id"], {})
    clock[0] += timedelta(minutes=1)
    candidate = {"candidate_id": "synthetic-offset-candidate", "target_session": session["session_uuid"],
        "action_kind": "collect_or_confirm_evidence", "proposed_change": {}, "target_range": {},
        "reason_evidence_ids": [], "eligibility": [], "uncertainty": {},
        "verification_protocol": "synthetic software test", "rule_version": "synthetic-only", "user_choice": None,
        "followup_window": freeze_window({"start": "2026-01-03T00:00:00Z", "end": "2026-01-10T00:00:00Z", "timezone": "UTC"}, declared_at=clock[0].isoformat())}
    service.record_recommendation(candidate, {"reference_set_id": baseline["set_uuid"],
        "source_record_ids": [baseline["set_uuid"]], "condition": instance["condition"],
        "session_exercise_id": instance["id"]}, cutoff_time=clock[0].isoformat(), theory_version="synthetic-not-scientific-evidence")
    clock[0] += timedelta(minutes=2)
    execution = service.edit_set(draft["id"], {"completion_state": "completed",
        "load_value": 40, "load_unit": "kg", "reps": 7,
        "started_at": (clock[0] - timedelta(minutes=1)).isoformat(), "ended_at": clock[0].isoformat()}, base_revision=draft["revision"])
    clock[0] += timedelta(minutes=1)
    service.recommendation_feedback(candidate["candidate_id"], user_choice="accepted", execution_state="executed", actual_record_ids=[execution["set_uuid"]])
    yield repo, service, baseline, execution
    repo.close()


def offset(value, hours, *, compact):
    text = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=hours))).isoformat()
    return text[:-3] + text[-2:] if compact else text


def normalized_outcomes(value):
    rows = deepcopy(value)
    for row in rows:
        followup = row.get("followup")
        if followup:
            followup["cutoff_time"] = datetime.fromisoformat(followup["cutoff_time"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    return rows


@pytest.mark.parametrize("hours", [0, 8])
def test_history_and_snapshot_accept_compact_cutoff_and_window_offsets(recorded_trial, hours):
    repo, service, baseline, execution = recorded_trial
    times = {"cutoff_time": "2026-01-05T00:00:00Z", "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-05T00:00:00Z"}
    colon = {key: offset(value, hours, compact=False) for key, value in times.items()}
    compact = {key: offset(value, hours, compact=True) for key, value in times.items()}
    expected = service.history_as_of(**colon)
    assert {row["set_uuid"] for row in expected} == {baseline["set_uuid"], execution["set_uuid"]}
    assert service.history_as_of(**compact) == expected
    before_rows, before_context = snapshot(repo, include_sources=False, **colon)
    rows, context = snapshot(repo, include_sources=False, **compact)
    assert rows == before_rows
    assert context["sessions"] == before_context["sessions"]
    assert normalized_outcomes(context["recommendation_outcomes"]) == normalized_outcomes(before_context["recommendation_outcomes"])


@pytest.mark.parametrize("hours", [0, 8])
@pytest.mark.parametrize("compact_fields", [("cutoff_time",), ("window_start", "window_end"), ("cutoff_time", "window_start", "window_end")])
@pytest.mark.parametrize("membership", ["feedback", "followup"])
def test_candidate_feedback_and_followup_queries_normalize_each_bound(recorded_trial, hours, compact_fields, membership):
    repo, service, baseline, execution = recorded_trial
    times = {"cutoff_time": "2026-01-06T00:00:00Z", **({"window_start": "2026-01-02T08:03:30Z", "window_end": "2026-01-02T08:05:00Z"}
        if membership == "feedback" else {"window_start": "2026-01-04T00:00:00Z", "window_end": "2026-01-06T00:00:00Z"})}
    colon = {key: offset(value, hours, compact=False) for key, value in times.items()}
    mixed = {key: offset(value, hours, compact=key in compact_fields) for key, value in times.items()}
    expected = service.list_recommendations(**colon)
    assert len(expected) == 1 and expected[0]["feedback"][-1]["actual_record_ids"] == [execution["set_uuid"]]
    assert service.list_recommendations(**mixed) == expected
    before_rows, before_context = snapshot(repo, include_sources=False, **colon)
    rows, context = snapshot(repo, include_sources=False, **mixed)
    assert {row["set_uuid"] for row in before_rows} == {baseline["set_uuid"], execution["set_uuid"]}
    assert rows == before_rows
    assert normalized_outcomes(context["recommendation_outcomes"]) == normalized_outcomes(before_context["recommendation_outcomes"])
