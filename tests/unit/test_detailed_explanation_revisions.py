"""Explanation release guards; software verification, not source semantic review."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("deepen", ROOT / "tools/v14_deepen_source_explanations.py")
DEEPEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEEPEN)


def previous():
    return json.loads((ROOT / "artifacts/v14/knowledge/release-1.4.9.json").read_text())


@pytest.mark.parametrize("version,filename", [("1.4.9", "detailed_explanations_1_4_10.json"),
                                             ("1.4.10", "boundary_explanations_1_4_11.json")])
def test_revisions_retain_original_records_and_add_no_candidate_permissions(version, filename):
    base = json.loads((ROOT / f"artifacts/v14/knowledge/release-{version}.json").read_text())
    data = DEEPEN.definition(ROOT / "src/healthzip/knowledge/data" / filename)
    before = copy.deepcopy(base)
    rules = DEEPEN.revised_rules(base, data)
    assert base == before
    assert len(rules) == len(data.get("rule_revisions", data["claim_revisions"]))
    for rule in rules:
        assert rule["requested_capability"] == "source_explanation"
        assert not rule["permitted_actions"] and not rule["numeric_provenance"]
        predecessors = [json.loads(row["payload_json"]) for row in base["rules"] if row["rule_id"] == rule["rule_id"]]
        assert any(len(old["claim_refs"]) == len(rule["claim_refs"]) and all(
            ref in rule["claim_refs"] or {"claim_id": ref["claim_id"], "version": data["version"]} in rule["claim_refs"]
            for ref in old["claim_refs"]) for old in predecessors)
    for item in data["claim_revisions"]:
        claim = item["claim"]
        old = next(json.loads(row["payload_json"]) for row in base["claims"]
                   if row["claim_id"] == item["replaces"]["claim_id"] and row["version"] == item["replaces"]["version"])
        assert old["answer_task"]["outcome"] == claim["answer_task"]["outcome"]
        assert claim["answer_revision_of"] == item["replaces"]


@pytest.mark.parametrize("mutation", ["numerical_action", "candidate_capability", "wrong_predecessor"])
def test_rule_revision_refuses_changed_authority_or_dependency(mutation):
    base, data = previous(), DEEPEN.definition()
    target = data["claim_revisions"][0]["replaces"]
    row = next(r for r in base["rules"] if json.loads(r["payload_json"]).get("claim_refs") == [target]
               and json.loads(r["payload_json"])["requested_capability"] == "source_explanation")
    payload = json.loads(row["payload_json"])
    if mutation == "numerical_action":
        payload["permitted_actions"] = ["double_progression"]
    elif mutation == "candidate_capability":
        payload["requested_capability"] = "trial_candidate"
    else:
        payload["claim_refs"][0]["version"] = "unreviewed"
    row["payload_json"] = json.dumps(payload)
    with pytest.raises(ValueError):
        DEEPEN.revised_rules(base, data)


@pytest.mark.parametrize("mutation", ["action", "unreviewed_dependency", "condition"])
def test_explicit_multi_claim_rule_revisions_cannot_expand_authority(mutation):
    base = json.loads((ROOT / "artifacts/v14/knowledge/release-1.4.10.json").read_text())
    data = DEEPEN.definition(ROOT / "src/healthzip/knowledge/data/boundary_explanations_1_4_11.json")
    rule = data["rule_revisions"][0]["rule"]
    if mutation == "action":
        rule["permitted_actions"] = ["double_progression"]
    elif mutation == "unreviewed_dependency":
        rule["claim_refs"][0]["version"] = "unreviewed"
    else:
        rule["conditions"] = []
    with pytest.raises(ValueError):
        DEEPEN.revised_rules(base, data)
