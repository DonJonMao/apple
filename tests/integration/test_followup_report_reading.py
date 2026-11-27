"""Normal reading never restores audit objects; explicit detail is reconstructible."""
import json
from contextlib import closing

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
