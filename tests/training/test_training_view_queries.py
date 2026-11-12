"""Normal training views keep complete history available without eager payload scans."""

from datetime import date, timedelta

from healthzip.analytics import all_analysis, p1
from healthzip.db.repository import Repository
from healthzip.strength_log import save_strength_log


def legacy(repo, day, name):
    return save_strength_log(repo, session_date=day, started_at="", name=name, notes="",
        sets=[{"exercise_name": "Synthetic lift", "weight_kg": 40, "reps": 8, "set_number": 1}])


def test_bounded_legacy_strength_view_reads_only_supporting_payloads(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "synthetic-view.sqlite3")
    today = date.today()
    for index in range(12):
        legacy(repo, (today - timedelta(days=90 + index)).isoformat(), f"Old synthetic {index}")
    legacy(repo, today.isoformat(), "Current synthetic")
    returned = {"strength_set": 0, "strength_session": 0}
    original = repo.rows

    def counted(sql, args=()):
        rows = original(sql, args)
        for table in returned:
            if "FROM " + table in sql:
                returned[table] += len(rows)
        return rows

    monkeypatch.setattr(repo, "rows", counted)
    result = p1.strength_quality(repo, today.isoformat(), today.isoformat())
    assert len(result["sets"]) == 1
    assert returned == {"strength_set": 1, "strength_session": 1}
    assert repo.count("strength_set") == 13
    repo.close()


def test_selected_analysis_window_is_used_by_both_strength_views(tmp_path):
    repo = Repository(tmp_path / "synthetic-window.sqlite3")
    today = date.today()
    legacy(repo, (today - timedelta(days=90)).isoformat(), "Outside selected window")
    legacy(repo, today.isoformat(), "Inside selected window")
    result = all_analysis(repo, window_days=7)
    assert result["strength"]["series"] == result["strength_quality"]["series"]
    assert sum(group["records"] for group in result["strength"]["series"]) == 1
    # Explicit unbounded API still exposes every original historical record.
    assert len(p1.strength_quality(repo)["sets"]) == 2
    repo.close()


def test_legacy_noncanonical_day_supported_by_day_parser_is_not_dropped(tmp_path):
    repo = Repository(tmp_path / "synthetic-compact-day.sqlite3")
    today = date.today()
    legacy(repo, today.isoformat(), "Legacy compact date")
    repo.conn.execute("UPDATE strength_set SET set_date=?", (today.strftime("%Y%m%d"),))
    repo.conn.commit()
    # The adapter's existing parser determines format support on this Python.
    if p1._day(today.strftime("%Y%m%d")) is not None:
        assert len(p1.strength_quality(repo, today.isoformat(), today.isoformat())["sets"]) == 1
    repo.close()


def test_same_load_peer_counts_do_not_compare_every_pair(monkeypatch):
    class CountingWeight(float):
        comparisons = 0
        __hash__ = float.__hash__

        def __eq__(self, other):
            type(self).comparisons += 1
            return float.__eq__(self, other)

    count = 1000
    rows = [{"id": index, "session_id": 1, "date": "2020-01-01", "exercise_name": "Synthetic lift",
        "equipment": "barbell", "variation": "", "condition_key": "synthetic-confirmed",
        "comparability_status": "user_confirmed", "warmup": False, "volume_kg": None,
        "e1rm_kg": None, "session": {}, "weight_kg": CountingWeight(40), "reps": 8}
        for index in range(count)]
    monkeypatch.setattr(p1, "_strength_rows", lambda *args: rows)
    result = p1.strength_quality(None)
    assert {row["peer_sets"] for row in result["series"][0]["same_load_reps"]} == {count}
    assert CountingWeight.comparisons < count * 12, "Peer counting must not enumerate all pairs"
