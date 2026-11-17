#!/usr/bin/env python3
"""Actual existing knowledge permissions, synthetic training and persisted followup.

Use a disposable SQLite knowledge backup. Does not add, approve or alter any
claim/rule/release. The receipt is functional evidence, not independent science.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from healthzip.advice import candidate_basis, freeze_candidate, save_profile
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, load_analysis, run_workflow, save_context


def definitions_hash(root):
    digest = hashlib.sha256()
    with sqlite3.connect(f"file:{root / 'theories.sqlite3'}?mode=ro", uri=True) as conn:
        for table in ("source_claim", "application_rule", "core_release", "knowledge_evidence_edge"):
            digest.update(table.encode())
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                digest.update(json.dumps(row, sort_keys=True).encode())
    return digest.hexdigest()


def check(root):
    import healthzip.training.service as training
    original_stamp = training.timestamp
    with tempfile.TemporaryDirectory(prefix="healthzip-long-review-") as temporary:
        path = Path(temporary)
        (path / ".local").mkdir()
        (path / ".local/knowledge").symlink_to(root, target_is_directory=True)
        previous = Path.cwd()
        os.chdir(path)
        repo = Repository(path / "synthetic.sqlite3")
        try:
            svc = TrainingService(repo)
            batch = repo.create_batch(file_sha256="synthetic-background", file_name="synthetic", file_size=1, xml_member_path="synthetic.xml")
            machine = svc.create_equipment("Synthetic station", "barbell")
            condition = {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg",
                "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                "rom_protocol": "user-full", "settings": {"position": "fixed"}, "settings_confirmed": True,
                "reference_protocol": {"protocol_id": "synthetic-reference", "version": "1",
                    "reference_policy_id": "first-work-set", "effort_protocol": "rir-2",
                    "tempo": "controlled", "rest_protocol": "180-sec"}}
            for days, reps in zip((26, 22, 18, 14, 10, 6), (10, 10, 9, 10, 10, 10)):
                clock = datetime.now(timezone.utc) - timedelta(days=days)
                for kind, raw, unit, value, hours in (
                    ("sleep_stage", "HKCategoryTypeIdentifierSleepAnalysis", None, "HKCategoryValueSleepAnalysisAsleep", 5 if days == 18 else 7),
                    ("resting_heart_rate_bpm", "HKQuantityTypeIdentifierRestingHeartRate", "count/min", 65 if days == 18 else 60, 0),
                    ("hrv_sdnn_ms", "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "ms", 30 if days == 18 else 40, 0),
                ):
                    end = clock-timedelta(hours=1)
                    key = f"synthetic-{days}-{kind}"
                    repo.insert_sample(batch, {"fingerprint": key, "source_record_id": key,
                        "raw_type": raw, "canonical_type": kind, "raw_value": str(value), "raw_unit": unit,
                        "category_value": value if kind == "sleep_stage" else None,
                        "start_utc": (end-timedelta(hours=hours)).isoformat(), "end_utc": end.isoformat(),
                        "source_name": "Synthetic watch", "device": "Synthetic device", "source_version": "1",
                        "metadata_json": json.dumps({"protocol_id": "synthetic-fixed"}), "created_at": end.isoformat()})
                    sample_id = repo.one("SELECT id FROM health_sample WHERE fingerprint=?", (key,))[0]
                    repo.conn.execute("UPDATE source_revision SET available_at=? WHERE table_name='health_sample' AND record_id=?",
                                      ((end+timedelta(minutes=1)).isoformat(), sample_id))
                repo.conn.commit()
                with patch.object(training, "timestamp", lambda value=None: original_stamp(value) if value else clock.isoformat()):
                    session = svc.start_session("Synthetic historical training")
                    instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
                    row = svc.add_set(instance["id"], {"reference_set": True}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
                    clock += timedelta(seconds=1)
                    row = svc.edit_set(row["id"], {"completion_state": "in_progress", "started_at": clock.isoformat()}, base_revision=row["revision"])
                    clock += timedelta(seconds=30)
                    svc.edit_set(row["id"], {"completion_state": "completed", "ended_at": clock.isoformat(),
                        "load_value": 50, "load_unit": "kg", "reps": reps, "rir": 2, "pain_flag": False,
                        "quality_status": "acceptable", "stop_reason": "target_rir"}, base_revision=row["revision"])
                    svc.end_session(session["id"])
            save_profile(repo, {"age": 33, "training_goal": "strength", "training_experience": "experienced", "health_scope": "healthy_adult_self_reported"})
            declaration = save_context(repo, {"population": "healthy_adults"})
            session = svc.start_session("Synthetic next training")
            instance = svc.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            target = svc.add_set(instance["id"], {"reference_set": True}, planned={"reps_min": 8, "reps_max": 12, "rir": 2})
            request = WorkflowRequest("W1", context_id=declaration, session_id=session["id"], session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"])
            first = run_workflow(repo, request, knowledge_root=root)
            effective = svc.current_targets(instance["id"])
            trial = freeze_candidate(repo, svc, session, instance, effective, effective["sets"][0], [50, 54, 58], "heavier_lower_reps")
            assert trial["candidate"]["proposed_change"]["load"] == 54, trial["candidate"]["eligibility"]
            assert first["nodes"][3]["branch"] == "long_term_review"
            cid = trial["candidate_id"]
            svc.recommendation_feedback(cid, user_choice="accepted")
            target = svc.edit_set(target["id"], {"completion_state": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()}, base_revision=target["revision"])
            target = svc.edit_set(target["id"], {"completion_state": "completed", "ended_at": datetime.now(timezone.utc).isoformat(),
                "load_value": 54, "load_unit": "kg", "reps": 8, "rir": 2, "pain_flag": False,
                "quality_status": "acceptable", "stop_reason": "target_rir"}, base_revision=target["revision"])
            svc.end_session(session["id"])
            svc.recommendation_feedback(cid, user_choice="accepted", execution_state="executed", actual_record_ids=[target["set_uuid"]])
            final = run_workflow(repo, WorkflowRequest("W1", context_id=declaration, session_id=session["id"],
                session_exercise_id=instance["id"], selected_set_uuid=target["set_uuid"], candidate_id=cid), knowledge_root=root)
            outcomes = load_analysis(repo, final["run_id"])["metrics"]["STR-27"]["value"]
            outcome = next(row for row in outcomes if row["recommendation_id"] == cid)
            assert outcome["short_term_success"] is True
            assert TrainingService(repo).list_recommendations()[0]["input_snapshot"] == trial["input_snapshot"]
            evidence = [{"metric_id": q["metric_id"], "status": q["status"],
                "source_explanation": q.get("permissions", {}).get("source_explanation", False),
                "claims": q.get("claims", []), "spans": q.get("spans", []), "conflicts": q.get("conflicts", [])}
                for q in first["knowledge"]["queries"]]
            assert any(q["source_explanation"] for q in evidence)
            assert all(s["text_hash"] and s["kind"] for q in evidence for s in q["spans"])
            return {"identity": "actual_public_knowledge_and_synthetic_private_records_functional_integration",
                "workflow_version": first["workflow_version"], "release_id": first["knowledge"]["release_id"],
                "comparison": first["supplements"]["long_term_review"], "evidence": evidence,
                "factors": [{key: h[key] for key in ("hypothesis_id", "status", "support", "counterevidence", "unknown", "source_claim_refs")} for h in first["hypotheses"]],
                "candidate_basis": candidate_basis(trial), "adoption": outcome["adoption"],
                "execution": outcome["execution_state"], "task_met": outcome["short_term_success"],
                "historical_candidate_unchanged": True, "independent_scientific_validation": False,
                "causal_effect": None, "model_network_calls": 0}
        finally:
            repo.close()
            os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-copy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.knowledge_copy.resolve()
    before = definitions_hash(root)
    result = check(root)
    after = definitions_hash(root)
    assert before == after
    result["existing_claim_rule_release_edge_sha256"] = before
    result["production_permissions_changed"] = False
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "task_met": result["task_met"], "permissions_changed": False}))


if __name__ == "__main__":
    main()
