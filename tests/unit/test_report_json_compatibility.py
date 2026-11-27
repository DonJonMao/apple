"""Fast-reader eligibility must retain nested numeric and extension boundaries."""
import math

import pytest

from healthzip.workflows.period_report import _fast_json_compatible


class RecordedInteger(int):
    pass


class RecordedFloat(float):
    pass


@pytest.mark.parametrize("value,expected", [
    (-2**63, True), (2**64-1, True), (-2**63-1, False), (2**64, False),
    (RecordedInteger(2**64), False), (RecordedInteger(-2**63), True),
    (RecordedFloat("inf"), False), (float("nan"), False),
    (float("-inf"), False), (math.nextafter(0, 1), True), (-0.0, True),
])
def test_numeric_boundary_inside_shared_tuple_and_list(value, expected):
    shared = {"vendor metadata": ["原始值", None, True, (value,)]}
    assert _fast_json_compatible({"first": shared, "same": shared}) is expected


def test_deep_containers_do_not_require_python_recursion():
    root = {"value": float("inf")}
    for _ in range(1500):
        root = [root]
    assert not _fast_json_compatible(root)


def test_shared_cycles_terminate_but_do_not_hide_unsafe_sibling():
    cycle = []
    cycle.append(cycle)
    # This gate only checks numeric decoder eligibility. JSON serialization
    # separately rejects cyclic payloads, exactly as before this optimization.
    assert _fast_json_compatible(cycle)
    assert not _fast_json_compatible({"cycle": cycle, "sibling": [2**100]})
