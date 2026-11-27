"""Same-day protocol groups remain identifiable in findings and frozen reports."""

import json
from contextlib import closing, nullcontext
from copy import deepcopy

from healthzip.analytics import health_context
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.ui import health_comparison, review_page
from healthzip.workflows import period_report, report_objects

START = "2025-02-03T00:00:00+08:00"
END = "2025-02-05T00:00:00+08:00"
SOURCE = "独立协议标签合成来源"
DEVICE = "独立协议标签合成设备"
PROTOCOL_A = "独立合成晨间固定测量条件及完整协议甲"
PROTOCOL_B = "独立合成晨间固定测量条件及完整协议乙"


def _records():
    specifications = [
        (PROTOCOL_A, "synthetic-v1", {}),
        (PROTOCOL_A, "synthetic-v2", {}),
        (PROTOCOL_B, "synthetic-v1", {}),
        (None, "synthetic-v1", {"sampling_mode": "active", "posture": "seated"}),
        (None, "synthetic-v1", {"sampling_mode": "background", "posture": "supine"}),
        (None, None, {}),
    ]
    rows = []
    for group, (protocol, version, conditions) in enumerate(specifications):
        for day, value in ((3, 64), (4, 66)):
            at = f"2025-02-{day:02d}T08:00:00+08:00"
            rows.append({
                "id": group * 10 + day,
                "canonical_type": "resting_heart_rate_bpm",
                "raw_type": "resting_heart_rate_bpm",
                "raw_value": str(value), "normalized_value": value,
                "raw_unit": "count/min", "normalized_unit": "count/min",
                "source_name": SOURCE, "device": DEVICE, "source_version": version,
                "protocol_id": protocol,
                "metadata_json": json.dumps({"protocol_id": protocol, **conditions}),
                "event_start": at, "event_end": at, "available_at": at,
                "start_utc": at, "end_utc": at, "record_status": "active",
            })
    return rows


def _metric(rows):
    return evaluate(
        "STATE-RHR", rows, cutoff_time=END, window_start=START, window_end=END,
        context={"timezone": "Asia/Shanghai"},
    )


def test_same_day_groups_share_readable_identity_without_pooling_or_mutation():
    rows = _records()
    rows_before = deepcopy(rows)
    metric = _metric(rows)
    before = deepcopy(metric)
    streams = metric["comparison"]["streams"]
    assert len(streams) == 6
    assert {stream["current"]["value"] for stream in streams} == {65}
    assert {
        frozenset(str(record_id) for record_id in stream["current"]["source_record_ids"])
        for stream in streams
    } == {frozenset((str(group * 10 + 3), str(group * 10 + 4))) for group in range(6)}

    statements = health_context.comparison_statements(metric, "日静息心率", "bpm")
    # The original implementation produced six identical sentences despite
    # six actual same-day protocol groups. Check behavior before new helpers.
    assert len(set(statements)) == 6
    labels = health_context.stream_labels(streams)
    assert len(set(labels)) == len(set(statements)) == 6
    for stream, label, statement in zip(streams, labels, statements):
        protocol, version = stream["protocol"][2:4]
        assert SOURCE in label and DEVICE in label
        assert label in statement and "65.0 bpm" in statement
        assert health_comparison._stream_name({**stream, "display_label": label}) == label
        if protocol in {PROTOCOL_A, PROTOCOL_B}:
            assert protocol in label
        else:
            assert "协议" in label and ("未知" in label or "未记录" in label)
        if version:
            assert version in label
        else:
            assert "版本" in label and ("未知" in label or "未记录" in label)
        if protocol and protocol.startswith("context:"):
            expected = ("主动", "坐姿") if "active" in protocol else ("后台", "仰卧")
            assert all(term in label for term in expected)
            assert "context:" not in label and "sampling_mode" not in label
        assert [point["date"] for point in stream["current"]["daily_points"]] == [
            "2025-02-03", "2025-02-04",
        ]
    assert rows == rows_before
    assert metric == before
    navigation = health_context.stream_navigation_labels(streams)
    assert len(set(navigation)) == 6
    assert all(label in option for label, option in zip(labels, navigation))
    assert all(not option.startswith(SOURCE) for option in navigation)
    assert {
        stream["stream_id"]: label
        for stream, label in zip(reversed(streams), health_context.stream_navigation_labels(list(reversed(streams))))
    } == {stream["stream_id"]: label for stream, label in zip(streams, navigation)}


def test_single_stream_avoids_repeating_protocol_and_version_on_the_first_screen():
    metric = _metric(_records()[:2])
    before = deepcopy(metric)
    stream = metric["comparison"]["streams"][0]
    labels = health_context.stream_labels([stream])
    assert len(labels) == 1
    label = labels[0]
    assert SOURCE in label and DEVICE in label
    assert PROTOCOL_A not in label and "synthetic-v1" not in label
    assert health_comparison._stream_name({**stream, "display_label": label}) == label
    assert label in health_context.comparison_statements(metric, "日静息心率", "bpm")[0]
    legacy = {key: value for key, value in stream.items() if key != "protocol"}
    assert health_context.stream_labels([legacy]) == labels
    assert metric == before


def test_opaque_protocol_aliases_are_unique_stable_and_keep_full_identity_in_details():
    protocols = [
        "a8d11b07c4034e0db4af1af6ac574820",
        "a8d11b07c4034e0db4af1af6ac574821",
    ]
    rows = []
    for group, protocol in enumerate(protocols):
        for original in _records()[:2]:
            row = deepcopy(original)
            row["id"] += group * 10
            row["protocol_id"] = protocol
            row["metadata_json"] = json.dumps({"protocol_id": protocol})
            rows.append(row)
    metric = _metric(rows)
    before = deepcopy(metric)
    streams = metric["comparison"]["streams"]
    assert len(streams) == 2
    assert {stream["current"]["value"] for stream in streams} == {65}
    labels = health_context.stream_labels(streams)
    assert len(set(labels)) == 2
    assert all("独立记录组" in label for label in labels)
    assert all(protocol not in label for protocol in protocols for label in labels)
    by_identity = {stream["stream_id"]: label for stream, label in zip(streams, labels)}
    reversed_streams = list(reversed(streams))
    assert {
        stream["stream_id"]: label
        for stream, label in zip(reversed_streams, health_context.stream_labels(reversed_streams))
    } == by_identity
    assert {stream["protocol"][2] for stream in streams} == set(protocols)
    assert metric == before


def test_unmapped_frozen_conditions_do_not_silently_collapse_to_one_label():
    original = _metric(_records()[:2])["comparison"]["streams"][0]
    streams = []
    for setting in ("synthetic-setting-A", "synthetic-setting-B"):
        stream = deepcopy(original)
        # An earlier/imported frozen contract can carry an explicitly recorded
        # condition outside the current six condition fields used for grouping.
        stream["protocol"] = list(stream["protocol"])
        stream["protocol"][2] = "context:" + json.dumps({"unmapped_setting": setting})
        stream["stream_id"] = str(tuple(stream["protocol"]))
        stream["fact_id"] = "synthetic-frozen-condition:" + setting
        streams.append(stream)
    before = deepcopy(streams)
    labels = health_context.stream_labels(streams)
    assert len(set(labels)) == 2
    assert all(SOURCE in label and DEVICE in label for label in labels)
    assert all("独立记录组" in label for label in labels)
    assert all("context:" not in label and "unmapped_setting" not in label for label in labels)
    by_identity = {stream["stream_id"]: label for stream, label in zip(streams, labels)}
    reversed_streams = list(reversed(streams))
    assert {
        stream["stream_id"]: label
        for stream, label in zip(reversed_streams, health_context.stream_labels(reversed_streams))
    } == by_identity
    assert streams == before


class _ReportPage:
    def __init__(self, selected):
        self.selected = selected
        self.options = []
        self.messages = []

    def _record(self, *values, **kwargs):
        self.messages.append(" ".join(str(value) for value in values))

    markdown = _record
    caption = _record
    write = _record

    def selectbox(self, label, options, *, format_func, **kwargs):
        self.options = [format_func(option) for option in options]
        return self.selected

    def expander(self, *args, **kwargs):
        return nullcontext()


def test_report_chart_selection_uses_frozen_groups_and_preserves_legacy_snapshot(monkeypatch):
    metric = _metric(_records())
    payload = {"current": {
        "metrics": {"STATE-RHR": metric}, "window_start": START, "window_end": END,
        "cutoff_time": END, "timezone": "Asia/Shanghai",
    }, "questions": []}
    payload["current"]["joint_health_context"] = health_context.joint_health_context(
        payload["current"]["metrics"], [],
        {"start": START, "end": END, "cutoff_time": END, "timezone": "Asia/Shanghai"},
    )
    before = deepcopy(payload)
    reading = report_objects.reading_view(payload)
    assert payload == before
    streams = reading["charts"][0]["comparison"]["streams"]
    expected_labels = health_context.stream_labels(metric["comparison"]["streams"])
    assert [stream["display_label"] for stream in streams] == expected_labels
    assert all(any(label in finding for finding in reading["findings"]) for label in expected_labels)
    report = {
        "report_id": "synthetic-protocol-groups", "reading_view": reading,
        "markdown": "# 合成协议分组报告\n\n## 本期主要变化\n\n"
        + "\n".join(reading["findings"]),
    }
    monkeypatch.setattr(review_page, "_render_report_source_status", lambda *args, **kwargs: {})
    selected_streams = []
    monkeypatch.setattr(
        health_comparison, "_chart", lambda stream, *args: selected_streams.append(stream),
    )
    for legacy in (False, True):
        shown = deepcopy(report)
        if legacy:
            shown["reading_view"]["version"] = "report-reading-view-1"
            for stream in shown["reading_view"]["charts"][0]["comparison"]["streams"]:
                del stream["display_label"]
        frozen = deepcopy(shown)
        for index, expected in enumerate(streams):
            page = _ReportPage(index)
            monkeypatch.setattr(review_page, "st", page)
            review_page._render_readable_report(shown, "synthetic-stream-labels")
            chosen = selected_streams[-1]
            assert chosen["protocol"] == expected["protocol"]
            assert chosen["fact_id"] == expected["fact_id"]
            assert chosen["current"]["daily_points"] == expected["current"]["daily_points"]
            if not legacy:
                assert len(set(page.options)) == 6
                assert all(label in option for label, option in zip(expected_labels, page.options))
            else:
                # Navigation can use frozen identities without rewriting either
                # the historical Markdown or its frozen reading projection.
                assert len(set(page.options)) == 6
                assert all(SOURCE in option for option in page.options)
                protocol = expected["protocol"][2]
                if protocol in {PROTOCOL_A, PROTOCOL_B}:
                    assert any(protocol in message for message in page.messages)
            assert shown == frozen


def test_report_version_invalidates_old_cache_and_preserves_frozen_bytes(tmp_path, monkeypatch):
    current_version = period_report.REPORT_VERSION
    old_version = "joint-period-report-3.0.1"
    assert current_version != old_version
    with closing(Repository(tmp_path / "synthetic-protocols.sqlite3")) as repo:
        for row in _records():
            repo.conn.execute(
                "INSERT INTO source_revision(table_name,record_id,available_at,payload_json,"
                "temporal_provenance) VALUES('health_sample',?,?,?,'synthetic')",
                (row["id"], row["available_at"], json.dumps(row)),
            )
        repo.conn.commit()
        source_before = [tuple(row) for row in repo.rows("SELECT * FROM source_revision ORDER BY revision_id")]
        args = {"cutoff_time": END, "timezone": "Asia/Shanghai"}
        options = {"period": "week", "knowledge_root": tmp_path / "missing-knowledge"}
        monkeypatch.setattr(period_report, "REPORT_VERSION", old_version)
        old = period_report.create_report(repo, args, **options)
        old_row = tuple(repo.one(
            "SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?",
            (old["report_id"],),
        ))
        old_objects = dict(repo.rows("SELECT object_id,payload_json FROM report_content_object"))
        stages = []
        repeated = period_report.create_report(repo, args, progress=stages.append, **options)
        assert "复用已核对的报告内容" in stages
        assert repeated["content_signature"] == old["content_signature"]

        monkeypatch.setattr(period_report, "REPORT_VERSION", current_version)
        stages.clear()
        revised = period_report.create_report(repo, args, progress=stages.append, **options)
        assert "复用已核对的报告内容" not in stages
        assert "分析本期实际问题与行动" in stages
        assert revised["version"] == current_version
        assert revised["content_signature"] != old["content_signature"]
        chart = next(chart for chart in revised["reading_view"]["charts"] if chart["metric_id"] == "STATE-RHR")
        labels = [stream["display_label"] for stream in chart["comparison"]["streams"]]
        assert len(set(labels)) == 6
        assert all(label in revised["markdown"] for label in labels)
        assert period_report.load_report(repo, old["report_id"]) == old
        assert tuple(repo.one(
            "SELECT payload_json,markdown FROM joint_period_report WHERE report_id=?",
            (old["report_id"],),
        )) == old_row
        objects_after = dict(repo.rows("SELECT object_id,payload_json FROM report_content_object"))
        assert {key: objects_after[key] for key in old_objects} == old_objects
        assert [tuple(row) for row in repo.rows("SELECT * FROM source_revision ORDER BY revision_id")] == source_before
