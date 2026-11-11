"""Exercise visible advice controls with real core knowledge and synthetic training.

Copies the local public knowledge databases using SQLite backup. Never opens
the default private health database or changes production knowledge approvals.
"""
from __future__ import annotations

import json
import os
import runpy
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    helpers = runpy.run_path(str(ROOT / "tests/integration/test_review_candidate_flow.py"))
    from healthzip.advice import current_use_status
    from healthzip.analytics.v13 import analyze
    from healthzip.db.repository import Repository
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.training.service import TrainingService

    with tempfile.TemporaryDirectory(prefix="healthzip-core-ui-synthetic-") as temporary:
        workspace = Path(temporary)
        knowledge = workspace / ".local/knowledge"
        knowledge.mkdir(parents=True)
        for source in (ROOT / ".local/knowledge").glob("*.sqlite3"):
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original:
                with sqlite3.connect(knowledge / source.name) as copied:
                    original.backup(copied)
        previous = Path.cwd()
        os.chdir(workspace)
        try:
            path = workspace / "synthetic.sqlite3"
            app = helpers["open_app"](path)
            app.text_input(key="start_name").set_value("Synthetic public-evidence reference")
            app.button(key="training_start").click().run()
            app.text_input(key="session_selector_query").set_value("杠铃平板卧推").run()
            app.text_input(key="session_condition_new_machine").set_value("Synthetic bench station")
            app.button(key="session_condition_add_machine").click().run()
            repo = Repository(path)
            machine = TrainingService(repo).list_equipment()[0]["id"]
            repo.close()
            app.selectbox(key="session_condition_instance").set_value(machine)
            helpers["configure_condition"](app, "session_condition")
            next(b for b in app.button if b.label == "添加到本次训练").click().run()
            instance = helpers["current"](path)["exercises"][0]
            app.button(key="add_set_" + instance["id"]).click().run()
            helpers["finish_reference"](app, path, instance, 50, 10)
            next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
            app.text_input(key="start_name").set_value("Synthetic public-evidence trial")
            app.button(key="training_start").click().run()
            app.text_input(key="session_selector_query").set_value("杠铃平板卧推").run()
            app.selectbox(key="session_condition_instance").set_value(machine)
            helpers["configure_condition"](app, "session_condition")
            next(b for b in app.button if b.label == "添加到本次训练").click().run()
            session = helpers["current"](path)
            instance = session["exercises"][0]
            app.button(key="add_set_" + instance["id"]).click().run()
            instance = helpers["current"](path)["exercises"][0]
            sid = instance["sets"][0]["set_uuid"]
            for field, value in (("low", "6"), ("high", "8"), ("rir", "2")):
                app.text_input(key="set_" + sid + "_target_" + field).set_value(value)
            app.button(key="set_" + sid + "_target_save").click().run()
            key = instance["id"]
            app.selectbox(key="strategy_" + key).set_value("heavier_lower_reps")
            app.text_input(key="loads_" + key).set_value("50,52.5,55")
            app.button(key="candidate_" + key).click().run()
            repo = Repository(path)
            missing = TrainingService(repo).list_recommendations()[0]
            assert missing["candidate"]["proposed_change"]["load"] is None
            repo.close()
            app.text_input(key="advice_age_" + key).set_value("32")
            for field, value in (("training_goal", "strength"), ("training_experience", "experienced"),
                                 ("health_scope", "healthy_adult_self_reported")):
                app.selectbox(key="advice_profile_" + field + "_" + key).set_value(value)
            app.button(key="advice_profile_save_" + key).click().run()
            app.button(key="candidate_" + key).click().run()
            assert not app.exception and not app.error, [x.value for x in app.error]
            repo = Repository(path)
            records = TrainingService(repo).list_recommendations()
            record = next(r for r in records if r["candidate"]["proposed_change"]["load"] is not None)
            assert record["candidate"]["proposed_change"]["load"] == 52.5
            assert record["candidate"]["target_range"]["reps_min"] == 6
            rules = record["input_snapshot"]["theory_authority"]["principles"]
            assert rules and all(p.get("rule_id", "").startswith("CORE-") for p in rules)
            repo.close()
            cid = record["candidate_id"]
            app.selectbox(key="choice_" + cid).set_value("accepted")
            app.button(key="feedback_" + cid).click().run()
            actual = helpers["finish_reference"](app, path, instance, 52.5, 6)
            next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
            next(w for w in app.selectbox if w.label == "训练历史").set_value(session["id"]).run()
            app.selectbox(key="history_choice_" + cid).set_value("accepted")
            app.selectbox(key="history_execution_" + cid).set_value("executed")
            app.multiselect(key="history_actual_records_" + cid).set_value([actual])
            app.button(key="history_feedback_" + cid).click().run()
            assert not app.exception and not app.error, [x.value for x in app.error]
            repo = Repository(path)
            saved = next(r for r in TrainingService(repo).list_recommendations() if r["candidate_id"] == cid)
            assert saved["input_snapshot"] == record["input_snapshot"]
            outcome = next(x for x in analyze(repo)["metrics"]["STR-27"]["value"] if x["recommendation_id"] == cid)
            assert outcome["short_term_success"] is True
            workbench = KnowledgeWorkbench(knowledge)
            try:
                workbench.lib.update_state("S1", "withdrawn", "Synthetic lifecycle check in copied knowledge only")
            finally:
                workbench.close()
            state = current_use_status(repo, saved)
            assert state["status"] == "review_required"
            repo.close()
            output = {"data_kind": "synthetic_training_real_core_evidence",
                      "entry": "Streamlit AppTest visible controls, including profile, targets, execution and post-session feedback",
                      "private_health_database_opened": False, "production_knowledge_changed": False,
                      "missing_profile_blocked": True, "production_core_rule_ui_flow_passed": True,
                      "core_rules": [{"rule_id": p["rule_id"], "version": p["version"]} for p in rules],
                      "candidate": record["candidate"], "outcome": outcome,
                      "post_withdrawal_current_use": state["status"], "frozen_snapshot_preserved": True,
                      "independent_human_review": False, "personal_causal_efficacy_validated": False}
            (ROOT / "artifacts/v14/advice/real-core-ui.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
            print("Actual core rule UI flow, post-session feedback and copied-source withdrawal passed.")
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
