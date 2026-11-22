"""Metadata reuse must not merge measurement conditions or unknown sources."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from healthzip.analytics import workspaces


def test_ordinary_samples_resolve_shared_identity_but_keep_protocol_boundaries(monkeypatch):
    original = workspaces.physiology_stream_key
    calls = []

    def track(row):
        calls.append(row["id"])
        return original(row)

    monkeypatch.setattr(workspaces, "physiology_stream_key", track)
    rows = [{"id": str(i), "canonical_type": "heart_rate_bpm", "value": 60+i, "unit": "count/min",
             "event_end": f"2026-11-01T10:{i:02d}:00+08:00", "source_name": "watch", "device": "A"}
            for i in range(10)]
    rows += [{**rows[0], "id": "new-device", "device": "B"},
             {**rows[0], "id": "active", "metadata_json": '{"activity_context":"active"}'},
             {**rows[0], "id": "rest", "activity_context": "rest"},
             {**rows[0], "id": "unknown-1", "source_name": None},
             {**rows[0], "id": "unknown-2", "source_name": None}]
    result = workspaces._ordinary_heart_observations(rows, datetime(2026, 11, 1, tzinfo=timezone.utc),
                datetime(2026, 11, 2, tzinfo=timezone.utc), ZoneInfo("Asia/Shanghai"))
    assert len(calls) == 6
    assert len(result["ordinary_daily"]) == 6
    assert result["ordinary_sample_count"] == 15
    assert sorted(row["sample_count"] for row in result["ordinary_daily"]) == [1, 1, 1, 1, 1, 10]


def test_public_window_label_uses_analysis_zone_and_half_open_endpoint():
    from healthzip.ui.body_workspace import local_window_label

    value = local_window_label("2026-11-21T16:00:00+00:00", "2026-11-22T16:00:00+00:00", "Asia/Shanghai")
    assert "2026-11-22 00:00 — 2026-11-23 00:00" in value
    assert "不含结束时刻" in value
