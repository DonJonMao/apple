"""Theme eligibility uses actual observations, not arbitrary contextual rows."""
import json
from contextlib import closing

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.db.repository import Repository
from healthzip.workflows.period_report import create_report, load_report

START = "2024-09-09T00:00:00+08:00"
END = "2024-09-12T00:00:00+08:00"


def record(repo, kind, value, *, table="health_sample", identity=1, unit="count"):
    at = "2024-09-10T08:00:00+08:00"
    row = {"id": identity, "canonical_type": kind, "raw_type": kind,
           "normalized_value": value, "raw_value": str(value),
           "normalized_unit": unit, "raw_unit": unit,
           "source_name": "合成来源", "device": "合成设备", "source_version": "fixture-1",
           "start_utc": at, "end_utc": at, "event_time": at,
           "metadata_json": "{}", "record_status": "active"}
    if table == "subjective_log":
        row.update(fatigue=value, notes="已填写的背景", recorded_at=at)
    if kind in {"high_hr_event", "menstrual_flow"}:
        row.update(category_value="recorded", normalized_value=None)
    repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES(?,?,?,?,'synthetic')",
                      (table, identity, at, json.dumps(row)))
    repo.conn.commit()


def questions(repo, **extra):
    return {q["id"]: q for q in analyze_questions(repo, window_start=START, window_end=END,
        cutoff_time=END, period="week", **extra)}


def test_fatigue_keeps_background_without_inventing_topics(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        record(repo, "fatigue", 7, table="subjective_log")
        views = questions(repo)
        assert views["W2"]["topic_status"]["state"] == "context_only"
        assert "疲劳 7" in views["W2"]["observation"]
        assert views["W4"]["topic_status"]["state"] == "no_records"
        assert not views["W4"]["topic_status"]["has_goal"]
        assert not views["W4"]["steps"]
        for qid in ("W7", "W8", "E"):
            assert not views[qid]["topic_status"]["has_primary_records"]
            assert not views[qid]["steps"]
            assert not any(r["type"] in {"event", "event_training"} for r in views[qid]["rows"])
        report = create_report(repo, {"cutoff_time": END, "timezone": "Asia/Shanghai"},
            period="week", knowledge_root=tmp_path / "missing")
        assert "疲劳 7" in report["markdown"]
        assert "疲劳 7" in report["reading_view"]["findings"][0]
        assert "共有 0 天" not in report["reading_view"]["findings"][0]
        assert "核对原通知" not in report["markdown"]
        for title in (views["W7"]["title"], views["W8"]["title"], views["E"]["title"]):
            assert title not in report["markdown"]
        frozen = load_report(repo, report["report_id"])
        assert {q["id"]: q["topic_status"] for q in frozen["questions"]} == {
            qid: q["topic_status"] for qid, q in views.items()}


def test_steps_alone_describes_amount_and_names_missing_speed(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        record(repo, "steps", 2310)
        view = questions(repo)["W7"]
        assert view["topic_status"]["state"] == "partial"
        assert view["topic_status"]["primary_metrics"] == ["steps"]
        assert "2,310" in view["observation"]
        assert next(r for r in view["rows"] if r.get("metric") == "steps")["value"] == 2310
        assert "步速" in "".join(view["limitations"])
        assert not any("步速下降" in text for text in [view["observation"], *view["steps"]])


def test_actual_device_event_is_independent_and_has_record_identity(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        record(repo, "high_hr_event", None)
        view = questions(repo)["E"]
        assert view["topic_status"]["state"] == "descriptive"
        event = next(r for r in view["rows"] if r["type"] == "event")
        assert event["source_record_ids"] == ["health_sample:1"]
        assert event["device"] == "合成设备"
        assert "2024-09-10" in view["observation"]
        assert event["title"] in "".join(view["steps"])


def test_cycle_disabled_enabled_empty_and_actual_record(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        assert questions(repo, cycle_enabled=False)["W8"]["topic_status"]["state"] == "disabled"
        enabled = questions(repo, cycle_enabled=True)["W8"]
        assert enabled["topic_status"]["state"] == "no_records"
        assert "已开启" in enabled["observation"]
        record(repo, "menstrual_flow", None)
        actual = questions(repo, cycle_enabled=False)["W8"]
        assert actual["topic_status"]["state"] == "descriptive"
        assert actual["topic_status"]["has_primary_records"]
        assert "相位" not in actual["observation"]


def test_existing_body_facts_do_not_invent_a_previously_selected_goal(tmp_path):
    with closing(Repository(tmp_path / 'synthetic.sqlite3')) as repo:
        record(repo, 'body_mass_kg', 72, unit='kg')
        record(repo, 'high_hr_event', 1, identity=2)
        view = questions(repo)['W4']
        assert view['topic_status']['has_primary_records']
        assert not view['topic_status']['has_goal']
        assert not view['action_reviews']
        assert '先前选择' not in ' '.join(view['steps'])
        assert any('体重' in step and '来源' in step for step in view['steps'])
        report = create_report(repo, {'cutoff_time': END, 'timezone': 'Asia/Shanghai'},
            period='week', knowledge_root=tmp_path / 'missing')
        assert '先前选择的动作和目标尺度' not in report['markdown']
        final_steps = report['markdown'].split('## 下一步\n', 1)[1].split('## 冻结依据', 1)[0]
        assert final_steps.strip().splitlines()[0].startswith('- 核对 2024-09-10 合成来源')
        assert 'health_sample:2' in final_steps
        assert load_report(repo, report['report_id'])['markdown'] == report['markdown']
