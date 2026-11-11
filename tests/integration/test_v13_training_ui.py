"""Real Streamlit widget interaction writes and reads the existing Repository."""

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def test_chest_template_smith_two_sessions_end_to_end(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "ui.sqlite3"
    monkeypatch.chdir(tmp_path)
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    app.text_input(key="template_name_None").set_value("胸部计划")
    app.text_input(key="template_selector_query").set_value("上斜史密斯").run()
    app.text_input(key="template_condition_new_machine").set_value("合成验收史密斯")
    app.button(key="template_condition_add_machine").click().run()
    repo = Repository(path)
    machine = TrainingService(repo).list_equipment()[0]["id"]
    repo.close()
    app.selectbox(key="template_condition_instance").set_value(machine)
    app.selectbox(key="template_condition_basis").set_value("plates_per_side_kg")
    app.checkbox(key="template_condition_confirmed").check()
    app.selectbox(key="template_condition_side").set_value("both")
    app.selectbox(key="template_condition_repmeaning").set_value("simultaneous")
    app.text_input(key="template_condition_rom").set_value("用户确认全幅")
    app.text_input(key="template_condition_settings").set_value("上斜30度")
    app.checkbox(key="template_condition_settings_ok").check()
    app.checkbox(key="template_condition_symmetric").check()
    app.text_input(key="template_targets_low").set_value("8")
    app.text_input(key="template_targets_high").set_value("10")
    app.text_input(key="template_targets_rir").set_value("2")
    app.button(key="template_save").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    plan = TrainingService(repo).list_templates()[0]["id"]
    repo.close()
    app.run()
    app.selectbox(key="start_template").set_value(plan)
    app.text_input(key="start_name").set_value("第一次胸部")
    app.button(key="training_start").click().run()
    assert not app.exception
    repo = Repository(path)
    svc = TrainingService(repo)
    first = svc.get_session(svc.list_sessions()[0]["id"])
    set_id = first["sets"][0]["set_uuid"]
    assert first["completed_sets"] == 0
    repo.close()
    for field, value in (("load_value", "30"), ("reps", "10"), ("rir", "2")):
        app.text_input(key=f"set_{set_id}_{field}").set_value(value).run()
        assert not app.exception and not app.error
    app.selectbox(key=f"set_{set_id}_stop").set_value("plan_target")
    app.button(key=f"set_{set_id}_completed").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    actual = TrainingService(repo).get_set(set_id)
    assert (actual["load_value"], actual["reps"], actual["rir"], actual["stop_reason"]) == (
        "30",
        10,
        2,
        "plan_target",
    )
    repo.close()
    app.text_area(key="session_feedback").set_value("合成验收：完成，无手表数据")
    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
    assert not app.exception and not app.error
    app.selectbox(key="start_template").set_value(plan)
    app.text_input(key="start_name").set_value("第二次胸部")
    app.button(key="training_start").click().run()
    assert not app.exception
    repo = Repository(path)
    svc = TrainingService(repo)
    second = svc.get_session(svc.list_sessions()[0]["id"])
    instance_id = second["exercises"][0]["id"]
    assert second["completed_sets"] == 0
    assert svc.last_values(instance_id)["suggested_actual"]["load_value"] == "30"
    repo.close()
    app.button(key="candidate_" + instance_id).click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    candidate = TrainingService(repo).list_recommendations()[0]
    assert candidate["candidate"]["proposed_change"]["load"] is None
    assert candidate["candidate"]["eligibility"]
    assert candidate["input_snapshot"]["metric_result"]["data_status"] != "ok"
    assert candidate["input_snapshot"]["source_record_ids"] == [actual["set_uuid"]]
    assert any("候选 / 缺项" in str(x.value) for x in app.markdown)
    repo.close()
    app.button(key="last_" + instance_id).click().run()
    assert not app.exception
    repo = Repository(path)
    svc = TrainingService(repo)
    second = svc.get_session(second["id"])
    copied = second["sets"][-1]
    assert copied["completion_state"] == "draft" and second["completed_sets"] == 0
    repo.close()
    set_id = copied["set_uuid"]
    app.text_input(key=f"set_{set_id}_load_value").set_value("32.5").run()
    app.text_input(key=f"set_{set_id}_reps").set_value("8").run()
    app.text_input(key=f"set_{set_id}_rir").set_value("2").run()
    app.selectbox(key=f"set_{set_id}_stop").set_value("plan_target")
    app.button(key=f"set_{set_id}_completed").click().run()
    assert not app.exception and not app.error
    assert any("两侧配重合计变化：+5 kg" in str(x.value) for x in app.markdown)
    app.text_area(key="session_feedback").set_value("合成验收：第二场完成8次")
    app.text_input(key="session_srpe").set_value("7")
    app.text_input(key="session_minutes").set_value("45")
    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    svc = TrainingService(repo)
    finished = svc.get_session(second["id"])
    assert finished["session_status"] == "completed"
    assert finished["feedback"]["notes"] == "合成验收：第二场完成8次"
    assert finished["session_rpe"] == 7 and finished["duration_seconds"] == 2700
    frozen = svc.list_recommendations()[0]
    assert frozen["input_snapshot"] == candidate["input_snapshot"] and frozen["stale"]
    from healthzip.analytics.v13 import analyze
    from healthzip.reporting.markdown_report import render_report

    weekly = analyze(repo, period="week")
    assert weekly["metrics"]["STR-01"]["value"]["completed_work_parent_sets"] == 2
    assert weekly["metrics"]["STR-01"]["n_sessions"] == 2
    facts = weekly["metrics"]["STR-02"]["value"]
    assert {r["reps"] for r in facts} == {8, 10}
    report = render_report(
        {"period_snapshots": {"week": weekly}}, {}, tmp_path / "weekly.md"
    ).read_text()
    assert "本周完整指标" in report and "STR-01" in report
    assert '"completed_work_parent_sets": 2' in report
    repo.close()


def test_training_ui_condition_target_replacement_order_and_numeric_errors(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "maintenance.sqlite3"
    repo = Repository(path)
    svc = TrainingService(repo)
    session = svc.start_session("合成条件维护")
    original = svc.add_exercise(session["id"], "psa.ex.smith_incline_press", {})
    one = svc.add_set(original["id"])
    two = svc.add_set(original["id"])
    repo.close()
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    prefix = "instance_" + original["id"]
    app.text_input(key=prefix + "_condition_rom").set_value("合成完整幅度")
    app.button(key=prefix + "_condition_save").click().run()
    assert not app.exception and not app.error
    set_prefix = "set_" + one["set_uuid"]
    app.text_input(key=set_prefix + "_target_low").set_value("6")
    app.text_input(key=set_prefix + "_target_high").set_value("8")
    app.button(key=set_prefix + "_target_save").click().run()
    assert not app.exception and not app.error
    app.text_input(key=set_prefix + "_load_value").set_value("30").run()
    app.text_input(key=set_prefix + "_reps").set_value("8").run()
    app.button(key=set_prefix + "_completed").click().run()
    assert not app.exception and not app.error
    app.text_input(key=prefix + "_condition_rom").set_value("不能覆盖已执行条件")
    app.button(key=prefix + "_condition_save").click().run()
    assert not app.exception and any("测量条件不可覆盖" in str(x.value) for x in app.error)
    app.text_input(key=prefix + "_replacement_query").set_value("上斜史密斯").run()
    app.text_input(key=prefix + "_replacement_reason").set_value("器械占用，改用未知条件")
    app.selectbox(key=prefix + "_replacement_condition_basis").set_value("unknown")
    app.button(key=prefix + "_replace").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    svc = TrainingService(repo)
    preserved = svc.get_set(one["id"])
    assert preserved["reps"] == 8 and preserved["condition"]["rom_protocol"] == "合成完整幅度"
    assert preserved["planned"]["reps_min"] == 6
    assert svc.get_set(two["id"])["completion_state"] == "skipped"
    replacement = svc.get_session_exercise(original["id"])["replaced_by_instance_id"]
    repo.close()
    app.button(key="session_up_" + replacement).click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    assert TrainingService(repo).get_session(session["id"])["exercises"][0]["id"] == replacement
    repo.close()
    app.text_input(key="timer_target").set_value("不是数字")
    next(b for b in app.button if b.label == "开始休息计时").click().run()
    assert not app.exception and app.error
    app.text_input(key="session_minutes").set_value("不是数字")
    next(b for b in app.button if b.label == "结束训练并保存反馈").click().run()
    assert not app.exception and app.error
    repo = Repository(path)
    assert TrainingService(repo).get_session(session["id"])["session_status"] == "in_progress"
    repo.close()


def test_training_ui_empty_history_import_preview_apply_and_export(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "legacy.csv"
    legacy.write_text(
        "date,exercise_name,equipment,weight,reps,weight_unit,warmup\n2026-11-01,Synthetic Bench,smith,30,10,kg,false\n"
    )
    path = tmp_path / "exchange-ui.sqlite3"
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    app.text_input(key="training_import_path").set_value(str(legacy))
    app.button(key="training_import_preview").click().run()
    assert not app.exception and not app.error
    app.button(key="training_import_apply").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    assert repo.count("strength_set") == 1
    assert repo.one("SELECT load_basis FROM strength_set")[0] == "unknown"
    row_id = repo.one("SELECT id FROM strength_set")[0]
    repo.close()
    app.text_input(key=f"legacy_{row_id}_reps").set_value("8")
    app.button(key=f"legacy_{row_id}_save").click().run()
    assert not app.exception and not app.error
    repo = Repository(path)
    row = repo.one("SELECT * FROM strength_set")
    assert row["reps"] == 8 and row["load_basis"] == "unknown" and row["completion_state"] is None
    repo.close()
    app.button(key=f"legacy_{row_id}_delete").click().run()
    assert not app.exception and not app.error
    app.button(key=f"legacy_{row_id}_restore").click().run()
    assert not app.exception and not app.error
    output = tmp_path / "export.json"
    app.text_input(key="training_export_path").set_value(str(output))
    app.button(key="training_export_all").click().run()
    assert not app.exception and not app.error and output.exists()
    from healthzip.training.exchange import preview_import

    assert preview_import(output)["legacy_unassigned_sets"] == 1
