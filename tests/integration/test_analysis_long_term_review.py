"""Long review positive paths and counterexamples over actual repositories/pages."""
import json
import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, load_run, run_workflow
from healthzip.workflows.reports import markdown, review_analysis

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_analysis_w1_flow.py")))


@pytest.mark.parametrize("change,expected", [
    ({"load_value": 35}, False), ({"rir": 3}, False),
    ({"reps": 11, "rir": 1}, False), ({"rir": 1}, True),
    ({"rir": 3, "rir_qualifier": "at_least"}, False),
])
def test_joint_components_do_not_mislabel_load_or_rir_progress(tmp_path, monkeypatch, change, expected):
    repo, svc, instance, target, ids = HELPERS["history"](tmp_path, monkeypatch, approved=False)
    row = svc.get_set(ids[-1])
    svc.edit_set(row["id"], change, base_revision=row["revision"])
    run = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"]), knowledge_root=tmp_path / "missing")
    review = run["supplements"]["long_term_review"]
    assert review["start_long_term_review"] is expected
    last = review["tasks"][0]["comparisons"][-1]
    assert last["rir_recorded"] is True
    if "load_value" in change:
        assert last["load_change"] == 5
        # Repeated low-load history cannot hide a subsequent higher-load improvement.
        assert review["series"][0]["start_long_term_review"] is True
    if change.get("rir_qualifier"):
        assert last["rir_change_bounds"] == {"lower": 1, "upper": None}
        assert last["identity"] == "recorded_joint_improvement"
    repo.close()


def add_background(repo, svc, ids):
    bid = repo.create_batch(file_sha256="synthetic-long-background", file_name="synthetic", file_size=1, xml_member_path="synthetic.xml")
    for index, identity in enumerate(ids):
        row = svc.get_set(identity)
        session = svc.get_session(row["session_id"])
        start = datetime.fromisoformat(session["started_at"])
        for kind, raw, unit, value, hours in (
            ("sleep_stage", "HKCategoryTypeIdentifierSleepAnalysis", None, "HKCategoryValueSleepAnalysisAsleep", 5 if index == 2 else 7),
            ("resting_heart_rate_bpm", "HKQuantityTypeIdentifierRestingHeartRate", "count/min", 65 if index == 2 else 60, 0),
            ("hrv_sdnn_ms", "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "ms", 30 if index == 2 else 40, 0),
        ):
            end = start - timedelta(hours=1)
            key = f"synthetic-{index}-{kind}"
            assert repo.insert_sample(bid, {"fingerprint": key, "source_record_id": key,
                "raw_type": raw, "canonical_type": kind, "raw_value": str(value), "raw_unit": unit,
                "category_value": value if kind == "sleep_stage" else None,
                "start_utc": (end-timedelta(hours=hours)).isoformat(), "end_utc": end.isoformat(),
                "source_name": "Synthetic watch", "device": "Synthetic device", "source_version": "1",
                "metadata_json": json.dumps({"protocol_id": "synthetic-fixed"}), "created_at": end.isoformat()})
            # Synthetic ingestion clock, not a new field injected into an observation.
            sample_id = repo.one("SELECT id FROM health_sample WHERE fingerprint=?", (key,))[0]
            repo.conn.execute("UPDATE source_revision SET available_at=? WHERE table_name='health_sample' AND record_id=?",
                              ((end+timedelta(minutes=1)).isoformat(), sample_id))
    repo.conn.commit()


def test_all_training_backgrounds_include_middle_changes_and_missing_branch(tmp_path, monkeypatch):
    repo, svc, instance, target, ids = HELPERS["history"](tmp_path, monkeypatch, approved=False)
    add_background(repo, svc, ids)
    run = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"]), knowledge_root=tmp_path / "missing")
    contexts = run["supplements"]["pretraining_contexts"]
    assert [ctx["reference_record_id"] for ctx in contexts] == ["strength_set:" + sid for sid in ids]
    for mid, expected in (("STATE-SLEEP-24H", 300), ("STATE-RHR", 65), ("STATE-SDNN", 30)):
        value = contexts[2]["metrics"][mid]["value"]
        assert (value["observed_minutes"] if mid == "STATE-SLEEP-24H" else next(iter(value.values()))[-1]["value"]) == expected
    factors = {h["hypothesis_id"]: h for h in run["hypotheses"]}
    assert factors["unobserved_opportunity"]["status"] == "weakened"
    assert len(factors["unobserved_opportunity"]["counterevidence"]) == 6
    for name, delta in (("sleep_state", -120), ("rhr_state", 5), ("sdnn_state", -10)):
        assert factors[name]["status"] == "conflicting"
        assert any(p["difference"] == delta for p in factors[name]["support"])
        assert factors[name]["counterevidence"]  # Stable endpoints do not hide the middle change.
        assert factors[name]["unknown"]
    assert factors["body_mass"]["status"] == "unassessable"
    assert run["nodes"][3]["branch"] == "long_term_review"
    assert run["knowledge"]["status"] == "source_unavailable"
    assert run["facts"]  # No unified evidence-insufficient fallback discards observations.
    repo.close()


def test_w4_normal_page_produces_candidate_feedback_and_shared_reports(tmp_path, monkeypatch):
    repo, svc, instance, target, ids = HELPERS["history"](tmp_path, monkeypatch)
    path = repo.path
    repo.close()
    app = HELPERS["PAGE"]["open_workflow"](path)
    app.selectbox(key="workflow_kind").select("W4").run()
    app.selectbox(key="workflow_outcome").select("STR-11").run()
    app.button(key="workflow_run").click().run(timeout=30)
    assert not app.exception and not app.error
    key = "workflow_long_" + instance["id"]
    app.selectbox(key="strategy_" + key).set_value("heavier_lower_reps")
    app.text_input(key="loads_" + key).set_value("30,34,38")
    app.button(key="candidate_" + key).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    record = TrainingService(repo).list_recommendations()[0]
    cid = record["candidate_id"]
    assert record["candidate"]["proposed_change"]["load"] == 34
    base = load_run(repo, record["input_snapshot"]["analysis_review"]["run_id"])
    assert base["nodes"][3]["branch"] == "long_term_review"
    repo.close()
    app.selectbox(key="workflow_long_choice_" + cid).set_value("declined")
    app.selectbox(key="workflow_long_execution_" + cid).set_value("not_executed")
    app.button(key="workflow_long_feedback_" + cid).click().run(timeout=30)
    assert not app.exception and not app.error
    repo = Repository(path)
    snapshot = analyze(repo)
    for period in (None, "week", "month"):
        runs = review_analysis(repo, snapshot, period=period, knowledge_root=tmp_path / "missing")
        assert runs and any(r["supplements"]["long_term_review"]["start_long_term_review"] for r in runs)
        basis = next(b for r in runs for b in r["linked_candidate_bases"] if b["candidate_id"] == cid)
        assert basis["numeric_origins"][0]["value"] == 34
        assert basis["numeric_origins"][1]["origin"] == "沿用用户已确认计划的次数下限"
        report = "\n".join(markdown(runs))
        assert "策略依据" in report and "个人记录依据" in report and "RIR" in report
        assert "not_executed" in report and "任务达成 None" in report
    repo.close()


def test_selected_new_exercise_does_not_borrow_other_task_stagnation(tmp_path, monkeypatch):
    from healthzip.workflows import load_analysis
    repo, svc, instance, target, ids = HELPERS["history"](tmp_path, monkeypatch, approved=False)
    new = svc.add_exercise(instance["session_id"], "psa.ex.goblet_squat", {})
    run = run_workflow(repo, WorkflowRequest("W1", session_id=instance["session_id"],
        session_exercise_id=new["id"]), knowledge_root=tmp_path / "missing")
    assert run["nodes"][2]["long_term_review_trigger"] is False
    assert not run["supplements"].get("strength_points")
    assert load_analysis(repo, run["run_id"])["metrics"]["STR-11"]["value"] is None
    repo.close()


def test_report_keeps_saved_selection_explicit_window_and_visibility(tmp_path, monkeypatch):
    from healthzip.workflows import load_analysis
    repo, svc, instance, target, ids = HELPERS["history"](tmp_path, monkeypatch, approved=False)
    add_background(repo, svc, ids)
    cutoff = datetime.now(timezone.utc).isoformat()
    start = (datetime.now(timezone.utc)-timedelta(days=12)).isoformat()
    first = analyze(repo, cutoff_time=cutoff, window_start=start, window_end=cutoff)
    stream_id = first["sleep_options"]["streams"][0]["stream_id"]
    # An incomplete source selection must stay incomplete in all consumers;
    # falling back to automatic source selection would silently erase the gap.
    selection = {"sleep_selection": {"stream_id": stream_id, "episodes": [], "main_episode_id": None}}
    selected = analyze(repo, cutoff_time=cutoff, window_start=start, window_end=cutoff, context=selection)
    runs = review_analysis(repo, selected, knowledge_root=tmp_path / "missing")
    run = runs[0]
    snapshot = load_analysis(repo, run["run_id"])
    assert snapshot["window_start"] == start and snapshot["window_end"] == cutoff
    assert run["request"]["mode"] == "prospective"
    assert snapshot["sleep_selection"]["accepted"] is False
    assert snapshot["metrics"]["STATE-SLEEP-24H"]["value"] is None
    repo.close()
