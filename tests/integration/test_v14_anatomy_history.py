"""Synthetic review records exercise the real persistence and analysis path."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.training.exchange import export_training, import_training
from healthzip.training.offline import apply_event_batch, browser_bootstrap
from healthzip.training.semantics import TrainingError
from healthzip.training.service import TrainingService

EXERCISE = "psa.ex.barbell_bench_press"


def mapping(version="1", muscle="synthetic_chest"):
    return {
        "mapping_id": "isolated.synthetic.anatomy",
        "version": version,
        "exercise_id": EXERCISE,
        "definition_version": 1,
        "review_status": "approved",
        "reviewer": "isolated_software_fixture",
        "reviewer_kind": "synthetic_test_only",
        "reviewed_at": (datetime.now(timezone.utc) - timedelta(days=1))
        .replace(microsecond=0)
        .isoformat(),
        "evidence_refs": [{"source_id": "synthetic_only", "locator": "synthetic paragraph 1"}],
        "direct": [muscle],
        "indirect": ["synthetic_triceps"],
    }


def record(svc, review=None):
    equipment = svc.list_equipment()
    machine = (
        equipment[0] if equipment else svc.create_equipment("Synthetic anatomy bar", "barbell")
    )
    condition = {
        "equipment_instance_id": machine["id"],
        "load_basis": "external_total_kg",
        "load_basis_confirmed": True,
        "settings_confirmed": True,
        "side": "both",
        "repetition_semantics": "simultaneous",
        "rom_protocol": "synthetic_full",
        "settings": {"grip": "synthetic_standard"},
    }
    session = svc.start_session("Synthetic anatomy version")
    instance = svc.add_exercise(
        session["id"],
        EXERCISE,
        condition,
        reviewed_anatomy_snapshot=review,
    )
    row = svc.add_set(
        instance["id"],
        {"completion_state": "completed", "reps": 8, "load_value": 20, "load_unit": "kg"},
    )
    return session, instance, row


def test_str05_06_real_history_keeps_mapping_versions_and_unknown_legacy(tmp_path):
    repo = Repository(tmp_path / "source.sqlite3")
    try:
        svc = TrainingService(repo)
        _, _, legacy = record(svc)
        review = mapping()
        first_session, first_instance, first = record(svc, review)
        original = deepcopy(first["reviewed_anatomy_snapshot"])
        cutoff = (
            datetime.fromisoformat(first["available_at"]) + timedelta(microseconds=1)
        ).isoformat()
        review["direct"].append("must_not_mutate_saved_snapshot")
        _, _, second = record(svc, mapping("2", "synthetic_new_relation"))
        assert svc.get_set(first["id"])["reviewed_anatomy_snapshot"] == original
        assert svc.get_set(legacy["id"])["reviewed_anatomy_snapshot"] is None
        assert first["condition_key"] and first["condition_key"] == second["condition_key"]
        assert first_instance["reviewed_anatomy_snapshot"]["frozen_at"] <= first["available_at"]
        for old_cutoff, expected_versions in [
            (cutoff, {"1"}),
            ((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(), {"1", "2"}),
        ]:
            output = analyze(
                repo,
                cutoff_time=old_cutoff,
                context={"muscle_mappings": {EXERCISE: mapping("99")}},
                use_cache=False,
            )
            for metric_id in ("STR-05", "STR-06"):
                metric = output["metrics"][metric_id]
                assert metric["data_status"] == "partial"
                assert {
                    x["mapping_version"] for x in metric["value"]["groups"]
                } == expected_versions
                assert len(metric["value"]["unknown_set_ids"]) == 1
                assert all(x["snapshot_sha256"] for x in metric["value"]["mapping_bindings"])
        template = svc.save_session_as_template(first_session["id"], "Synthetic retained mapping")
        adopted = svc.start_session(template_id=template["id"])
        assert adopted["exercises"][0]["reviewed_anatomy_snapshot"]["version"] == "1"
        cached_template = next(
            x for x in browser_bootstrap(repo)["templates"] if x["id"] == template["id"]
        )
        event = {
            "event_id": "synthetic-anatomy-offline-retry",
            "operation": "add_exercise",
            "arguments": {
                "session_id": adopted["id"],
                "exercise_id": EXERCISE,
                "condition": cached_template["items"][0]["condition"],
            },
        }
        first_receipt = apply_event_batch(repo, [event])["results"][0]["result"]
        repeated = apply_event_batch(repo, [event])["results"][0]["result"]
        assert first_receipt["reviewed_anatomy_snapshot"]["version"] == "1"
        assert (
            repeated["replayed"]
            and repeated["reviewed_anatomy_snapshot"] == first_receipt["reviewed_anatomy_snapshot"]
        )
        exported = export_training(
            repo, tmp_path / "history.json", session_ids=[first_session["id"]]
        )
        target = Repository(tmp_path / "target.sqlite3")
        try:
            result = import_training(target, exported)
            assert result["new"] == 1 and result["invalid"] == 0, result
            assert (
                TrainingService(target).get_set(first["set_uuid"])["reviewed_anatomy_snapshot"]
                == original
            )
            imported_rows, _ = snapshot(
                target, (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
            )
            assert (
                next(x for x in imported_rows if x.get("set_uuid") == first["set_uuid"])[
                    "reviewed_anatomy_snapshot"
                ]
                == original
            )
        finally:
            target.close()
    finally:
        repo.close()


@pytest.mark.parametrize(
    "change",
    [
        {"review_status": "pending"},
        {"evidence_refs": []},
        {"evidence_refs": [1]},
        {"definition_version": 2},
        {"exercise_id": "psa.ex.plank"},
        {"reviewed_at": "2099-01-01T00:00:00+00:00"},
        {"reviewed_at": "2020-01-01T00:00:00"},
        {"reviewer": 123},
        {"version": True},
    ],
)
def test_anatomy_binding_rejects_incomplete_review_or_wrong_scope(tmp_path, change):
    repo = Repository(tmp_path / "invalid.sqlite3")
    try:
        svc = TrainingService(repo)
        session = svc.start_session("Synthetic invalid review")
        with pytest.raises(TrainingError):
            svc.add_exercise(
                session["id"],
                EXERCISE,
                {"load_basis": "unknown"},
                reviewed_anatomy_snapshot={**mapping(), **change},
            )
        assert not svc.get_session(session["id"])["exercises"]
    finally:
        repo.close()


def test_anatomy_version_is_immutable_and_set_edits_cannot_adopt_new_review(tmp_path):
    repo = Repository(tmp_path / "immutable.sqlite3")
    try:
        svc = TrainingService(repo)
        _, _, first = record(svc, mapping())
        with pytest.raises(TrainingError, match="版本不可重写"):
            record(svc, mapping(muscle="different_relation_same_version"))
        with pytest.raises(TrainingError):
            svc.edit_set(
                first["id"],
                {"reviewed_anatomy_snapshot": mapping("2")},
                base_revision=first["revision"],
            )
        assert svc.get_set(first["id"])["reviewed_anatomy_snapshot"]["version"] == "1"
    finally:
        repo.close()


def test_import_rejects_anatomy_frozen_after_original_set_availability(tmp_path):
    source = Repository(tmp_path / "source.sqlite3")
    target = Repository(tmp_path / "target.sqlite3")
    try:
        svc = TrainingService(source)
        session, _, _ = record(svc, mapping())
        path = export_training(source, tmp_path / "tampered.json", session_ids=[session["id"]])
        bundle = json.loads(path.read_text())
        instance = bundle["sessions"][0]["exercises"][0]
        instance["sets"][0]["available_at"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(bundle))
        result = import_training(target, path)
        assert result["invalid"] and not result["new"], result
        assert target.count("strength_set") == 0
    finally:
        target.close()
        source.close()


@pytest.mark.parametrize("already_bound", [False, True])
def test_anatomy_template_request_retry_preserves_original_payload(tmp_path, already_bound):
    repo = Repository(tmp_path / "template-retry.sqlite3")
    try:
        svc = TrainingService(repo)
        review = mapping()
        if already_bound:
            _, _, row = record(svc, review)
            review = row["reviewed_anatomy_snapshot"]
        items = [
            {
                "exercise_id": EXERCISE,
                "condition": {
                    "load_basis": "unknown",
                    "reviewed_anatomy_snapshot": review,
                },
            }
        ]
        first = svc.create_template(
            "Synthetic mapping plan", items, event_id="synthetic-template-retry"
        )
        replay = svc.create_template(
            "Synthetic mapping plan", items, event_id="synthetic-template-retry"
        )
        assert replay["replayed"] and replay["id"] == first["id"]
        assert first["items"] == replay["items"]
        instance = svc.start_session(template_id=first["id"])["exercises"][0]
        assert instance["reviewed_anatomy_snapshot"]["frozen_at"]
    finally:
        repo.close()
