"""Bounded report queries keep explicitly required old execution and baseline."""

from test_v14_followup_report import report
from test_v14_followup_report import trial as trial

from healthzip.analytics.v13 import snapshot


def test_later_followup_report_retains_execution_baseline_and_declared_support(request):
    repo, _, _, _, baseline, execution, add = request.getfixturevalue("trial")
    later = add(4, reps=10)
    rows, context = snapshot(repo, "2026-02-11T00:00:00Z",
        window_start="2026-02-01T00:00:00Z", window_end="2026-03-01T00:00:00Z")
    identities = {row.get("set_uuid") for row in rows}
    assert identities == {baseline["set_uuid"], execution["set_uuid"], later["set_uuid"]}
    assert set(context["query_plan"]["training_required_set_ids"]) == {baseline["set_uuid"], execution["set_uuid"]}
    value = report(repo, "2026-02-11T00:00:00Z", period="month")
    item = value["execution"]["value"][0]
    assert item["execution_change"]["differences"]["reps"]["value"] == -2
    assert item["actual_observations"][0]["record_id"] == execution["set_uuid"]
    assert value["followup_windows"][0]["observations"][0]["after"]["record_id"] == later["set_uuid"]
