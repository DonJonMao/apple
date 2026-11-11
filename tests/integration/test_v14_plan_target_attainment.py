"""Original plan completion and its individual endpoints are distinct facts."""
from contextlib import closing
from datetime import datetime, timezone

import pytest

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.training.service import TrainingService


def _target(**changes):
    return {"load_value": 50, "load_unit": "kg", "load_basis": "external_total_kg",
            "reps_min": 8, "reps_max": 10, "rir": 2, **changes}


def _session(repo, targets, *, basis="external_total_kg"):
    svc = TrainingService(repo)
    template = svc.create_template("Synthetic original plan", [{
        "exercise_id": "psa.ex.barbell_bench_press",
        "condition": {"load_basis": basis, "load_basis_confirmed": True},
        "targets": {"sets": targets},
    }])
    return svc, template, svc.start_session(template_id=template["id"])


def _record(svc, row, **changes):
    now = datetime.now(timezone.utc).isoformat()
    return svc.edit_set(row["set_uuid"], {
        "completion_state": "completed", "started_at": now, "ended_at": now,
        "load_value": 50, "load_unit": "kg", "reps": 8, "rir": 2, **changes,
    }, base_revision=row["revision"])


def _metric(repo):
    cutoff = datetime.now(timezone.utc).isoformat()
    return analyze(repo, cutoff_time=cutoff, use_cache=False)["metrics"]["STR-09"]


def test_service_snapshot_separates_original_completion_and_three_target_denominators(tmp_path):
    with closing(Repository(tmp_path / "synthetic-plan-targets.sqlite3")) as repo:
        svc, _, session = _session(repo, [
            _target(load_value=45.359237), _target(),
            _target(load_unit=None, load_basis=None), {}, _target(), _target(),
        ])
        rows = session["sets"]
        _record(svc, rows[0], load_value=100, load_unit="lb")
        _record(svc, rows[1], reps=6, rir=None)
        _record(svc, rows[2], reps=9, rir=2, rir_qualifier="at_least")
        _record(svc, rows[3], reps=9)
        _record(svc, rows[4], completion_state="skipped", load_value=None, load_unit=None, reps=None, rir=None)
        extra = svc.add_set(session["exercises"][0]["id"])
        _record(svc, extra)
        result = _metric(repo)
        value = result["value"]
        assert (value["planned"], value["completed"], value["skipped"], value["unknown"], value["extra_sets"]) == (6, 4, 1, 1, 1)
        assert value["completed_fraction_of_plan"] == 4 / 6
        endpoints = value["target_attainment"]
        for name, counts in {"load": (2, 1, 2, 1), "reps": (2, 2, 1, 1), "rir": (1, 1, 3, 1)}.items():
            metric = endpoints[name]
            assert tuple(metric[k] for k in ("met_n", "not_met_n", "unknown_n", "no_target_n")) == counts
            assert metric["planned_n"] == 6 and metric["target_n"] == 5
            assert metric["known_n"] == counts[0] + counts[1]
            assert metric["fraction_of_known_targets"] == counts[0] / (counts[0] + counts[1])
            assert metric["observed_met_fraction_of_targets"] == counts[0] / 5
            assert len(metric["observations"]) == 6
        assert endpoints["load"]["observations"][0]["comparison"]["recorded_unit"] == "kg"
        assert endpoints["load"]["observations"][2]["status"] == "unknown"
        assert endpoints["rir"]["observations"][2]["status"] == "unknown"
        assert result["data_status"] == "partial"


def test_original_plan_completion_includes_warmup_while_work_counts_stay_separate(tmp_path):
    with closing(Repository(tmp_path / "synthetic-warmup-plan.sqlite3")) as repo:
        svc, _, session = _session(repo, [_target(set_type="warmup"), _target(set_type="work"),
                                        _target(set_type="warmup"), _target(set_type="work")])
        assert session["sets"][0]["set_type"] == "warmup"
        _record(svc, session["sets"][0])
        _record(svc, session["sets"][1])
        _record(svc, session["sets"][2], completion_state="skipped")
        for role in ("warmup", "work"):
            extra = svc.add_set(session["exercises"][0]["id"], {"set_type": role})
            _record(svc, extra)
        cutoff = datetime.now(timezone.utc).isoformat()
        metrics = analyze(repo, cutoff_time=cutoff, use_cache=False)["metrics"]
        value = metrics["STR-09"]["value"]
        assert value["planned"] == 4
        assert value["completed"] == 2 and value["skipped"] == 1 and value["unknown"] == 1
        assert value["completed_fraction_of_plan"] == 0.5 and value["extra_sets"] == 2
        assert all(item["met_n"] == 2 for item in value["target_attainment"].values())
        assert metrics["STR-01"]["value"]["completed_work_parent_sets"] == 2


def test_current_target_and_template_edits_do_not_replace_original_endpoint_goals(tmp_path):
    with closing(Repository(tmp_path / "synthetic-original-targets.sqlite3")) as repo:
        svc, template, session = _session(repo, [_target()])
        row = svc.update_set_target(session["sets"][0]["set_uuid"], _target(reps_min=1, reps_max=3),
                                    base_revision=session["sets"][0]["revision"])
        changed_items = [{**template["items"][0], "targets": {"sets": [_target(reps_min=1, reps_max=3)]}}]
        svc.update_template(template["id"], "Synthetic changed template", changed_items, base_revision=template["revision"])
        _record(svc, row, reps=3)
        cutoff = datetime.now(timezone.utc).isoformat()
        _, context = snapshot(repo, cutoff, include_sources=False)
        assert context["session_plans"][0]["sets"][0]["targets"]["reps_min"] == 8
        result = _metric(repo)["value"]
        assert result["completed_fraction_of_plan"] == 1
        repetitions = result["target_attainment"]["reps"]
        assert repetitions["met_n"] == 0 and repetitions["not_met_n"] == 1
        assert repetitions["observations"][0]["target"] == {"min": 8, "max": 10}


@pytest.mark.parametrize("basis,unit,target,actual,expected,direction", [
    ("assistance_setting", "kg", 40, 45, "not_met", "easier"),
    ("assistance_setting", "kg", 40, 35, "not_met", "harder"),
    ("assistance_setting", "kg", 40, 40, "met", "unchanged"),
    ("plates_per_side_kg", "kg", 30, 30, "met", "not_inferred"),
    ("per_dumbbell_kg", "kg", 30, 30, "met", "not_inferred"),
    ("machine_setting", "level", 7, 7, "met", "not_inferred"),
])
def test_load_targets_keep_entered_basis_and_assistance_direction(tmp_path, basis, unit, target, actual, expected, direction):
    with closing(Repository(tmp_path / "synthetic-load-target.sqlite3")) as repo:
        svc, _, session = _session(repo, [_target(load_value=target, load_unit=unit, load_basis=basis)], basis=basis)
        _record(svc, session["sets"][0], load_value=actual, load_unit=unit)
        observation = _metric(repo)["value"]["target_attainment"]["load"]["observations"][0]
        assert observation["status"] == expected
        assert observation["comparison"]["task_direction"] == direction


@pytest.mark.parametrize("interval,expected", [
    ({"lower": 2, "upper": 3}, "met"),
    ({"lower": 1, "upper": 3}, "unknown"),
    ({"lower": 5, "upper": None}, "not_met"),
    ({"lower": 3, "upper": None}, "unknown"),
])
def test_rir_interval_only_decides_a_target_when_logically_determined(interval, expected):
    row = {"id": "synthetic-actual", "planned_set_id": "synthetic-plan", "record_kind": "strength_set",
           "completion_state": "completed", "set_type": "work", "measurement_mode": "repetitions",
           "reps": 8, "rir_interval": interval, "event_end": "2026-11-03T08:00:00Z",
           "available_at": "2026-11-03T09:00:00Z"}
    metric = evaluate("STR-09", [row], cutoff_time="2026-11-04T00:00:00Z",
                      window_start="2026-11-01T00:00:00Z", window_end="2026-11-04T00:00:00Z",
                      context={"plan_snapshot": {"sets": [{"id": "synthetic-plan", "targets": {"rir_min": 2, "rir_max": 4}}]}})
    result = metric["value"]["target_attainment"]["rir"]
    assert result["observations"][0]["status"] == expected
    assert result["unknown_n"] == (expected == "unknown")


def test_unknown_target_fields_are_not_inferred_from_actual_values(tmp_path):
    with closing(Repository(tmp_path / "synthetic-unknown-target.sqlite3")) as repo:
        svc, _, session = _session(repo, [_target(load_unit=None, load_basis=None, reps_max=None, rir=None)])
        _record(svc, session["sets"][0])
        value = _metric(repo)["value"]["target_attainment"]
        assert value["load"]["unknown_n"] == 1 and value["load"]["known_n"] == 0
        assert value["reps"]["unknown_n"] == 1 and value["reps"]["known_n"] == 0
        assert value["rir"]["no_target_n"] == 1 and value["rir"]["target_n"] == 0
        assert all(value[name]["fraction_of_known_targets"] is None for name in ("load", "reps", "rir"))


def test_service_undated_skip_is_known_plan_nonexecution_without_a_fake_endpoint(tmp_path):
    with closing(Repository(tmp_path / "synthetic-skipped-target.sqlite3")) as repo:
        svc, _, session = _session(repo, [_target()])
        original = session["sets"][0]
        skipped = svc.edit_set(original["set_uuid"], {"completion_state": "skipped"}, base_revision=original["revision"])
        value = _metric(repo)["value"]
        assert value["skipped"] == 1 and value["unknown"] == 0
        assert all(item["not_met_n"] == 1 for item in value["target_attainment"].values())
        assert skipped["started_at"] is None and skipped["ended_at"] is None
        assert svc.get_set(original["set_uuid"])["ended_at"] is None


def test_ui_skip_retains_known_nonexecution_in_analysis(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "synthetic-ui-skip.sqlite3"
    with closing(Repository(path)) as repo:
        _, _, session = _session(repo, [_target()])
        identity = session["sets"][0]["set_uuid"]
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    ).run(timeout=30)
    app.button(key="set_" + identity + "_skipped").click().run(timeout=30)
    assert not app.exception and not app.error
    with closing(Repository(path)) as repo:
        value = _metric(repo)["value"]
        assert value["skipped"] == 1 and value["completed"] == 0
        assert value["target_attainment"]["reps"]["not_met_n"] == 1


@pytest.mark.parametrize("state,status,observed_match", [
    ("draft", "unknown", True), ("in_progress", "unknown", True),
    ("aborted", "met", True), ("skipped", "not_met", None),
])
def test_recorded_endpoint_match_does_not_imply_group_completion(tmp_path, state, status, observed_match):
    with closing(Repository(tmp_path / "synthetic-plan-state.sqlite3")) as repo:
        svc, _, session = _session(repo, [_target()])
        row = session["sets"][0]
        svc.edit_set(row["set_uuid"], {
            "completion_state": state, "load_value": 50, "load_unit": "kg", "reps": 8, "rir": 2,
        }, base_revision=row["revision"])
        result = _metric(repo)["value"]
        assert result["completed"] == 0
        observation = result["target_attainment"]["reps"]["observations"][0]
        assert observation["execution_state"] == state
        assert observation["status"] == status and observation["observed_match"] is observed_match


@pytest.mark.parametrize("variant,expected_skip,expected_state", [
    ("in_window", 1, "skipped"),
    ("plan_outside_window", 0, None),
    ("future_availability", 0, None),
    ("no_explicit_plan_session", 0, None),
    ("wrong_session", 0, None),
    ("corrected_to_draft", 0, "draft"),
    ("deleted_revision", 0, None),
    ("future_event_revision", 0, None),
    ("late_correction", 1, "skipped"),
])
def test_undated_plan_states_require_window_membership_and_latest_visible_revision(variant, expected_skip, expected_state):
    row = {"id": "synthetic-set", "source_record_id": "synthetic-set", "planned_set_id": "plan-slot",
           "session_id": "planned-session", "completion_state": "skipped", "record_kind": "strength_set",
           "available_at": "2026-11-03T09:00:00Z"}
    plan = {"session_id": "planned-session", "event_end": "2026-11-03T08:00:00Z",
            "available_at": "2026-11-03T08:01:00Z",
            "sets": [{"id": "plan-slot", "session_id": "planned-session", "targets": _target()}]}
    rows = [row]
    if variant == "plan_outside_window":
        plan["event_end"] = "2020-01-01T00:00:00Z"
    elif variant == "future_availability":
        row["available_at"] = "2027-01-01T00:00:00Z"
    elif variant == "wrong_session":
        row["session_id"] = "different-session"
    elif variant in {"corrected_to_draft", "deleted_revision", "future_event_revision", "late_correction"}:
        changes = {"corrected_to_draft": {"completion_state": "draft"},
                   "deleted_revision": {"record_status": "deleted"},
                   "future_event_revision": {"completion_state": "completed", "event_end": "2027-01-01T00:00:00Z"},
                   "late_correction": {"completion_state": "draft", "available_at": "2027-01-01T00:00:00Z"}}[variant]
        rows.append({**row, "id": "synthetic-revision", "available_at": "2026-11-03T10:00:00Z", **changes})
    context = {"plan_snapshot": {"sets": plan["sets"]}, "session_plans": [] if variant == "no_explicit_plan_session" else [plan]}
    result = evaluate("STR-09", rows, cutoff_time="2026-11-04T00:00:00Z", window_start="2026-11-01T00:00:00Z",
                      window_end="2026-11-04T00:00:00Z", context=context)
    assert result["value"]["skipped"] == expected_skip
    observation = result["value"]["target_attainment"]["reps"]["observations"][0]
    assert observation["execution_state"] == expected_state
    assert observation["status"] == ("not_met" if expected_skip else "unknown")
