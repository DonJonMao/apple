from healthzip.normalize import normalize_value, parse_apple_datetime


def test_timestamp_preserves_offset_and_local_date():
    utc, local, offset, day = parse_apple_datetime("2026-11-03 23:30:00 -0500")
    assert offset == -300
    assert local.startswith("2026-11-03T23:30:00")
    assert day == "2026-11-03"
    assert utc.endswith("Z")


def test_units_and_unknown_unit():
    value, unit, status = normalize_value("HKQuantityTypeIdentifierBodyMass", "220", "lb")
    assert round(value, 4) == 99.7903
    assert unit == "kg" and status == "converted"
    _, _, status = normalize_value("HKQuantityTypeIdentifierBodyMass", "10", "stone")
    assert status == "unit_unverified"


def test_missing_and_category_values_are_not_zero():
    value, _, status = normalize_value("HKQuantityTypeIdentifierHeartRate", "", "count/min")
    assert value is None and status == "unknown"
