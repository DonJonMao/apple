"""Review repairs exercised through local import and Repository entry points."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zipfile import ZipFile

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.csv_importers import import_measurements_csv
from healthzip.training.service import TrainingService


def imported(repo, tmp_path, records):
    path = tmp_path / "review-synthetic.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", "<HealthData>" + "".join(records) + "</HealthData>")
    output = import_apple_zip(path, repo)
    assert output.status == "completed"
    return analyze(repo, window_days=365, timezone_name="UTC", cutoff_time=datetime.now(timezone.utc).isoformat())


def energy_record(kind, day, value):
    return (f'<Record type="HKQuantityTypeIdentifier{kind}EnergyBurned" unit="kcal" value="{value}" '
            f'sourceName="synthetic_watch" sourceVersion="1" startDate="2026-11-{day:02d} 00:00:00 +0000" '
            f'endDate="2026-11-{day+1:02d} 00:00:00 +0000"/>')


def test_r11_imported_two_day_energy_cumulative_has_kcal_unit(tmp_path):
    repo = Repository(tmp_path / "r11.sqlite3")
    output = imported(repo, tmp_path, [energy_record(kind, day, amount)
        for day in (1, 2) for kind, amount in (("Basal", 1600), ("Active", 600))])
    metric = output["metrics"]["ENERGY-DEVICE-TOTAL"]
    assert metric["unit"] == "kcal"
    assert metric["value"][0]["device_total_kcal"] == 4400
    assert metric["value"][0]["valid_day_mean_kcal_day"] == 2200
    assert metric["value"][0]["complete_days"] == 2
    assert output["metrics"]["ENERGY-BASAL"]["unit"] == output["metrics"]["ENERGY-ACTIVE"]["unit"] == "kcal"
    repo.close()


def test_r12_same_date_disjoint_intervals_and_different_devices_are_not_pooled(tmp_path):
    repo = Repository(tmp_path / "r12-intervals.sqlite3")
    basal = energy_record("Basal", 1, 1600).replace('2026-11-02 00:00:00', '2026-11-01 12:00:00')
    active = energy_record("Active", 1, 600).replace('2026-11-01 00:00:00', '2026-11-01 12:00:00')
    output = imported(repo, tmp_path, [basal, active])
    assert output["metrics"]["ENERGY-DEVICE-TOTAL"]["value"] is None
    repo.close()
    repo = Repository(tmp_path / "r12-devices.sqlite3")
    records = [energy_record(kind, 1, amount).replace('synthetic_watch', source)
        for source in ("watch_A", "watch_B") for kind, amount in (("Basal", 1600), ("Active", 600))]
    output = imported(repo, tmp_path, records)
    totals = output["metrics"]["ENERGY-DEVICE-TOTAL"]["value"]
    assert len(totals) == 2 and all(value["device_total_kcal"] == 2200 for value in totals)
    summary = output["metrics"]["REPORT-ENERGY-SUMMARY"]
    assert summary["value"]["known_complete_day_energy_sum"] is None
    assert len(summary["value"]["streams"]) == 2 and summary["data_status"] == "incompatible"
    repo.close()


def test_r12_imported_disjoint_component_days_cannot_form_total(tmp_path):
    repo = Repository(tmp_path / "r12.sqlite3")
    output = imported(repo, tmp_path, [energy_record("Basal", 1, 1600), energy_record("Active", 2, 600)])
    metric = output["metrics"]["ENERGY-DEVICE-TOTAL"]
    assert metric["value"] is None
    assert metric["data_status"] == "insufficient"
    repo.close()


def test_r13_imported_multiple_nights_require_explicit_main_episode(tmp_path):
    repo = Repository(tmp_path / "r13.sqlite3")
    rows = [f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleep" '
            f'sourceName="synthetic_watch" startDate="2026-11-{day:02d} 23:00:00 +0000" '
            f'endDate="2026-11-{day+1:02d} 06:00:00 +0000"/>' for day in (1, 2, 3)]
    output = imported(repo, tmp_path, rows)
    assert output["metrics"]["STATE-SLEEP-MAIN"]["value"] is None
    facts = output["metrics"]["REPORT-STATE-SUMMARY"]["daily_facts"]
    assert [fact["value"] for fact in facts if fact.get("series_id") == "observed_sleep_by_wake_date"] == [420, 420, 420]
    assert all(fact["metric_id"] != "STATE-SLEEP-MAIN" for fact in facts)
    repo.close()


def test_r14_real_measurement_csv_preserves_scale_source_streams(tmp_path):
    path = tmp_path / "synthetic-measurements.csv"
    path.write_text("datetime,measurement_type,value,unit,source\n"
                    "2026-11-01T08:00:00+00:00,weight,80,kg,scale_A\n"
                    "2026-11-02T08:00:00+00:00,weight,90,kg,scale_B\n")
    repo = Repository(tmp_path / "r14.sqlite3")
    assert import_measurements_csv(path, repo)["inserted"] == 2
    output = analyze(repo, window_days=365)
    trend = output["metrics"]["BODY-MASS-TREND"]
    assert len(trend["value"]) == 2
    assert all(item["kg_per_week"] is None and item["n_days"] == 1 for item in trend["value"])
    assert trend["data_status"] != "valid"
    repo.close()


def recorded_reference_sessions(repo, *, multiple_exercises=False, regular_sets=False):
    service = TrainingService(repo)
    machine = service.create_equipment("synthetic_review_bar", "barbell")
    exercises = [service.search_exercises(query)[0] for query in (["杠铃卧推", "杠铃深蹲"] if multiple_exercises else ["杠铃卧推"])]
    condition = {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg", "load_basis_confirmed": True,
                 "side": "both", "repetition_semantics": "simultaneous", "rom_protocol": "declared_full",
                 "settings": {"grip": "declared"}, "settings_confirmed": True,
                 "reference_protocol": {"protocol_id": "review_reference", "version": "1", "reference_policy_id": "first_work_set",
                    "effort_protocol": "target_rir_2", "tempo": "2-0-1", "rest_protocol": "120_seconds_before_reference"}}
    origin = datetime.now(timezone.utc) + timedelta(minutes=1)
    saved = []
    for index, reps in enumerate((8, 11, 9)):
        start = origin + timedelta(days=index)
        session = service.start_session("synthetic review", started_at=start.isoformat())
        for offset, exercise in enumerate(exercises):
            instance = service.add_exercise(session["id"], exercise["exercise_id"], condition)
            draft = service.add_set(instance["id"], {"reference_set": True, "set_number": 1})
            saved.append(service.edit_set(draft["set_uuid"], {"completion_state": "completed", "reps": reps + offset,
                "load_value": "60", "load_unit": "kg", "rir": 2, "quality_status": "acceptable", "stop_reason": "target_rir",
                "started_at": (start + timedelta(minutes=1+offset)).isoformat(),
                "ended_at": (start + timedelta(minutes=2+offset)).isoformat()}, base_revision=draft["revision"]))
            if regular_sets and index == 0:
                for position, actual_reps in ((2, 6), (3, 5)):
                    service.add_set(instance["id"], {"completion_state": "completed", "set_number": position,
                        "load_value": "60", "load_unit": "kg", "reps": actual_reps, "rir": 2, "stop_reason": "target_rir",
                        "started_at": (start+timedelta(minutes=2*position)).isoformat(),
                        "ended_at": (start+timedelta(minutes=2*position+1)).isoformat()})
        service.end_session(session["id"], ended_at=(start + timedelta(hours=1)).isoformat())
    return (origin + timedelta(days=4)).isoformat(), saved


def test_r01_default_repository_analysis_has_independent_action_tasks(tmp_path):
    repo = Repository(tmp_path / "r01.sqlite3")
    cutoff, _ = recorded_reference_sessions(repo, multiple_exercises=True)
    output = analyze(repo, cutoff_time=cutoff)
    assert len(output["strength_tasks"]) == 2
    for task in output["strength_tasks"]:
        assert task["protocol_complete"]
        assert task["metrics"]["STR-11"]["valid_n"] == 3
        assert task["metrics"]["STR-19"]["value"]["n"] == 3
        assert task["metrics"]["STR-19"]["value"]["slope_per_day"] is not None
    repo.close()


def test_r10_actual_analysis_view_registers_and_consumes_budget(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "r10-ui.sqlite3"
    repo = Repository(path)
    from healthzip.training.semantics import timestamp
    past = datetime.now(timezone.utc) - timedelta(days=5)
    class PastDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return past.astimezone(tz) if tz else past.replace(tzinfo=None)
    with patch(__name__ + ".datetime", PastDatetime), patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or past.isoformat())):
        _, rows = recorded_reference_sessions(repo)
    repo.close()
    script = ("from healthzip.db.repository import Repository\n"
              "from healthzip.analytics.v13 import analyze\n"
              "from healthzip.ui.analysis_page import render_analysis\n"
              f"repo=Repository({str(path)!r})\n"
              "render_analysis(repo, {'v13': analyze(repo)})\nrepo.close()")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    app.button(key="analysis_look_submit").click().run(timeout=30)
    assert not app.exception and not app.error
    first = app.session_state["analysis_last_look"]
    assert first["uncertainty"]["level"] == .975
    assert first["look_audit"]["data_status"] == "valid"
    app.button(key="analysis_look_submit").click().run(timeout=30)
    assert app.session_state["analysis_last_look"]["look_allocation"] == first["look_allocation"]
    app.text_input(key="analysis_look_family").set_value("another_family").run(timeout=30)
    assert not any("实际区间与登记依据" in str(item.value) for item in app.markdown)
    app.text_input(key="analysis_look_family").set_value("local_strength_monitoring").run(timeout=30)
    app.number_input(key="analysis_look_alpha").set_value(.1).run(timeout=30)
    assert not any("实际区间与登记依据" in str(item.value) for item in app.markdown)
    app.number_input(key="analysis_look_alpha").set_value(.05).run(timeout=30)
    repo = Repository(path)
    service = TrainingService(repo)
    actual = service.get_set(rows[-1]["set_uuid"])
    service.edit_set(actual["set_uuid"], {"reps": 10}, base_revision=actual["revision"])
    repo.close()
    app.run(timeout=30)
    app.button(key="analysis_look_submit").click().run(timeout=30)
    assert not app.exception and not app.error
    second = app.session_state["analysis_last_look"]
    assert second["look_allocation"]["look_number"] == 2
    assert second["uncertainty"]["level"] == 1 - .05 / 6
    assert first["look_allocation"]["data_version"] != second["look_allocation"]["data_version"]


def test_r10_explicit_same_day_cutoff_change_invalidates_display(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "r10-explicit.sqlite3"
    repo = Repository(path)
    cutoff, _ = recorded_reference_sessions(repo)
    repo.close()
    later = (datetime.fromisoformat(cutoff)+timedelta(minutes=1)).isoformat()
    script = ("import streamlit as st\nfrom healthzip.db.repository import Repository\n"
              "from healthzip.analytics.v13 import analyze\nfrom healthzip.ui.analysis_page import render_analysis\n"
              f"cutoff=st.selectbox('指定截止',{[cutoff, later]!r},key='review_explicit_cutoff')\n"
              f"repo=Repository({str(path)!r})\nrender_analysis(repo,{{'v13':analyze(repo,cutoff_time=cutoff)}})\nrepo.close()")
    app = AppTest.from_string(script).run(timeout=30)
    app.button(key="analysis_look_submit").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.session_state["analysis_look_snapshot"]["cutoff_mode"] == "explicit"
    app.selectbox(key="review_explicit_cutoff").set_value(later).run(timeout=30)
    assert app.session_state["analysis_look_snapshot"]["cutoff_time"] == later
    assert not any("实际区间与登记依据" in str(item.value) for item in app.markdown)
    app.button(key="analysis_look_submit").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.session_state["analysis_last_look"]["look_allocation"]["look_number"] == 2


def test_r01_reference_tasks_do_not_remove_regular_sets_from_session_decline(tmp_path):
    repo = Repository(tmp_path / "within-session.sqlite3")
    cutoff, rows = recorded_reference_sessions(repo, regular_sets=True)
    service = TrainingService(repo)
    first = service.get_set(rows[0]["set_uuid"])
    output = analyze(repo, cutoff_time=cutoff)
    values = [item for item in output["metrics"]["STR-15"]["value"] if item["session_id"] == first["session_id"]]
    assert len(values) == 3 and [item["delta_reps"] for item in values] == [0, -2, -3]
    repo.close()


def test_followup_repository_quality_unknown_preserves_unknown_outcome(tmp_path):
    from healthzip.science.semantics import flatten_record

    repo = Repository(tmp_path / "quality-outcome.sqlite3")
    cutoff, rows = recorded_reference_sessions(repo)
    service = TrainingService(repo)
    actual = service.get_set(rows[1]["set_uuid"])
    task_cutoff = (datetime.fromisoformat(actual["started_at"]) - timedelta(seconds=1)).isoformat()
    session = service.get_session(actual["session_id"])
    candidate = {"candidate_id": "synthetic-review-quality", "target_session": session["session_uuid"],
        "action_kind": "synthetic_frozen_task", "proposed_change": {"load": 60, "load_unit": "kg", "load_basis": "external_total_kg"},
        "target_range": {"reps_min": 11, "reps_max": 11, "rir_min": 2, "rir_max": 2},
        "reason_evidence_ids": [], "eligibility": [], "uncertainty": {}, "verification_protocol": "synthetic quality test",
        "followup_window": "specified session", "rule_version": "synthetic_test_only", "user_choice": None}
    normalized = flatten_record(actual)
    service.record_recommendation(candidate, {"condition": {"condition_key": normalized["condition_key"]},
        "session_exercise_id": actual["session_exercise_id"], "source_record_ids": [rows[0]["set_uuid"]]},
        cutoff_time=task_cutoff, theory_version="none_reviewed_synthetic_contract_test")
    actual = service.edit_set(actual["set_uuid"], {"quality_status": "unknown"}, base_revision=actual["revision"])
    service.recommendation_feedback(candidate["candidate_id"], user_choice="accepted", execution_state="executed",
        actual_record_ids=[actual["set_uuid"]], occurred_at=(datetime.fromisoformat(actual["ended_at"]) + timedelta(minutes=1)).isoformat())
    metric = analyze(repo, cutoff_time=cutoff)["metrics"]["STR-27"]
    assert metric["value"][0]["short_term_success"] is None
    service.edit_set(actual["set_uuid"], {"quality_status": "technique_limited"}, base_revision=actual["revision"])
    assert analyze(repo, cutoff_time=cutoff)["metrics"]["STR-27"]["value"][0]["short_term_success"] is False
    repo.close()
