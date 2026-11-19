"""Synthetic energy intervals retain complete provenance at export scale."""

from datetime import datetime, timedelta, timezone

from healthzip.normalize import quantity_value
from healthzip.science.contracts import Window
from healthzip.science.energy import atomic_energy

ORIGIN = datetime(2026, 11, 1, tzinfo=timezone.utc)
WINDOW = Window(ORIGIN.isoformat(), (ORIGIN + timedelta(days=7)).isoformat(),
                (ORIGIN + timedelta(days=7)).isoformat())


def sample(identity, start, end, **extra):
    return {"_source_id": identity, "canonical_type": "active_energy_kcal",
            "event_start": (ORIGIN + timedelta(seconds=start)).isoformat(),
            "_event_end": (ORIGIN + timedelta(seconds=end)).isoformat(),
            "normalized_value": 0.125, "normalized_unit": "kcal",
            "source_name": "synthetic_watch", "device_id": "watch1",
            "protocol_id": "synthetic_energy_v1", **extra}


def test_nested_tied_and_adjacent_intervals_keep_all_ordered_conflicts_and_sources():
    rows = [sample("e", 3, 4), sample("c", 1, 5), sample("b", 0, 2),
            sample("a", 0, 6), sample("d", 2, 3),
            sample("other_stream", 0, 6, device_id="watch2"),
            sample("invalid_unit", 0, 1, normalized_unit="unknown"),
            sample("boundary", -1, 0)]
    output = atomic_energy(rows, "active_energy_kcal", WINDOW)
    assert output["conflicts"] == [["b", "a"], ["b", "c"], ["a", "c"],
                                   ["a", "d"], ["a", "e"], ["c", "d"], ["c", "e"]]
    assert output["unknown_or_boundary_ids"] == ["invalid_unit", "boundary"]
    streams = output["streams"]
    assert len(streams) == 2
    first, other = streams
    assert first["source_ids"] == ["b", "a", "c", "d", "e"]
    assert first["sample_count"] == 5
    assert first["conflicted"] is True and first["known_kcal"] is None
    by_id = {r["_source_id"]: r for r in rows}
    assert first["numeric_provenance"] == [quantity_value(by_id[i]) for i in first["source_ids"]]
    assert other == {"stream": ["synthetic_watch", "watch2", "synthetic_energy_v1", None],
                     "known_kcal": 0.125, "sample_count": 1, "conflicted": False,
                     "source_ids": ["other_stream"], "numeric_provenance": [quantity_value(rows[5])]}


def test_many_nonoverlapping_intervals_keep_every_value_and_source():
    count = 5000
    rows = [sample(f"synthetic-{i}", i, i + 1) for i in range(count)]
    output = atomic_energy(list(reversed(rows)), "active_energy_kcal", WINDOW)
    assert output["conflicts"] == [] and output["unknown_or_boundary_ids"] == []
    stream, = output["streams"]
    assert stream["known_kcal"] == count * 0.125
    assert stream["sample_count"] == count and stream["conflicted"] is False
    assert stream["source_ids"] == [row["_source_id"] for row in rows]
    assert stream["numeric_provenance"] == [quantity_value(row) for row in rows]
