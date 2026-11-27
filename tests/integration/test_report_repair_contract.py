"""Independent values verify shared period facts, frozen references and display."""
import json
from contextlib import closing
from datetime import datetime, timedelta

from healthzip.analytics.body_metrics import analyze_body_metric, analyze_questions
from healthzip.analytics.cache import clear
from healthzip.analytics.display_format import format_measurement
from healthzip.analytics.workspace_summary import workspace_summary
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.ui.overview import _select_cards
from healthzip.ui.review_page import report_sections
from healthzip.workflows.period_report import create_report, load_report
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report

CUTOFF = "2024-09-12T00:00:00+08:00"
START = "2024-09-09T00:00:00+08:00"


def independent_records(repo):
    rows = []
    for i, (hours, heart) in enumerate(zip((5, 6, 10), (61.2222, 62.3333, 100.9))):
        wake = datetime.fromisoformat(START) + timedelta(days=i, hours=7)
        for kind, value, unit in (("sleep_stage", None, "category"),
                                  ("resting_heart_rate_bpm", heart, "count/min"),
                                  ("hrv_sdnn_ms", 38 + i, "ms"), ("steps", 2000 - i * 100, "count"),
                                  ("walking_speed_m_s", 1.25, "m/s")):
            start = wake - timedelta(hours=hours) if kind == "sleep_stage" else wake + timedelta(hours=1)
            end = wake if kind == "sleep_stage" else start
            row = {"id": len(rows)+1, "canonical_type": kind, "raw_type": kind,
                   "raw_value": str(value), "normalized_value": value, "raw_unit": unit, "normalized_unit": unit,
                   "category_value": "HKCategoryValueSleepAnalysisAsleepUnspecified" if kind == "sleep_stage" else None,
                   "source_name": "独立合成甲", "device": "独立设备甲", "source_version": "test-4",
                   "start_utc": start.isoformat(), "end_utc": end.isoformat(),
                   "metadata_json": json.dumps({"protocol_id": "固定晨间", "sampling_mode": "background"}), "record_status": "active"}
            rows.append(row)
    row = {**rows[1], "id": 100, "normalized_value": 80, "raw_value": "80", "source_name": "独立合成乙", "device": "独立设备乙"}
    rows.append(row)
    for row in rows:
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) VALUES('health_sample',?,?,?,'synthetic')",
                          (row["id"], row["end_utc"], json.dumps(row)))
    repo.conn.commit()


def test_t05_t19_same_period_values_across_overview_detail_question_report(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        summary = workspace_summary(repo, "总览", cutoff_time=CUTOFF, period="week")["periods"][0]
        sleep = next(f for f in summary["facts"] if f["label"] == "已观察睡眠")
        assert sleep["value"] == 6 and sleep["statistics"]["mean"] == 7
        assert "睡眠中位数" in dict(_select_cards(summary["facts"]))
        heart = next(f for f in summary["facts"] if f["label"] == "静息心率" and f["source_identity"][0] == "独立合成甲")
        assert heart["value"] == 62.3333 and heart["statistics"]["mean"] != heart["value"]
        fields = {"window_start": START, "window_end": CUTOFF, "cutoff_time": CUTOFF, "period": "week"}
        direct = {q["id"]: q for q in analyze_questions(repo, **fields)}
        report = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"},
                               period="week", knowledge_root=tmp_path / "missing")
        for q in report["questions"]:
            assert q["fact_id"] == direct[q["id"]]["fact_id"]
            assert q["rows"] == direct[q["id"]]["rows"]
            assert q["association"] == direct[q["id"]]["association"]
        for kind, qid, expected in (("sleep_stage", "W6", 360), ("resting_heart_rate_bpm", "W4", 62.3333),
                                    ("walking_speed_m_s", "W7", 1.25)):
            metric = analyze_body_metric(repo, kind, source_filter=["独立合成甲"], **fields)
            q = next(q for q in report["questions"] if q["id"] == qid)
            row = next(r for r in q["rows"] if r.get("metric") == kind and r.get("source") == "独立合成甲")
            stream = metric["value"]["streams"][0]
            assert row["value"] == stream["current"]["value"] == expected
            assert row["difference"] == stream["absolute_change"]
            assert row["source_record_ids"]
        assert "6.0 小时" in report["markdown"] and "62.3 bpm" in report["markdown"]
        assert "count/min" not in report["markdown"]
        assert format_measurement(62.3333, "count/min") == "62.3 bpm"
        assert len(report["markdown"].encode()) < 60_000


def test_t05_source_selection_changes_all_report_consumers(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        selected = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai", "source_filter": ["独立合成乙"]},
                                 period="week", knowledge_root=tmp_path / "missing")
        points = [p for group in selected["current"]["metrics"]["STATE-RHR"]["value"].values() for p in group]
        assert [p["value"] for p in points] == [80]
        for q in selected["questions"]:
            assert q["source_filter"] == ["独立合成乙"]
            assert all(r.get("source") != "独立合成甲" for r in q["rows"])
        assert "独立合成甲" not in selected["markdown"]


def test_t12_frozen_content_deduplicated_survives_cache_clear_and_legacy_reads(tmp_path):
    with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
        independent_records(repo)
        fields = {"cutoff_time": CUTOFF, "timezone": "Asia/Shanghai"}
        kwargs = {"period": "week", "knowledge_root": tmp_path / "missing"}
        first, second = create_report(repo, fields, **kwargs), create_report(repo, fields, **kwargs)
        assert first["report_id"] != second["report_id"]
        assert repo.one("SELECT COUNT(*) FROM report_content_object WHERE kind='frozen-report-references-1'")[0] == 1
        frozen = repo.rows("SELECT * FROM report_content_object ORDER BY object_id")
        clear()
        repo.conn.execute("DELETE FROM source_revision")
        repo.conn.commit()
        assert load_report(repo, first["report_id"]) == first
        assert repo.rows("SELECT * FROM report_content_object ORDER BY object_id") == frozen
        bundle = audit_bundle(repo, first["report_id"])
        # Export resolves entirely without current records, this database, or a
        # network source. Duplicate frozen objects have one manifest entry.
        assert reconstruct_report(json.loads(json.dumps(bundle))) == first
        # Historic inline objects remain exact, with no background migration.
        legacy = {"report_id": "old-inline", "version": "joint-period-report-1.3.1", "current": {"frozen": 123}}
        repo.conn.execute("INSERT INTO joint_period_report VALUES(?,?,?,?,?)", ("old-inline", "local", CUTOFF, json.dumps(legacy), "old original"))
        repo.conn.commit()
        assert load_report(repo, "old-inline") == {**legacy, "markdown": "old original"}


def test_preview_projection_matches_full_replay_and_only_requested_period(tmp_path):
    from tests.health_change_fixture import CUTOFF as TRAINING_CUTOFF
    from tests.health_change_fixture import create_health_change_fixture

    path = tmp_path / "synthetic.sqlite3"
    create_health_change_fixture(path)
    with closing(Repository(path)) as repo:
        service = TrainingService(repo)
        bounds = {"cutoff_time": TRAINING_CUTOFF, "window_start": "2026-10-01T00:00:00+08:00", "window_end": TRAINING_CUTOFF}
        full = service.history_as_of(**bounds)
        projected = service.history_summary_as_of(**bounds)
        keys = ("set_uuid", "session_id", "ended_at", "completion_state", "set_type", "session_status", "conflicted")
        assert [{k: r.get(k) for k in keys} for r in projected] == [{k: r.get(k) for k in keys} for r in full]
        both = workspace_summary(repo, "总览", cutoff_time=TRAINING_CUTOFF)
        for period in ("week", "month"):
            one = workspace_summary(repo, "总览", cutoff_time=TRAINING_CUTOFF, period=period)
            assert len(one["periods"]) == 1
            actual = one["periods"][0]
            expected = next(r for r in both["periods"] if r["period"] == period)
            assert actual["facts"] == expected["facts"]
            assert actual["strength_daily"] == expected["strength_daily"]


def test_semantic_report_chapters_do_not_split_table_or_fence():
    original = "# 报告\n\n## 睡眠\n|日|值|\n|---|---|\n|一|6|\n```text\n## 这是原文\n```\n## 下一步\n继续记录。"
    sections = report_sections(original)
    assert [name for name, _ in sections] == ["报告开头", "睡眠", "下一步"]
    assert "|一|6|" in sections[1][1] and "## 这是原文" in sections[1][1]
