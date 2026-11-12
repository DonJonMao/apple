"""Frozen template presentations survive offline event replay and public export."""

import pytest

from healthzip.db.repository import Repository
from healthzip.training.offline import apply_event_batch, browser_bootstrap, recorder_html
from healthzip.training.service import TrainingService


@pytest.mark.parametrize("planned_sets", [[], [{"duration_s": 30}]])
def test_offline_template_keeps_own_snapshot_after_same_version_rename(tmp_path, planned_sets):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    svc = TrainingService(repo)
    exercise = svc.create_exercise("旧名称", "duration", "dumbbell", "per_dumbbell_kg")
    old = svc.create_template(
        "A旧模板",
        [{"exercise_id": exercise["exercise_id"], "targets": {"sets": planned_sets}}],
    )
    svc.update_exercise(exercise["exercise_id"], {"name_zh": "新名称"}, base_revision=1)
    svc.create_template(
        "B新模板",
        [{"exercise_id": exercise["exercise_id"], "targets": {"sets": planned_sets}}],
    )
    bootstrap = browser_bootstrap(repo)
    assert [x["name_zh"] for x in bootstrap["catalog_definitions"]] == ["旧名称", "新名称"]
    # A later physical definition is also available, but the offline plan uses v1.
    svc.update_exercise(exercise["exercise_id"], {"recording_mode": "distance"}, base_revision=2)
    item = old["items"][0]
    slots = [
        {
            "set_uuid": f"offline-set-{index}",
            "session_exercise_id": "offline-exercise",
            "exercise_id": exercise["exercise_id"],
            "targets": target,
        }
        for index, target in enumerate(planned_sets)
    ]
    events = [
        {
            "event_id": "start-offline",
            "operation": "start_session",
            "arguments": {
                "session_id": "offline-session",
                "template_id": old["id"],
                "template_version": old["version"],
                "populate_template": False,
                "client_plan_slots": slots,
            },
        },
        {
            "event_id": "add-offline",
            "operation": "add_exercise",
            "arguments": {
                "session_id": "offline-session",
                "session_exercise_id": "offline-exercise",
                "exercise_id": exercise["exercise_id"],
                "definition_version": 1,
                "condition": item["condition"],
                "targets": item["targets"],
                "populate_sets": False,
            },
        },
    ]
    first = apply_event_batch(repo, events)
    assert all(x["status"] == "applied" for x in first["results"])
    persisted = svc.get_session_exercise("offline-exercise")
    assert persisted["exercise"] == item["exercise_snapshot"]
    assert persisted["exercise"]["name_zh"] == "旧名称"
    assert persisted["exercise"]["definition_version"] == 1
    assert persisted["exercise"]["default_load_basis"] == "per_dumbbell_kg"
    assert persisted["condition"] == item["condition"]
    assert persisted["planned"] == item["targets"]
    repeated = apply_event_batch(repo, events)
    assert all(x["result"]["replayed"] for x in repeated["results"])
    assert len(svc.get_session("offline-session")["exercises"]) == 1
    repo.close()


@pytest.mark.parametrize("tamper", ["exercise_id", "definition_version"])
def test_offline_plan_slot_rejects_changed_definition_identity(tmp_path, tamper):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    svc = TrainingService(repo)
    exercise = svc.create_exercise("旧定义", "duration", "bodyweight", "unknown")
    template = svc.create_template(
        "冻结模板",
        [{"exercise_id": exercise["exercise_id"], "targets": {"sets": [{"duration_s": 30}]}}],
    )
    svc.update_exercise(exercise["exercise_id"], {"recording_mode": "distance"}, base_revision=1)
    target = template["items"][0]["targets"]["sets"][0]
    svc.start_session(
        template_id=template["id"], session_id="offline-session", populate_template=False,
        client_plan_slots=[{
            "exercise_id": exercise["exercise_id"], "session_exercise_id": "offline-exercise",
            "set_uuid": "planned-set", "targets": target,
        }],
    )
    arguments = {
        "session_id": "offline-session", "session_exercise_id": "offline-exercise",
        "exercise_id": exercise["exercise_id"], "definition_version": 1,
        "condition": {}, "populate_sets": False,
    }
    arguments[tamper] = "psa.ex.plank" if tamper == "exercise_id" else 2
    receipt = apply_event_batch(repo, [{
        "event_id": "changed-definition", "operation": "add_exercise", "arguments": arguments,
    }])
    assert receipt["results"][0]["status"] == "failed"
    assert "冻结模板身份或定义版本不一致" in receipt["results"][0]["error"]
    assert not svc.get_session("offline-session")["exercises"]
    repo.close()


def test_private_alias_stays_in_bootstrap_and_out_of_public_html(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    svc = TrainingService(repo)
    svc.add_alias("psa.ex.plank", "合成私人唯一别名")
    svc.create_exercise("合成私人动作", "duration", "bodyweight", "unknown")
    bootstrap = browser_bootstrap(repo)
    plank = next(x for x in bootstrap["catalog"] if x["exercise_id"] == "psa.ex.plank")
    assert plank["user_aliases"] == ["合成私人唯一别名"]
    public = recorder_html(repo).decode()
    assert "合成私人唯一别名" not in public
    assert "合成私人动作" not in public
    repo.close()
