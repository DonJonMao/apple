"""Report presentation shares one zone without altering frozen timestamps."""
import pytest

from healthzip.analytics.display_format import local_timestamp


@pytest.mark.parametrize("zone,values,expected", [
    ("Asia/Shanghai", ("2024-09-09T16:30:00+00:00", "2024-09-10T00:30:00+08:00"), "2024-09-10 00:30"),
    ("America/New_York", ("2024-03-10T06:30:00+00:00", "2024-03-10T01:30:00-05:00"), "2024-03-10 01:30"),
    ("America/New_York", ("2024-03-10T07:30:00+00:00", "2024-03-10T03:30:00-04:00"), "2024-03-10 03:30"),
    ("America/New_York", ("2024-11-03T06:30:00+00:00", "2024-11-03T01:30:00-05:00"), "2024-11-03 01:30"),
])
def test_same_instant_offsets_midnight_and_dst(zone, values, expected):
    original = tuple(values)
    assert [local_timestamp(v, zone) for v in values] == [expected, expected]
    assert [local_timestamp(v, zone, date_only=True) for v in values] == [expected[:10]] * 2
    assert values == original
