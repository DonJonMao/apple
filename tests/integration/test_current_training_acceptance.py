"""Full current-training acceptance on isolated synthetic repositories."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.current import current_advice, objective_comparison, save_equipment_loads
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, load_analysis, load_run, run_workflow
from healthzip.workflows.period_report import create_report, load_report
from healthzip.workflows.reports import markdown

UI = runpy.run_path(str(Path(__file__).resolve().parents[1] / "strength_ui_harness.py"))
FLOW = runpy.run_path(str(Path(__file__).with_name("test_current_training_flow.py")))
HELP = FLOW["HELP"]
LONG = runpy.run_path(str(Path(__file__).with_name("test_analysis_long_term_review.py")))


def body(repo, *, late=False):
    now = datetime.now(timezone.utc)
    end = now-timedelta(hours=1)
    batch = repo.create_batch(file_sha256="synthetic-current-body", file_name="synthetic.xml", file_size=1, xml_member_path="synthetic.xml")
    for name, raw, unit, value, start in (
        ("sleep_stage", "HKCategoryTypeIdentifierSleepAnalysis", None, "HKCategoryValueSleepAnalysisAsleep", end-timedelta(hours=7)),
        ("resting_heart_rate_bpm", "HKQuantityTypeIdentifierRestingHeartRate", "count/min", 61, end),
        ("hrv_sdnn_ms", "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "ms", 41, end),
        ("vo2_max_ml_kg_min", "HKQuantityTypeIdentifierVO2Max", "mL/kg/min", 42, end),
    ):
        assert repo.insert_sample(batch, {"fingerprint": name, "source_record_id": name, "raw_type": raw,
            "canonical_type": name, "raw_value": str(value), "raw_unit": unit,
            "category_value": value if name == "sleep_stage" else None,
            "start_utc": start.isoformat(), "end_utc": end.isoformat(), "source_name": "Synthetic watch",
            "device": "Synthetic fixed device", "source_version": "1", "created_at": end.isoformat(),
            "metadata_json": json.dumps({"protocol_id": "synthetic-fixed"})})
    repo.conn.commit()
    HELP["mass_sample"](repo, end.isoformat(), 81)
    if not late:
        from healthzip.state_log import save_state
        save_state(repo, fatigue=1, soreness=2, pain="denied", muscle="chest")
    return end.isoformat()


def plan(svc, instance):
    return svc.create_template("Synthetic chest plan", [{"exercise_id": instance["catalog_id"],
        "condition": instance["condition"], "targets": {"sets": [{"reps_min": 7, "reps_max": 13, "rir": 2}]}}])


def newest_advice(repo, identity):
    return json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE session_exercise_id=? ORDER BY created_at DESC LIMIT 1", (identity,))[0])


def test_real_template_region_free_record_next_training_and_joint_reports(tmp_path, monkeypatch):
    import streamlit as st

    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    body(repo)
    template = plan(svc, instance)
    # No selected action exists yet: viewing a region cannot invent a plan/load.
    svc.end_session(instance["session_id"])
    downloads = {}
    original_download = st.download_button

    def capture(label, data, **kwargs):
        downloads[label] = data
        return original_download(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    UI["install"](monkeypatch)
    app = HELP["open_app"](repo.path)
    app.radio(key="main_workspace").set_value("力量").run()
    UI["send"](app, "catalog", {"regions": ["chest"]})
    assert not app.exception
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
    assert template["id"] in {item["id"] for item in UI["snapshot"](app)["templates"]}
    started = UI["send"](app, "start_session", {"template_id": template["id"], "name": "Synthetic current chest"})
    assert started["status"] == "saved"
    assert not app.exception and not app.error
    session = svc.get_session(started["data"]["id"])
    selected = session["exercises"][0]
    assert UI["send"](app, "advice", {"instance_id": selected["id"]})["status"] == "saved"
    before = newest_advice(repo, selected["id"])
    option = next(o for o in before["groups"][0]["options"] if o["strategy"] == "heavier_lower_reps")
    assert (option["load"], option["reps"], option["rir"]) == (34, 7, 2)
    assert before["body"]["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
    for mid, value in (("STATE-RHR", 61), ("STATE-SDNN", 41), ("BODY-MASS-DAILY", 81)):
        assert {p["value"] for points in before["body"]["metrics"][mid]["value"].values() for p in points} == {value}
    frozen_target = svc.get_set(selected["sets"][0]["id"])["planned"]
    UI["legacy"](app, "set_details", set_id=selected["sets"][0]["set_uuid"])
    HELP["HELP"]["W1"]["TRAINING"]["finish_reference"](app, repo.path, selected, 30, 11, reference=False)
    assert not app.exception and not app.error
    actual = svc.get_set(selected["sets"][0]["id"])
    assert actual["planned"] == frozen_target and actual["rir"] == 2
    compared = objective_comparison(repo, selected["id"])
    # Body windows move with their actual cutoff. Repeated page renders can
    # legitimately freeze a newer pre-start suggestion with the same records.
    # Objective linkage must select that exact latest applicable version.
    candidates = [json.loads(row[0]) for row in repo.conn.execute(
        "SELECT payload_json FROM current_training_advice WHERE session_exercise_id=?",
        (selected["id"],))]
    candidates = [version for version in candidates
        if datetime.fromisoformat(version["created_at"]) <= datetime.fromisoformat(actual["started_at"])
        and any(group["set_uuid"] == actual["set_uuid"] for group in version["groups"])]
    latest_cutoff = max(datetime.fromisoformat(version["created_at"]) for version in candidates)
    prestart = [version for version in candidates if datetime.fromisoformat(version["created_at"]) == latest_cutoff]
    assert len(prestart) == 1
    frozen = prestart[0]
    assert compared["rows"][0]["advice_id"] == frozen["advice_id"]
    assert compared["rows"][0]["frozen_group"]["original_target"] == before["groups"][0]["original_target"]
    frozen_option = next(option for option in frozen["groups"][0]["options"]
                         if option["strategy"] == "heavier_lower_reps")
    assert (frozen_option["load"], frozen_option["reps"], frozen_option["rir"]) == (34, 7, 2)
    assert frozen["body"]["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
    assert [row["set_uuid"] for row in frozen["daily_history"]["records"]] == [
        row["set_uuid"] for row in before["daily_history"]["records"]]
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?",
                              (before["advice_id"],))[0]) == before
    assert compared["rows"][0]["actual"]["reps"] == 11
    current_session = svc.get_session(session["id"])
    assert UI["send"](app, "end_session", {"session_id": current_session["id"], "base_revision": current_session["revision"]})["status"] == "saved"
    following_start = UI["send"](app, "start_session", {"template_id": template["id"]})
    assert following_start["status"] == "saved"
    next_session = svc.get_session(following_start["data"]["id"])
    assert UI["send"](app, "advice", {"instance_id": next_session["exercises"][0]["id"]})["status"] == "saved"
    next_advice = newest_advice(repo, next_session["exercises"][0]["id"])
    assert next_advice["advice_id"] != before["advice_id"]
    next_run = load_run(repo, next_advice["review_run_id"])
    # Ordinary actuals remain un-nominated; numeric-update coverage is shared
    # with test_current_training_three_repairs.
    rir = load_analysis(repo, next_run["run_id"])["metrics"]["STR-10"]
    assert "strength_set:"+actual["set_uuid"] in rir["source_record_ids"]
    app.radio(key="main_workspace").set_value("分析").run()
    for period, label in (("week", "本周"), ("month", "本月")):
        next(s for s in app.selectbox if s.label == "复盘周期").select(label)
        for selector in app.selectbox:
            try:
                selector.index
            except ValueError as exc:
                pytest.fail(f"stale selector {selector.key} / {selector.label}: {selector.value}; {selector.options}; {exc}")
        next(b for b in app.button if b.label == "生成当前周期复盘").click().run()
        assert not app.exception and not app.error
        data = json.loads(downloads["下载本周期完整结果"])
        report = data["joint_report"]
        assert report["period"] == period
        assert downloads["下载周期复核报告"] == report["markdown"]
        assert report["markdown"].strip() in [m.value.strip() for m in app.markdown]
        assert "420" in report["markdown"] and "Synthetic watch" in report["markdown"]
        assert {p["value"] for rows in report["current"]["metrics"]["STATE-SDNN"]["value"].values() for p in rows} == {41}
        joins = [ctx for identity in report["workflow_run_ids"] for ctx in load_run(repo, identity)["supplements"].get("training_session_contexts", [])]
        join = next(c for c in joins if c["session_id"] == session["id"])
        assert join["actual_records"][0]["reps"] == 11
        assert join["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
        assert any(c["rows"][0]["advice_id"] == frozen["advice_id"] for c in report["objective_comparisons"])
        assert load_report(repo, report["report_id"])["markdown"] == report["markdown"]
    app.radio(key="main_workspace").set_value("报告").run()
    for label in ("本周", "本月"):
        next(s for s in app.selectbox if s.label == "报告范围").select(label)
        next(b for b in app.button if b.label == "生成 Markdown 报告").click().run()
        assert not app.exception and not app.error
        exported = (tmp_path / "reports/latest.md").read_text()
        assert downloads["下载身体与力量联合报告"] == exported
        assert exported.strip() in [m.value.strip() for m in app.markdown]
        app.run()
        assert downloads["下载身体与力量联合报告"] == exported
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0
    repo.close()


@pytest.mark.parametrize("period,age", [("week", 8), ("month", 35)])
def test_old_report_link_keeps_current_actuals_out_of_old_snapshot(tmp_path, monkeypatch, period, age):
    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch)
    HELP["HELP"]["record"](svc, monkeypatch, instance, days=70)
    task = analyze(repo, 100)["strength_tasks"][0]
    old = run_workflow(repo, WorkflowRequest("W4", task_id=task["task_id"], period=period,
        cutoff_time=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat()))
    old_text = "\n".join(markdown([old], repo=repo))
    selected = HELP["add_current"](svc, instance)
    advice = current_advice(repo, selected["id"], window_days=14)
    assert current_advice(repo, selected["id"], source_report_id=old["run_id"], window_days=14) == advice
    assert repo.one("SELECT report_run_id FROM current_advice_report_link WHERE advice_id=?", (advice["advice_id"],))[0] == old["run_id"]
    review = load_analysis(repo, advice["review_run_id"])
    assert datetime.fromisoformat(review["window_start"]) == datetime.fromisoformat(advice["created_at"])-timedelta(days=14)
    assert review["window_end"] == advice["created_at"]
    actual = FLOW["finish"](svc, svc.get_session_exercise(selected["id"])["sets"][0])
    assert objective_comparison(repo, selected["id"])["rows"][0]["advice_id"] == advice["advice_id"]
    report = create_report(repo, analyze(repo), period=period)
    assert any(r["set_uuid"] == actual["set_uuid"] for c in report["objective_comparisons"] for r in c["rows"])
    assert "\n".join(markdown([old], repo=repo)) == old_text and load_run(repo, old["run_id"]) == old
    repo.close()


def test_recent_joint_review_uses_rir_and_body_despite_year_improvement(tmp_path, monkeypatch):
    repo, svc, instance, _, ids = FLOW["fixture"](tmp_path, monkeypatch)
    _, old = HELP["HELP"]["record"](svc, monkeypatch, instance, days=300)
    row = svc.get_set(old["set_uuid"])
    svc.edit_set(row["id"], {"reps": 8}, base_revision=row["revision"])
    LONG["add_background"](repo, svc, ids)
    advice = current_advice(repo, instance["id"], window_days=30)
    run = load_run(repo, advice["review_run_id"])
    review = run["supplements"]["long_term_review"]
    assert review["start_long_term_review"] and review["tasks"][0]["rir_used_n"] == 5
    assert len(run["supplements"]["pretraining_contexts"]) == 6
    factor = next(h for h in run["hypotheses"] if h["hypothesis_id"] == "sdnn_state")
    assert any(p["difference"] == -10 for p in factor["support"]) and factor["counterevidence"] and factor["unknown"]
    assert any(o["load"] == 34 for g in advice["groups"] for o in g["options"])
    assert old["set_uuid"] not in str(review)
    repo.close()


def test_late_body_changes_new_report_without_entering_original_advice(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    before = current_advice(repo, instance["id"])
    FLOW["finish"](svc, target)
    before_report = create_report(repo, analyze(repo), period="week")
    body(repo, late=True)
    after_report = create_report(repo, analyze(repo), period="week")
    assert before_report["current"]["metrics"]["STATE-SDNN"]["value"] is None
    assert after_report["current"]["metrics"]["STATE-SDNN"]["value"]
    joins = [c for identity in after_report["workflow_run_ids"] for c in load_run(repo, identity)["supplements"].get("training_session_contexts", [])]
    assert next(c for c in joins if c["session_id"] == instance["session_id"])["metrics"]["STATE-SDNN"]["value"] is None
    assert load_report(repo, before_report["report_id"]) == before_report
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (before["advice_id"],))[0]) == before
    repo.close()


@pytest.mark.parametrize("change", ["training", "body", "settings"])
def test_interleaved_inputs_refuse_stale_advice_and_actual_save_still_works(tmp_path, monkeypatch, change):
    import healthzip.training.current as module

    repo, svc, instance, target, ids = FLOW["fixture"](tmp_path, monkeypatch)
    original = module.run_workflow

    def interleaved(*args, **kwargs):
        run = original(*args, **kwargs)
        other = Repository(repo.path)
        service = TrainingService(other)
        if change == "training":
            row = service.get_set(ids[-1])
            service.edit_set(row["id"], {"reps": 12}, base_revision=row["revision"])
        elif change == "body":
            body(other)
        else:
            save_equipment_loads(other, instance["id"], [30, 38, 42], load_unit="kg")
        other.close()
        return run

    with monkeypatch.context() as patch:
        patch.setattr(module, "run_workflow", interleaved)
        with pytest.raises(ValueError, match="concurrent_current_advice"):
            current_advice(repo, instance["id"])
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 0
    FLOW["finish"](svc, target)
    assert svc.get_set(target["id"])["completion_state"] == "completed"
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_multiple_actions_missing_record_and_replacement_keep_identity(tmp_path, monkeypatch):
    repo, svc, a, first, _ = FLOW["fixture"](tmp_path, monkeypatch)
    b = svc.add_exercise(a["session_id"], "psa.ex.smith_squat", a["condition"])
    b_target = svc.add_set(b["id"], planned={"reps_min": 6, "reps_max": 10, "rir": 3})
    a_advice = current_advice(repo, a["id"])
    b_advice = current_advice(repo, b["id"])
    assert a_advice["task_id"] != b_advice["task_id"]
    FLOW["finish"](svc, first, load=38, reps=5)
    assert objective_comparison(repo, b["id"])["rows"][0]["status"] == "no_actual_record"
    assert objective_comparison(repo, a["id"])["rows"][0]["advice_id"] == a_advice["advice_id"]
    # A different exercise in the same session cannot inherit A's group range.
    FLOW["finish"](svc, b_target, load=30, reps=9)
    compared = objective_comparison(repo, b["id"])["rows"][0]
    assert compared["advice_id"] == b_advice["advice_id"] and compared["advice_id"] != a_advice["advice_id"]
    pending = svc.add_exercise(a["session_id"], a["catalog_id"], a["condition"])
    original_set = svc.add_set(pending["id"], planned={"reps_min": 7, "reps_max": 13, "rir": 2})
    original = current_advice(repo, pending["id"])
    replaced = svc.replace_exercise(pending["id"], "psa.ex.smith_squat", a["condition"], reason="Synthetic free choice",
        targets={"sets": [{"reps_min": 6, "reps_max": 10, "rir": 3}]}, base_revision=svc.get_session_exercise(pending["id"])["revision"])
    replacement = svc.get_session_exercise(replaced["id"])
    advice = current_advice(repo, replacement["id"])
    FLOW["finish"](svc, replacement["sets"][0], load=38, reps=8)
    assert objective_comparison(repo, replacement["id"])["rows"][0]["advice_id"] == advice["advice_id"]
    assert objective_comparison(repo, pending["id"])["rows"][0]["status"] == "no_actual_record"
    assert original_set["set_uuid"] not in {g["set_uuid"] for g in advice["groups"]}
    assert original["advice_id"] != advice["advice_id"]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_tied_advice_versions_keep_ambiguity_and_do_not_choose_closest_load(tmp_path, monkeypatch):
    import healthzip.training.current as module

    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    fixed = datetime.now(timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    with monkeypatch.context() as patch:
        patch.setattr(module, "datetime", Clock)
        first = current_advice(repo, instance["id"])
        save_equipment_loads(repo, instance["id"], [30, 38, 42], load_unit="kg")
        second = current_advice(repo, instance["id"])
    assert first["created_at"] == second["created_at"] and first["advice_id"] != second["advice_id"]
    FLOW["finish"](svc, target, load=38, reps=8)
    row = objective_comparison(repo, instance["id"])["rows"][0]
    assert row["status"] == "ambiguous" and row["advice_id"] is None
    assert set(row["possible_advice_ids"]) == {first["advice_id"], second["advice_id"]}
    assert row["frozen_group"] is None and row["reference_comparison"] == {}
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


def test_cached_advice_rechecks_equipment_changed_during_signature_read(tmp_path, monkeypatch):
    import healthzip.training.current as module

    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    original_advice = current_advice(repo, instance["id"])
    original_signature = module.knowledge_signature
    changed = False

    def interleaved(root):
        nonlocal changed
        signature = original_signature(root)
        if not changed:
            changed = True
            save_equipment_loads(repo, instance["id"], [30, 38, 42], load_unit="kg")
        return signature

    with monkeypatch.context() as patch:
        patch.setattr(module, "knowledge_signature", interleaved)
        with pytest.raises(ValueError, match="concurrent_current_advice"):
            current_advice(repo, instance["id"])
    assert repo.one("SELECT count(*) FROM current_training_advice")[0] == 1
    assert json.loads(repo.one("SELECT payload_json FROM current_training_advice")[0]) == original_advice
    renewed = current_advice(repo, instance["id"])
    assert any(o["load"] == 38 for g in renewed["groups"] for o in g["options"])
    FLOW["finish"](svc, target)
    repo.close()


def test_missing_time_rir_and_duplicate_event_preserve_unknowns(tmp_path, monkeypatch):
    repo, svc, instance, target, _ = FLOW["fixture"](tmp_path, monkeypatch)
    current_advice(repo, instance["id"])
    # The repository supports honestly undated historical actuals. They cannot
    # acquire an inferred start time just to match a suggestion.
    args = {"completion_state": "completed", "load_value": 30, "load_unit": "kg", "reps": 10}
    first = svc.edit_set(target["id"], args, base_revision=target["revision"], event_id="synthetic-repeat-save")
    repeated = svc.edit_set(target["id"], args, base_revision=target["revision"], event_id="synthetic-repeat-save")
    assert repeated["replayed"] is True
    assert first == {k: v for k, v in repeated.items() if k != "replayed"}
    comparison = objective_comparison(repo, instance["id"])
    row = comparison["rows"][0]
    assert row["status"] == "ambiguous" and row["actual"]["rir"] is None and row["actual"]["started_at"] is None
    assert len(comparison["rows"]) == 1
    assert objective_comparison(repo, instance["id"])["comparison_id"] == comparison["comparison_id"]
    assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
    repo.close()


@pytest.mark.parametrize("period", ["week", "month"])
def test_joint_report_body_values_sources_complete_days_and_new_task_page(tmp_path, monkeypatch, period):
    observations = runpy.run_path(str(Path(__file__).with_name("test_analysis_observation_flows.py")))
    repo, svc, instance, _, _ = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    measured = body(repo)
    # Preserve coverage of ordinary, unplanned records after automatic sampling
    # was introduced for explicit planned work sets.
    session = svc.start_session("Synthetic unplanned squat")
    current = svc.add_exercise(session["id"], "psa.ex.smith_squat", instance["condition"])
    svc.add_set(current["id"])
    actual = FLOW["finish"](svc, svc.get_session_exercise(current["id"])["sets"][0], load=38, reps=9)
    # Advance only this synthetic report's event clock within its calendar
    # period. Four complete input days stay four; no missing-day imputation.
    bounds = analyze(repo, period=period, timezone_name="UTC")
    start = datetime.fromisoformat(bounds["window_start"])
    cutoff = datetime.fromisoformat(bounds["window_end"])-timedelta(seconds=1)
    batch = observations["batch"](repo)
    for offset in (0, 2, 4, 5):
        day = start+timedelta(days=offset)
        for kind, amount in (("basal", 1500), ("active", 500)):
            observations["sample"](repo, batch, f"{kind}-{offset}", kind+"_energy_kcal", amount,
                day.isoformat(), (day+timedelta(days=1)).isoformat())
    repo.conn.commit()
    report = create_report(repo, analyze(repo, cutoff_time=cutoff.isoformat(), timezone_name="UTC"), period=period)
    metrics = report["current"]["metrics"]
    energy = metrics["ENERGY-DEVICE-TOTAL"]["value"][0]
    assert (energy["complete_days"], energy["device_total_kcal"], energy["valid_day_mean_kcal_day"]) == (4, 8000, 2000)
    energy_run = next(load_run(repo, identity) for identity in report["workflow_run_ids"] if load_run(repo, identity)["workflow_id"] == "W5")
    coverage = energy_run["supplements"]["energy_coverage"][0]
    assert coverage["complete_days"] == 4 and coverage["mean_kcal_per_complete_day"] == 2000
    assert coverage["window_days"] == (7 if period == "week" else (datetime.fromisoformat(bounds["window_end"])-start).days)
    assert metrics["ENERGY-IDENTIFIABILITY"]["data_status"] == "not_identifiable"
    for mid, number in (("STATE-RHR", 61), ("STATE-SDNN", 41), ("BODY-MASS-DAILY", 81)):
        points = [p for rows in metrics[mid]["value"].values() for p in rows]
        assert [p["value"] for p in points] == [number]
        assert points[0]["date"] == measured[:10]
        assert metrics[mid]["source_record_ids"]
    vo2 = report["current"]["observations"]["OBS-VO2-REPORTED"]
    assert vo2["value"]["streams"][0]["observations"][0]["value"] == 42
    task = next(t for t in report["current"]["strength_tasks"] if t["exercise_id"] == current["catalog_id"])
    assert task["input_data_hash"] and task["inventory_identity"] == "actual_records_no_reference_inferred"
    assert task["metrics"]["STR-11"]["value"] is None
    joins = [c for identity in report["workflow_run_ids"] for c in load_run(repo, identity)["supplements"].get("training_session_contexts", [])]
    join = next(c for c in joins if c["session_id"] == current["session_id"])
    assert join["actual_records"][0]["set_uuid"] == actual["set_uuid"]
    assert join["metrics"]["STATE-SLEEP-24H"]["value"]["observed_minutes"] == 420
    assert join["metrics"]["STATE-SLEEP-COVERAGE"]["value"] is not None
    for text in ("Synthetic watch", "Synthetic source", "完整日平均 2000", "缺日不填零", "42", "下一阶段", "支持", "削弱", "待核对"):
        assert text in report["markdown"]
    app = HELP["open_app"](repo.path)
    assert not app.exception
    assert any(current["exercise"]["name"] in option for s in app.selectbox if s.label == "测量任务" for option in s.options)
    repo.close()


@pytest.mark.parametrize("period", ["week", "month"])
def test_joint_report_without_current_actuals_keeps_manual_feedback_separate(tmp_path, monkeypatch, period):
    repo, svc, instance, _, ids = FLOW["fixture"](tmp_path, monkeypatch, approved=False)
    for identity in ids:
        row = svc.get_set(identity)
        svc.delete_set(row["id"], base_revision=row["revision"])
    from healthzip.workflows.calendar import completed_periods
    prior = completed_periods(datetime.now(timezone.utc).isoformat(), "UTC", period)[-1][0]
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(prior)-timedelta(days=1)).total_seconds()/86400
    HELP["HELP"]["record"](svc, monkeypatch, instance, days=age)
    old_candidate = HELP["HELP"]["freeze"](repo, svc, instance)
    svc.recommendation_feedback(old_candidate["candidate_id"], user_choice="declined", execution_state="not_executed", nonexecution_reason="user_choice")
    saved_feedback = [dict(r) for r in repo.rows("SELECT * FROM training_recommendation_feedback")]
    body(repo)
    report = create_report(repo, analyze(repo, timezone_name="UTC"), period=period)
    assert not report["objective_comparisons"]
    assert "本期尚无可建立时间对应的训练记录" in report["markdown"]
    historical = [load_run(repo, identity) for identity in report["historical_run_ids"]]
    task = next(r for r in historical if r["task_selection"])
    followup = task["supplements"]["partial_current_period"]["followup"]
    assert [r["recommendation_id"] for r in followup["STR-27"]["value"]] == [old_candidate["candidate_id"]]
    assert followup["STR-28"]["value"]["adoption_denominator"] == 1
    assert [dict(r) for r in repo.rows("SELECT * FROM training_recommendation_feedback")] == saved_feedback
    repo.close()
