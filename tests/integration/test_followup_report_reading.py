"""Normal reading never restores audit objects; explicit detail is reconstructible."""
import json
from contextlib import closing

import pytest

from healthzip.db.repository import Repository
from healthzip.workflows.period_report import create_report, load_report
from healthzip.workflows.report_objects import audit_bundle, read_question, reconstruct_report
from tests.integration.test_report_repair_contract import CUTOFF, independent_records


def test_reading_and_single_question_load_only_requested_frozen_objects(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        args = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        report = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        assert "current" not in report
        assert report["reading_view"]["global_metric_count"] == 77
        assert all("rows" not in q for q in report["questions"])
        queries = []
        repo.conn.set_trace_callback(queries.append)
        restored = load_report(repo, report["report_id"])
        repo.conn.set_trace_callback(None)
        assert restored == report
        assert not any("FROM analysis_run" in q or "FROM workflow_run" in q for q in queries)
        assert sum("SELECT payload_json FROM report_content_object" in q for q in queries) == 1
        sleep = next(q for q in report["questions"] if q["id"] == "W6")
        queries.clear()
        repo.conn.set_trace_callback(queries.append)
        detail = read_question(repo, sleep)
        repo.conn.set_trace_callback(None)
        assert any(r.get("metric") == "sleep_stage" and r["value"] == 360 for r in detail["rows"])
        assert sum("SELECT payload_json FROM report_content_object" in q for q in queries) == 1
        full = load_report(repo, report["report_id"], include_details=True)
        assert full["markdown"] == report["markdown"]
        assert detail["rows"] == next(q for q in full["questions"] if q["id"] == "W6")["rows"]
        bundle = json.loads(json.dumps(audit_bundle(repo, report["report_id"])))
        assert reconstruct_report(bundle) == full
        repo.conn.execute("DELETE FROM source_revision")
        repo.conn.commit()
        assert load_report(repo, report["report_id"]) == report
        assert read_question(repo, sleep)["rows"] == detail["rows"]


def test_hot_generation_keeps_independent_version_without_full_restore(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        args = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        first = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        queries = []
        repo.conn.set_trace_callback(queries.append)
        second = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        repo.conn.set_trace_callback(None)
        assert first["report_id"] != second["report_id"]
        assert first["content_signature"] == second["content_signature"]
        assert first["reading_view"] == second["reading_view"]
        assert not any("FROM analysis_run" in q or "FROM workflow_run" in q for q in queries)


@pytest.mark.parametrize("version_field,frozen_field", [("GUIDANCE_VERSION", "guidance_version"),
                                                       ("VERSION", "analysis_version")])
def test_report_cache_tracks_question_versions_without_rewriting_old_freeze(tmp_path, monkeypatch, version_field, frozen_field):
    from healthzip.analytics import body_questions

    with closing(Repository(tmp_path / "question-versions.sqlite3")) as repo:
        independent_records(repo)
        args = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        first = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        repeated = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        assert repeated["content_signature"] == first["content_signature"]
        old_question = read_question(repo, next(q for q in first["questions"] if q["id"] == "W2"))
        updated_version = "synthetic-updated-" + version_field.lower()
        monkeypatch.setattr(body_questions, version_field, updated_version)
        revised = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        new_question = read_question(repo, next(q for q in revised["questions"] if q["id"] == "W2"))
        assert new_question[frozen_field] == updated_version
        assert revised["content_signature"] != first["content_signature"]
        assert new_question["rows"] == old_question["rows"]
        assert new_question["observation"] == old_question["observation"]
        assert load_report(repo, first["report_id"]) == first
        assert read_question(repo, next(q for q in first["questions"] if q["id"] == "W2")) == old_question


@pytest.mark.parametrize("module_name,version_field", [
    ("healthzip.knowledge.metric_retrieval", "RETRIEVAL_VERSION"),
    ("healthzip.knowledge.topics", "ANSWER_NEEDS_VERSION"),
])
def test_report_rechecks_evidence_after_method_version_change_without_rewriting_history(
        tmp_path, monkeypatch, module_name, version_field):
    import importlib
    from datetime import datetime, timezone

    from healthzip.science import contracts

    class MetricClockType(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, datetime)

    class FixedMetricClock(datetime, metaclass=MetricClockType):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 27, 1, 2, 3, tzinfo=timezone.utc)

    # Isolate evidence-method invalidation from the metric computation timestamp
    # that legitimately contributes to a newly calculated joint fact identity.
    monkeypatch.setattr(contracts, "datetime", FixedMetricClock)

    with closing(Repository(tmp_path / "evidence-methods.sqlite3")) as repo:
        independent_records(repo)
        args = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        first = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing")
        before = tuple(repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (first["report_id"],)))
        stages = []
        repeated = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing", progress=stages.append)
        assert "复用已核对的报告内容" in stages
        assert repeated["content_signature"] == first["content_signature"]
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, version_field, "synthetic-new-evidence-method")
        stages.clear()
        revised = create_report(repo, args, period="week", knowledge_root=tmp_path / "missing", progress=stages.append)
        assert "分析本期实际问题与行动" in stages
        assert "复用已核对的报告内容" not in stages
        assert revised["report_id"] not in {first["report_id"], repeated["report_id"]}
        assert revised["reading_view"] == first["reading_view"]
        assert tuple(repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?", (first["report_id"],))) == before
        assert load_report(repo, first["report_id"]) == first


def test_same_timestamp_history_versions_open_the_selected_frozen_id(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from streamlit.testing.v1 import AppTest

    from healthzip.workflows import period_report

    class FixedCreationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 27, 1, 2, 3, tzinfo=timezone.utc)

    monkeypatch.setattr(period_report, 'datetime', FixedCreationClock)
    monkeypatch.chdir(tmp_path)
    with closing(Repository(tmp_path / 'synthetic.sqlite3')) as repo:
        independent_records(repo)
        args = {'cutoff_time': CUTOFF, 'timezone': 'Asia/Shanghai'}
        reports = [create_report(repo, args, period='week', knowledge_root=tmp_path / 'missing') for _ in range(2)]
        assert reports[0]['created_at'] == reports[1]['created_at']
        assert reports[0]['report_id'] != reports[1]['report_id']
        script = ('from healthzip.db.repository import Repository\n'
                  'from healthzip.ui.review_page import _history\n'
                  f'repo = Repository({str(repo.path)!r})\n'
                  '_history(repo)\nrepo.close()\n')
        app = AppTest.from_string(script).run(timeout=30)
        assert not app.exception
        chooser = next(s for s in app.selectbox if s.label == '历史复盘')
        assert len(set(chooser.options)) == 2
        for report in reports:
            chooser = next(s for s in app.selectbox if s.label == '历史复盘')
            chooser.set_value(report['report_id']).run(timeout=30)
            next(b for b in app.button if b.label == '打开这份复盘').click().run(timeout=30)
            assert not app.exception
            assert app.session_state['opened_report:' + str(repo.path.resolve())] == report['report_id']
            assert any('data-hz-report-id="' + report['report_id'] + '"' in m.value for m in app.markdown)
            assert load_report(repo, report['report_id'])['markdown'] == report['markdown']


def test_history_versions_disambiguate_colliding_short_identifiers():
    from healthzip.ui.review_page import report_history_labels

    ids = ['abcdef01aa', 'abcdef01ab', 'abcdef02aa']
    rows = [{'report_id': identity, 'created_at': '2026-11-27T01:02:03+00:00', 'period': 'week'} for identity in ids]
    labels = report_history_labels(rows, 'Asia/Shanghai')
    assert len(set(labels.values())) == 3
    assert all('2026-11-27 09:02' in label for label in labels.values())
    assert all(identity.startswith(label.split('版本 ')[1]) for identity, label in labels.items())
