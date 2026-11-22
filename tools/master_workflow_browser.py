"""Exercise W4/W8/E and sparse-estimate support through the real synthetic app."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile

import pyarrow as pa
from playwright.sync_api import sync_playwright
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from health_change_browser import WRAPPER  # noqa: E402
from master_science_fixture import CUTOFF, create_master_science_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def fixed_clock(value):
    class HistoricalClock(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime.fromisoformat(value)
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)
    return HistoricalClock


def prepare_fixture(db):
    """Only source records and deliberate actions are seeded; results are computed."""
    from healthzip.advice import save_profile
    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.db.repository import Repository
    from healthzip.importers.apple_xml import import_apple_zip
    from healthzip.state_log import save_state
    from healthzip.training.semantics import timestamp
    from healthzip.training.service import TrainingService
    from healthzip.workflows.actions import followup, save_feedback, select_action

    receipt = create_master_science_fixture(db)
    repo = Repository(db)
    try:
        # The older fixture has a ledger-only subjective id 1. Keep its identity
        # separate from the actual service's first newly inserted state record.
        repo.conn.execute("UPDATE source_revision SET record_id=record_id+1000000, "
                          "payload_json=json_set(payload_json,'$.id',record_id+1000000) "
                          "WHERE table_name='subjective_log'")
        repo.conn.commit()
        with patch("healthzip.state_log.datetime", fixed_clock("2026-11-20T20:30:00+08:00")):
            state_id = save_state(repo, observed_at="2026-11-20T20:30:00+08:00", pain="reported",
                                  location="合成左膝", movement_impact="合成记录：下楼时不适",
                                  fatigue=3, soreness=2, event_id="master-workflow-pain")
        root = Element("HealthData", locale="en_US")
        for kind in ("HKCategoryTypeIdentifierMenstrualFlow", "HKCategoryTypeIdentifierAbdominalCramps"):
            record = SubElement(root, "Record", type=kind, value="1", sourceName="合成长时段手表",
                                sourceVersion="fixture-2", device="合成设备 S",
                                startDate="2026-11-17T08:00:00+08:00", endDate="2026-11-17T08:00:00+08:00")
            SubElement(record, "MetadataEntry", key="protocol_id", value="固定晨间")
        with tempfile.TemporaryDirectory(prefix="hz-workflow-xml-") as temporary:
            archive = Path(temporary) / "cycle.zip"
            with ZipFile(archive, "w", ZIP_DEFLATED) as package:
                package.writestr("apple_health_export/export.xml", tostring(root, encoding="utf-8"))
            added = import_apple_zip(archive, repo, include_cycle=True)
        # Explicitly synthetic availability, as in master_science_fixture; never
        # applied to a user database or to production importer behavior.
        repo.conn.execute("UPDATE source_revision SET available_at=COALESCE(json_extract(payload_json,'$.end_utc'), "
                          "json_extract(payload_json,'$.observed_at')) WHERE temporal_provenance='locally_observed' "
                          "AND table_name IN ('health_sample','subjective_log')")
        repo.conn.commit()
        service = TrainingService(repo)
        complete_sessions = []
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else "2026-11-01T00:00:00+08:00"):
            equipment = service.create_equipment("合成固定推胸器", "machine")
            exercise = service.create_exercise("合成同条件推胸", "repetitions", "machine", "plates_per_side_kg",
                                               exercise_id="custom.master-workflow-press")
        condition = {"equipment_instance_id": equipment["id"], "load_basis": "plates_per_side_kg",
                     "load_basis_confirmed": True, "side": "bilateral", "repetition_semantics": "full_repetitions",
                     "rom_protocol": "synthetic-full", "settings": {}, "settings_confirmed": True,
                     "reference_protocol": {"protocol_id": "synthetic-workflow", "version": "1",
                        "reference_policy_id": "synthetic-first", "effort_protocol": "direct-rir",
                        "tempo": "controlled", "rest_protocol": "recorded-180s"}}
        for day, repetitions in (("2026-11-17", 10), ("2026-11-20", 12)):
            recorded = day + "T19:00:00+08:00"
            with patch("healthzip.training.service.timestamp", side_effect=lambda value=None: timestamp(value) if value else recorded):
                session = service.start_session("合成同条件执行", started_at=day + "T18:00:00+08:00")
                instance = service.add_exercise(session["id"], exercise["exercise_id"], condition)
                for index in range(2):
                    service.add_set(instance["id"], actual={"completion_state": "completed", "set_type": "work",
                        "load_value": 32.5, "load_unit": "kg", "reps": repetitions, "rir": 2,
                        "rest_recorded_s": 180, "rest_recorded_method": "manual", "quality_status": "acceptable",
                        "pain_flag": False, "started_at": f"{day}T18:{5 + index * 4:02}:00+08:00",
                        "ended_at": f"{day}T18:{6 + index * 4:02}:00+08:00"})
                service.end_session(session["id"], ended_at=day + "T18:30:00+08:00")
                complete_sessions.append(session["id"])
        with patch("healthzip.advice.datetime", fixed_clock("2026-11-01T00:00:00+08:00")):
            goal = save_profile(repo, {"age": None, "training_goal": "strength"})
        selected = "2026-11-18T00:00:00+08:00"
        baseline = analyze_questions(repo, window_start="2026-11-01T00:00:00+08:00", window_end=selected,
                                     cutoff_time=selected, timezone_name="Asia/Shanghai", question_ids=["W4"])[0]
        action_id = select_action(repo, baseline, baseline["steps"][0], "2026-11-25T12:00:00+08:00",
                                  selected_at=selected)
        result = followup(repo, action_id, cutoff_time="2026-11-21T22:00:00+08:00")
        with patch("healthzip.workflows.actions.datetime", fixed_clock("2026-11-21T22:00:00+08:00")):
            save_feedback(repo, action_id, "executed", "合成执行反馈：已沿用记录条件完成复查", result,
                          event_id="master-workflow-executed")
        return {**receipt, "extra_cycle_records": added.records_inserted, "state_id": state_id,
                "goal": goal, "action_id": action_id, "selected_at": selected,
                "complete_condition_sessions": complete_sessions,
                "baseline_observation": baseline["observation"], "baseline_rows": baseline["rows"],
                "feedback_status": "executed", "feedback_result_status": result["status"],
                "seed_methods": ["normal XML ZIP importer", "save_state", "save_profile", "analyze_questions",
                                 "select_action", "followup", "save_feedback"],
                "result_injection": False}
    finally:
        repo.close()


def run(output, *, prepare_only=False):
    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.analytics.body_questions import QUESTIONS
    from healthzip.db.repository import Repository

    output.mkdir(parents=True, exist_ok=True)
    prior = output / "browser.json"
    if prior.exists() and json.loads(prior.read_text()).get("status") == "failed":
        (output / f"browser-failed-attempt-{len(list(output.glob('browser-failed-attempt-*.json'))) + 1}.json").write_bytes(prior.read_bytes())
    result = {"data": "synthetic_only", "status": "preparing", "checks": {}, "errors": [],
              "external_model_calls": 0, "clock": CUTOFF,
              "table_evidence": "Actual Streamlit WebSocket ForwardMsg Arrow payloads received by browser",
              "unverified": ["physical phone", "Safari", "external validity", "remote private generation"]}
    with tempfile.TemporaryDirectory(prefix="hz-workflow-browser-") as temporary:
        folder = Path(temporary)
        db = folder / ".local/healthzip.sqlite3"
        result["fixture"] = prepare_fixture(db)
        if prepare_only:
            result["status"] = "fixture_prepared_not_browser_acceptance"
            (output / "fixture-preparation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
            return
        with closing(Repository(db)) as repo:
            expected = {q["id"]: q for q in analyze_questions(repo, window_start="2026-10-23T00:00:00+08:00",
                window_end=CUTOFF, cutoff_time=CUTOFF, timezone_name="Asia/Shanghai", question_ids=["W4", "W8", "E", "W7"])}
        result["computed_questions"] = expected
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (wrapper / ".streamlit").symlink_to(ROOT / ".streamlit", target_is_directory=True)
        wrapper_text = WRAPPER.format(cutoff=CUTOFF, app=str(ROOT / "app.py"))
        wrapper_text = wrapper_text.replace("runpy.run_path(",
            'importlib.import_module("healthzip.workflows.actions").datetime = FixedRequestClock\nrunpy.run_path(')
        (wrapper / "app.py").write_text(wrapper_text)
        tables = {}
        with isolated_app(wrapper, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            result["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page.on("pageerror", lambda error: result["errors"].append(str(error)))

            def on_frame(payload):
                if not isinstance(payload, bytes):
                    return
                message = ForwardMsg()
                message.ParseFromString(payload)
                if message.HasField("delta") and message.delta.HasField("new_element"):
                    element = message.delta.new_element
                    if element.HasField("dataframe"):
                        data = element.dataframe.arrow_data.data
                        if data:
                            rows = pa.ipc.open_stream(data).read_all().to_pylist()
                            tables[str(list(message.metadata.delta_path))] = rows

            page.on("websocket", lambda socket: socket.on("framereceived", on_frame))

            def text():
                assert page.get_by_test_id("stException").count() == 0, page.get_by_test_id("stException").all_text_contents()
                return page.get_by_test_id("stMain").inner_text()

            def radio(name):
                page.get_by_role("radio", name=name, exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)

            def select_question(qid):
                tables.clear()
                # Use the real searchable combobox's input; merely focusing it
                # does not guarantee that its popup remains open after a rerun.
                combo = page.get_by_role("combobox", name="想了解的问题", exact=True)
                combo.evaluate("el => el.scrollIntoView({block:'center',behavior:'instant'})")
                page.wait_for_timeout(250)
                combo.fill(QUESTIONS[qid][0])
                page.get_by_role("option", name=QUESTIONS[qid][0], exact=True).wait_for(state="visible")
                combo.press("ArrowDown")
                combo.press("Enter")
                page.get_by_role("heading", name=QUESTIONS[qid][0], exact=True).wait_for(timeout=60000)
                settle(page)

            def all_rows():
                return [row for table in tables.values() for row in table]

            def save(name, **details):
                result["checks"][name] = {"status": "passed", "rendered_text": text(),
                                           "browser_tables": dict(tables), **details}
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
                print("PASS", name, flush=True)

            def capture(name, target=None):
                dims = {}
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
                    if target is None:
                        page.get_by_test_id("stMain").evaluate("el => el.scrollTo(0, 0)")
                    else:
                        target.evaluate("el => el.scrollIntoView({block:'start'})")
                    page.wait_for_timeout(200)
                    dims[str(width)] = geometry(page)
                    assert dims[str(width)]["document"] <= dims[str(width)]["viewport"]
                    assert dims[str(width)]["main"] <= dims[str(width)]["main_client"]
                    page.screenshot(path=str(output / f"{name}-{width}.png"))
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.wait_for_timeout(250)
                settle(page)
                return dims

            try:
                page.goto(base + "/?workspace=heart")
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=60000)
                settle(page)
                radio("设置")
                radio("基础资料")
                page.get_by_role("checkbox", name="在身体中显示周期与症状", exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)
                radio("复盘")
                radio("问题分析")
                radio("近30天")
                select_question("W4")
                page.get_by_text("当前目标 · 力量表现", exact=True).wait_for(timeout=60000)
                assert "执行反馈：已执行" in text() and "合成执行反馈" in text()
                expected_reviews = expected["W4"]["action_reviews"]
                assert expected_reviews and any(o.get("value") is not None for o in expected_reviews[0]["observations"])
                shown = [r for r in all_rows() if "选择时数值" in r and "后续数值" in r]
                assert any(r.get("选择时数值") is not None and r.get("后续数值") is not None for r in shown), all_rows()
                assert any(r.get("选择时数值") == 10 and r.get("后续数值") == 12 and r.get("差值") == 2
                           for r in shown), shown
                assert any(r.get("选择时数值") == 8 and r.get("后续数值") is None
                           and "未知" in str(r.get("可比性说明")) for r in shown), shown
                with closing(Repository(db)) as repo:
                    frozen = json.loads(repo.one("SELECT baseline_json FROM review_action WHERE action_id=?",
                                                (result["fixture"]["action_id"],))[0])
                assert frozen["rows"] == result["fixture"]["baseline_rows"]
                save("W4_goal_execution_before_after", geometry=capture("W4-goal-action"))
                capture("W4-before-after", page.get_by_text("已选行动、实际执行与预设观察", exact=True))

                radio("行动复评")
                page.get_by_role("combobox", name="实际执行情况", exact=True).click()
                page.get_by_role("option", name="部分执行", exact=True).click()
                page.get_by_role("textbox", name="实际感受或未执行原因（可选）", exact=True).fill("合成浏览器更新：复查中一部分未执行")
                page.get_by_role("button", name="保存执行与复评", exact=True).click()
                page.get_by_text("执行情况和本次观察已保存", exact=False).wait_for(timeout=30000)
                radio("问题分析")
                page.get_by_text("合成浏览器更新：复查中一部分未执行", exact=False).wait_for(timeout=60000)
                page.get_by_text("执行反馈：部分执行", exact=False).wait_for(timeout=60000)
                settle(page)
                assert "执行反馈：部分执行" in text(), text()
                with closing(Repository(db)) as repo:
                    updated = json.loads(repo.one("SELECT baseline_json FROM review_action WHERE action_id=?",
                                                 (result["fixture"]["action_id"],))[0])
                assert updated == frozen
                save("W4_immediate_feedback_refresh_and_frozen_baseline", geometry=capture("W4-feedback-refresh"))

                select_question("W8")
                page.get_by_text("相关记录与日期", exact=True).click()
                settle(page)
                assert any(str(r.get("实际重量")) in {"40", "40.0"} and r.get("次数") == 8 for r in all_rows()), all_rows()
                assert any(r.get("前次次数") == 8 and r.get("本次次数") == 8 for r in all_rows()), all_rows()
                assert any(r.get("前次次数") == 10 and r.get("本次次数") == 12
                           and r.get("同条件同负荷") is True for r in all_rows()), all_rows()
                assert "2026-11-17" in text() and "2026-11-20" in text()
                assert "记录结束在训练开始之前" in text()
                save("W8_event_actual_sets_and_repeated_comparison", geometry=capture("W8-events"))
                capture("W8-actual-sets", page.get_by_text("相关记录与日期", exact=True))
                capture("W8-comparable-sets", page.get_by_text(re.compile(r"^合成同条件推胸 ·")).last)
                page.get_by_role("button", name="查看这场实际训练", exact=True).click()
                settle(page)
                component = page.frame_locator('iframe[title*="healthzip_strength_workbench"]')
                component.get_by_test_id("training-detail").wait_for(timeout=60000)
                original = component.get_by_test_id("training-detail").inner_text()
                original_values = {key: component.locator(f'[data-field="{key}"]').evaluate_all("els => els.map(el => ({value:el.value,readonly:el.readOnly,disabled:el.disabled}))")
                                   for key in ("load_value", "reps", "rir")}
                assert "合成" in original and "2026/11/17" in original, original
                assert all(row["value"] == "40" and row["readonly"] for row in original_values["load_value"])
                assert all(row["value"] == "8" and row["readonly"] for row in original_values["reps"])
                save("W8_open_original_training", original_training_text=original,
                     original_input_values=original_values, geometry=capture("W8-original-training"))

                radio("复盘")
                radio("问题分析")
                select_question("E")
                assert "合成左膝" in text() and "下楼时不适" in text(), text()
                assert "疲劳" in text() and "已记录" in text()
                page.get_by_text("相关记录与日期", exact=True).click()
                settle(page)
                assert any(str(r.get("实际重量")) in {"40", "40.0"} for r in all_rows())
                save("E_recorded_symptoms_and_training_context", geometry=capture("E-symptoms"))
                capture("E-context", page.get_by_text("相关记录与日期", exact=True))

                select_question("W7")
                page.get_by_text("相关记录与日期", exact=True).click()
                settle(page)
                support = [r for r in all_rows() if "支持起点" in r and r.get("项目") == "六分钟步行距离"]
                assert len(support) >= 2, all_rows()
                assert all(r["实际发布值"] == 500 and r["来源报告上限"] == 500 for r in support), support
                assert any(r["与前次支持重叠"] is True for r in support), support
                assert all(r["位于报告上限"] is True for r in support), support
                unknown = [r for r in all_rows() if "支持起点" in r and r.get("项目") == "步行稳定性"]
                assert unknown and all(r["支持起点"] is None and r["来源报告上限"] is None for r in unknown), unknown
                save("W7_low_frequency_support_and_upper_limit", geometry=capture("W7-support"))
                capture("W7-support-windows", page.get_by_text("低频估计的实际发布与支持窗口", exact=True))
                assert not result["errors"], result["errors"]
                result["status"] = "passed"
            except Exception as error:
                result["status"] = "failed"
                result["failure"] = repr(error)
                result["last_page_text"] = text()
                result["last_browser_tables"] = tables
                page.screenshot(path=str(output / "failure.png"))
                raise
            finally:
                (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/master_redesign/pages/workflow-completion")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    run(args.output, prepare_only=args.prepare_only)
