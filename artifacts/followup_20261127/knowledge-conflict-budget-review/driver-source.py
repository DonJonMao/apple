"""Small synthetic real-retrieval regression probe; no original DB or network."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from healthzip.knowledge import KnowledgeWorkbench, metric_retrieval, topics
from tests.integration.test_followup_report_evidence import claim, edge
from tests.knowledge.test_topic_answer_content import TOPIC, bind

sizes = {
    "hrv_metric_and_recording_identity": 2,
    "hrv_direction_and_training_response": 3,
    "wearable_hrv_protocol_transfer": 3,
    "hrv_missing_observation_unit": 3,
}
output = Path(__file__).resolve().parent
assert not (output / "before.json").exists(), "Preserve prior evidence"
with tempfile.TemporaryDirectory(prefix="healthzip-conflict-budget-independent-review-") as folder:
    workbench = KnowledgeWorkbench(Path(folder) / "synthetic", environment_kind="synthetic_test")
    try:
        sid = claim(workbench, "a", topics.PURPOSES, topic=TOPIC)
        premise = claim(workbench, "ap", [], bind=False, topic=TOPIC)
        edge(workbench, "ap", "a", "required_by", [premise, sid])
        rival = claim(workbench, "rival", [], bind=False, topic=TOPIC)
        for index, (need, count) in enumerate(sizes.items()):
            identity = "z" + str(index)
            sid = claim(workbench, identity, topics.ANSWER_NEEDS[need]["purposes"], topic=TOPIC)
            bind(workbench, identity, sid, need_id=need, topic=TOPIC)
            for number in range(count - 1):
                pid = identity + "p" + str(number)
                prerequisite = claim(workbench, pid, [], bind=False, topic=TOPIC)
                edge(workbench, pid, identity, "required_by", [prerequisite, sid])
            edge(workbench, identity, "rival", "conflicts_with", [sid, rival])

        original = metric_retrieval._retrieve_for_metric

        def without_priorities(*args, **kwargs):
            kwargs.pop("answer_priorities", None)
            return original(*args, **kwargs)

        results = {}
        for label, retrieve in [("current", original), ("new_answer_priorities_disabled", without_priorities)]:
            with patch.object(metric_retrieval, "_retrieve_for_metric", retrieve):
                results[label] = topics.question_sources(workbench, TOPIC, k=6)
        summary = {}
        for label, result in results.items():
            audit = result["retrieval"]
            summary[label] = {
                "status": result["status"], "items": [item["claim_id"] for item in result["items"]],
                "restricted": [item["claim_id"] for item in result["restricted_items"]],
                "first_groups": [group["claim_id"] for group in audit["evidence_selection"]["groups"]],
                "supplemental_groups": [group["claim_id"] for group in audit["supplemental_pass"]["evidence_selection"]["groups"]],
                "unique_spans": audit["selected_unique_spans"], "maximum_spans": audit["maximum_unique_spans"],
            }
        receipt = {
            "synthetic_only": True, "original_databases_opened": False, "external_calls": 0,
            "comparison": "Same current code and synthetic library; disable only the newly added answer_priorities argument",
            "answer_group_sizes": sizes, "independent_group_size": 2, "summary": summary,
            "source_hashes": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
                Path("src/healthzip/knowledge/metric_retrieval.py"), Path("src/healthzip/knowledge/topics.py"))},
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "full_results": results,
        }
        (output / "before.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        assert "a" in summary["new_answer_priorities_disabled"]["items"]
        assert "a" in summary["current"]["items"], "Known conflicts displaced the independent valid method/action"
    finally:
        workbench.close()
