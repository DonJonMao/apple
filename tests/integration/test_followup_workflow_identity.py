"""Hash preparation preserves all scientific and visibility identities."""
from copy import deepcopy

from healthzip.science.contracts import canonical_hash
from healthzip.workflows.contracts import scientific_identity, workflow_input_hash


def test_shared_workflow_facts_keep_exact_legacy_hash_and_no_persistent_cache():
    metric = {"value": [0, None, -0.0, 1.2345], "computed_at": "transport clock",
              "data_snapshot_hash": "global clock", "source_record_ids": ["a", "b"],
              "window": {"start": "2026-11-01T00:00:00+08:00", "timezone": "Asia/Shanghai"},
              "protocol": {"device": "Synthetic watch", "version": "v1"}}
    payload = {"snapshot": {"metrics": {"STR-10": metric}},
               "supplements": {"training_session_contexts": [{"id": n, "metrics": metric} for n in range(100)]},
               "request": {"cutoff": "2026-11-22", "computed_at": "significant here"},
               "dependencies": {"data_snapshot_hash": "significant dependency", "revision": 1}}

    def legacy():
        return canonical_hash({**payload, "snapshot": scientific_identity(payload["snapshot"]),
                               "supplements": scientific_identity(payload["supplements"])})

    original = deepcopy(payload)
    previous = workflow_input_hash(payload)
    assert previous == legacy()
    assert payload == original
    metric["computed_at"] = "new transport clock"
    assert workflow_input_hash(payload) == previous
    metric["protocol"]["version"] = "v2"
    assert workflow_input_hash(payload) == legacy() != previous
    previous = workflow_input_hash(payload)
    payload["dependencies"]["data_snapshot_hash"] = "new significant dependency"
    assert workflow_input_hash(payload) == legacy() != previous
    public = scientific_identity([metric, metric])
    public[0]["value"].append(42)
    assert public[1]["value"] == metric["value"]
