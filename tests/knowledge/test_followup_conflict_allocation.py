"""Saturated disputed answers cannot remove independent, complete topic uses."""
import pytest

from healthzip.knowledge import KnowledgeWorkbench, topics
from tests.integration.test_followup_report_evidence import claim, edge
from tests.knowledge.test_topic_answer_content import TOPIC, bind


@pytest.mark.parametrize("conflict_on", ["answer", "required_premise"])
def test_saturated_conflicts_preserve_independent_method_and_action(tmp_path, conflict_on):
    workbench = KnowledgeWorkbench(tmp_path / "synthetic-public", environment_kind="synthetic_test")
    try:
        independent = claim(workbench, "a", topics.PURPOSES, topic=TOPIC)
        premise = claim(workbench, "ap", [], bind=False, topic=TOPIC)
        edge(workbench, "ap", "a", "required_by", [premise, independent])
        rival = claim(workbench, "rival", [], bind=False, topic=TOPIC)
        sizes = {"hrv_metric_and_recording_identity": 2, "hrv_direction_and_training_response": 3,
                 "wearable_hrv_protocol_transfer": 3, "hrv_missing_observation_unit": 3}
        for index, (need, count) in enumerate(sizes.items()):
            identity = "z" + str(index)
            sid = claim(workbench, identity, topics.ANSWER_NEEDS[need]["purposes"], topic=TOPIC)
            bind(workbench, identity, sid, need_id=need, topic=TOPIC)
            for number in range(count - 1):
                predecessor = identity + "p" + str(number)
                source = claim(workbench, predecessor, [], bind=False, topic=TOPIC)
                edge(workbench, predecessor, identity, "required_by", [source, sid])
            if conflict_on == "answer":
                edge(workbench, identity, "rival", "conflicts_with", [sid, rival])
            else:
                edge(workbench, predecessor, "rival", "conflicts_with", [source, rival])

        answer = topics.question_sources(workbench, TOPIC, k=6, include_evidence=True)
        audit = answer["retrieval"]
        assert [item["claim_id"] for item in answer["items"]] == ["a"]
        item = answer["items"][0]
        assert set(item["purposes"]) == set(topics.PURPOSES)
        assert {citation["span_id"] for citation in item["citations"]} == {independent, premise}
        assert item["limitations"] and item["statement"]
        assert answer["status"] == "partial_conflict"
        assert len(answer["conflicts"]) == 4
        assert answer["restricted_items"]
        assert all(item["recommendation_allowed"] is False and item["citations"] and item["conflicts"]
                   for item in answer["restricted_items"])
        assert all(value["status"] != "available" for value in audit["answer_status"].values())
        assert audit["requested_k"] == audit["supplemental_pass"]["requested_k"] == 6
        assert audit["selected_unique_spans"] <= audit["maximum_unique_spans"] == 12
        assert audit["supplemental_remote_calls"] == 0
    finally:
        workbench.close()
