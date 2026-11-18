#!/usr/bin/env python3
"""Read current public-rule permissions through a disposable SQLite backup.

All private records are synthetic. Production databases are opened mode=ro;
only the temporary copies receive schema/audit writes. No rule, claim, review,
source or release is added, and no model service configuration is copied. This
is functional evidence, not scientific review or individual effectiveness.
"""
import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from healthzip.advice import save_profile
from healthzip.db.repository import Repository
from healthzip.training.current import current_advice, knowledge_signature, save_equipment_loads
from healthzip.training.service import TrainingService

PROFILE = {"age": 33, "training_goal": "strength", "training_experience": "experienced",
           "health_scope": "healthy_adult_self_reported"}
PLAN = {"reps_min": 8, "reps_max": 12, "rir": 2}
LOADS = [50, 55, 60, 65]


def backup_knowledge(root, destination):
    destination.mkdir()
    for filename in ("sources.sqlite3", "theories.sqlite3"):
        source = sqlite3.connect((root / filename).as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(destination / filename)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()


def condition(service):
    machine = service.create_equipment("Synthetic station", "barbell")
    return {"equipment_instance_id": machine["id"], "load_basis": "external_total_kg",
        "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
        "rom_protocol": "user-full", "settings": {"position": "fixed"}, "settings_confirmed": True}


def historical_sets(service, physical, days):
    import healthzip.training.service as training

    original = training.timestamp
    clock = datetime.now(timezone.utc) - timedelta(days=days)
    with patch.object(training, "timestamp", lambda value=None: original(value) if value else clock.isoformat()):
        session = service.start_session("Synthetic ordinary multiset history")
        exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", physical)
        rows = []
        for load, reps, rir in ((55, 10, 2), (55, 9, 1), (50, 11, 2)):
            row = service.add_set(exercise["id"])
            clock += timedelta(seconds=1)
            row = service.edit_set(row["id"], {"completion_state": "in_progress", "started_at": clock.isoformat()}, base_revision=row["revision"])
            clock += timedelta(seconds=30)
            row = service.edit_set(row["id"], {"completion_state": "completed", "ended_at": clock.isoformat(),
                "load_value": load, "load_unit": "kg", "reps": reps, "rir": rir,
                "quality_status": "acceptable", "pain_flag": False, "stop_reason": "target_rir"}, base_revision=row["revision"])
            rows.append(row)
        service.end_session(session["id"])
    return session, rows


def pending(service, physical, planned):
    session = service.start_session("Synthetic current training")
    exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", physical)
    row = service.add_set(exercise["id"], planned=planned)
    save_equipment_loads(service.repo, exercise["id"], LOADS, load_unit="kg")
    return exercise, row


def rule_metadata(rule):
    result = {key: rule[key] for key in ("id", "rule_id", "rule_version", "theory_id", "version",
        "capability", "review_status", "permitted_actions", "capability_policy_version") if key in rule}
    result["evidence_spans"] = [{key: span[key] for key in ("source_id", "source_version_id", "span_id", "text_hash")
        if key in span} for span in rule.get("evidence_spans", [])]
    result["claim_refs"] = [{key: claim[key] for key in ("claim_id", "version", "claim_version", "source_id", "source_version_id")
        if key in claim} for claim in rule.get("claim_refs", [])]
    return result


def receipt(advice):
    history = advice["daily_history"]
    groups = []
    for group in advice["groups"]:
        options = []
        for item in group["options"]:
            basis = item["basis"]
            options.append({"strategy": item["strategy"], "load": item["load"], "unit": item["load_unit"],
                "reps": item["reps"], "rir": item["rir"], "status": item["metric"]["data_status"],
                "reason_codes": item["metric"]["reason_codes"],
                "candidate_applicability": item["metric"].get("candidate_applicability"),
                "basis": {key: basis[key] for key in ("source_set_id", "source_set_ids", "calculation_record_ids",
                    "other_record_uses", "scope", "target_set_uuid", "weight_origin", "repetitions_origin",
                    "rir_origin", "plan", "available_loads")},
                "rules": [rule_metadata(rule) for rule in basis["rules"]]})
        groups.append({"target_set_uuid": group["set_uuid"], "options": options})
    return {"advice_id": advice["advice_id"], "business_version": advice["version"],
        "created_at": advice["created_at"], "generation_origin": advice["generation_origin"],
        "user_choice": advice["user_choice"], "history_status": history["status"],
        "history_match_version": history["match_version"], "latest_session": history["latest_session"],
        "selection": history["selection"], "limitations": history["limitations"],
        "recorded_sets": [{key: row.get(key) for key in ("session_id", "session_exercise_id", "set_uuid",
            "set_number", "set_type", "completion_state", "load_value", "load_unit", "load_basis", "reps",
            "rir", "quality_status", "pain_flag", "stop_reason", "started_at", "ended_at", "available_at",
            "revision", "reference_set", "reference_declared_at", "reference_selection")} for row in history["records"]],
        "decision_input_record_ids": advice["daily_decisions"]["input_record_ids"], "groups": groups}


def options(result):
    return [item for group in result["groups"] for item in group["options"]]


def check(root, workspace):
    results = {}
    for name, days in (("ordinary_multiset", 2), ("five_hundred_days", 500), ("no_history", None)):
        repo = Repository(workspace / (name + ".sqlite3"))
        try:
            service = TrainingService(repo)
            physical = condition(service)
            save_profile(repo, PROFILE)
            _, records = historical_sets(service, physical, days) if days else (None, [])
            exercise, target = pending(service, physical, PLAN)
            actual = current_advice(repo, exercise["id"], knowledge_root=root)
            results[name] = receipt(actual)
            assert results[name]["decision_input_record_ids"] == [row["set_uuid"] for row in records]
            assert all(not row["reference_set"] and not row["reference_declared_at"] for row in records)
            if name == "no_history":
                assert actual["daily_history"]["status"] == "no_history"
                assert all(item["load"] is None for item in options(actual))
            if name == "five_hundred_days":
                assert actual["daily_history"]["latest_session"]["days_since"] > 499
                assert "historical_performance_is_observation_not_current_capacity" in actual["daily_history"]["limitations"]
            if name == "ordinary_multiset":
                heavier = [item for item in options(actual) if item["strategy"] == "heavier_lower_reps"]
                assert [(item["load"], item["reps"], item["rir"]) for item in heavier] == [(60, 8, 2), (60, 8, 2), (55, 8, 2)]
                assert all(item["load"] is None for item in options(actual) if item["strategy"] == "double_progression")
                frozen = repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (actual["advice_id"],))[0]
                for field, value, case in (("quality_status", "technique_limited", "later_group_quality"), ("pain_flag", True, "later_group_pain")):
                    last = service.get_set(records[-1]["id"])
                    service.edit_set(last["id"], {field: value}, base_revision=last["revision"])
                    changed = current_advice(repo, exercise["id"], knowledge_root=root)
                    results[case] = receipt(changed)
                    assert all(item["load"] is None for item in options(changed))
                    assert repo.one("SELECT payload_json FROM current_training_advice WHERE advice_id=?", (actual["advice_id"],))[0] == frozen
                    last = service.get_set(records[-1]["id"])
                    service.edit_set(last["id"], {field: "acceptable" if field == "quality_status" else False}, base_revision=last["revision"])
                target = service.get_set(target["id"])
                service.update_set_target(target["id"], {}, base_revision=target["revision"])
                unplanned = current_advice(repo, exercise["id"], knowledge_root=root)
                results["no_plan"] = receipt(unplanned)
                assert len(unplanned["daily_history"]["records"]) == 3
                assert all(item["load"] is None for item in options(unplanned))
            assert repo.one("SELECT count(*) FROM training_recommendation_feedback")[0] == 0
            assert repo.one("SELECT count(*) FROM training_recommendation")[0] == 0
        finally:
            repo.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_root, output = args.knowledge_root.resolve(), args.output.resolve()
    before = knowledge_signature(source_root)
    with tempfile.TemporaryDirectory(prefix="healthzip-daily-public-rule-check-") as temporary:
        workspace = Path(temporary)
        root = workspace / "knowledge-copy"
        backup_knowledge(source_root, root)
        copy_before = knowledge_signature(root)
        previous = Path.cwd()
        try:
            os.chdir(workspace)
            (workspace / ".local").mkdir()
            (workspace / ".local/knowledge").symlink_to(root, target_is_directory=True)
            cases = check(root, workspace)
        finally:
            os.chdir(previous)
        copy_after = knowledge_signature(root)
    after = knowledge_signature(source_root)
    assert before == after == copy_before == copy_after
    result = {"identity": "actual_existing_public_rules_with_isolated_synthetic_private_records",
        "created_at": datetime.now(timezone.utc).isoformat(), "production_open_mode": "ro",
        "production_dependencies_unchanged": True, "knowledge_dependency_sha256": before,
        "production_claim_rule_release_modified": False, "model_service_configuration_copied": False,
        "raw_public_directories_copied": False, "synthetic_profile": PROFILE, "user_plan": PLAN,
        "confirmed_equipment_loads_kg": LOADS, "cases": cases,
        "limits": ["Functional verification only; no new source review, expert validation or scientific Gold.",
            "Numbers are separate optional target-set trials, not an entire-session prescription or current capability estimate.",
            "Missing plan or applicable rules prevents dependent numbers; ordinary facts and recording remain available.",
            "No private production health database, user PDF, source text, model response or secret is read into this receipt."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": list(cases), "production_dependencies_unchanged": True, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
