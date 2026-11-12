"""Software authority/lifecycle tests; not independent source-content review."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("completion", ROOT / "tools/v14_complete_source_explanations.py")
COMPLETION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPLETION)


def previous():
    return json.loads((ROOT / "artifacts/v14/knowledge/release-1.4.11.json").read_text())


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    data, base = COMPLETION.definition(), previous()
    versions = {}
    for source_id, source in data["sources"].items():
        maximum = max(int(s["span_id"].rsplit(":s", 1)[1]) for s in source["reviewed_spans"])
        versions[source_id] = w.lib.record_version(
            source_id, ("Synthetic " + source_id).encode(), "fulltext", {}, {},
            {"index_allowed": True, "license_id": "CC0"}, "matched",
            [{"text": f"Synthetic source {source_id} region {i}; software fixture only.",
              "locator": {"synthetic_region": i, "chapter_id": "4"}}
             for i in range(maximum + 1)], "synthetic-only")

    def bind(claim):
        link = claim["evidence_links"][0]
        link["source_version_id"] = versions[link["source_id"]]
        for part in claim["answer_task"]["answer_parts"]:
            part["span_ids"] = [link["source_version_id"] + ":s" + sid.rsplit(":s", 1)[1] for sid in part["span_ids"]]
        link["span_ids"] = sorted({sid for part in claim["answer_task"]["answer_parts"] for sid in part["span_ids"]})

    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-12T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Authority and lifecycle behavior only."}
    old_refs = [{"claim_id": "CORE-CLAIM-PROGRESSION", "version": "1.4.3"}]
    old_refs.extend(item["replaces"] for item in data["claim_revisions"])
    for ref in old_refs:
        claim = next(json.loads(c["payload_json"]) for c in base["claims"]
                     if c["claim_id"] == ref["claim_id"] and c["version"] == ref["version"])
        if claim.get("answer_revision_of") not in old_refs:
            claim.pop("answer_revision_of", None)
        bind(claim)
        w.review_claim(claim, review)
    for row in base["rules"]:
        rule = json.loads(row["payload_json"])
        if rule["requested_capability"] in {"plan_candidate", "trial_candidate"} or (
                row["rule_id"] == "RULE-N1-REGRESSION-COVARIANCE-EXPLANATION" and row["version"] == "1.4.10"):
            rule.pop("supersedes", None)
            w.review_rule(rule, review)
    frozen = w.release_core(data["previous_release_id"])
    data["previous_release_sha256"] = frozen["sha256"]
    for item in data["claims"] + data["claim_revisions"]:
        bind(item["claim"])
    yield w, data, frozen
    w.close()


def test_append_only_activation_preserves_all_four_candidate_dependencies(library):
    w, data, frozen = library
    before = COMPLETION.TOPICS.HHS.snapshot(w)
    sources = COMPLETION.TOPICS.source_snapshot(w)
    release, _, _, _ = COMPLETION.activate(w, data)
    assert len(release["claims"]) == len(frozen["claims"]) + 5
    assert len(release["rules"]) == len(frozen["rules"]) + 4
    assert COMPLETION.candidate_records(release) == COMPLETION.candidate_records(frozen)
    assert len(COMPLETION.candidate_records(release)["rules"]) == 4
    assert COMPLETION.TOPICS.source_snapshot(w) == sources
    after = COMPLETION.TOPICS.HHS.snapshot(w)
    assert all(row in after[table] for table, rows in before.items() for row in rows)
    assert COMPLETION.activate(w, data)[0] == release


@pytest.mark.parametrize("index", range(5))
def test_explicit_contracts_resolve_new_versions_without_numeric_actions(library, index):
    w, data, _ = library
    COMPLETION.activate(w, data)
    claim = (data["claims"] + data["claim_revisions"])[index]["claim"]
    task = claim["answer_task"]
    context = {"question_contract": {**{k: task[k] for k in ("subject", "outcome", "requested_relation")},
                                     "user_confirmed": True},
               "corpus_roles": ["research"] if task["subject"] == "statistical_inference" else ["core"]}
    result = w.query("解释选定来源主题。", route="strength", context=context, release_id=data["release_id"])
    assert result["answer_status"] == "answered_with_support"
    assert {c["theory_version"] for c in result["claims"]} == {data["version"]}
    assert not result["numeric_actions"]
    assert not w.reviewed_principles("strength", {"requested_capability": "source_explanation"})["principles"]


@pytest.mark.parametrize("mutation", ["action", "capability", "dependency", "condition", "claim_target", "predecessor"])
def test_preflight_rejects_authority_or_predecessor_tampering(mutation):
    data = COMPLETION.definition()
    rule = data["rule_revisions"][0]["rule"]
    if mutation == "action":
        rule["permitted_actions"] = ["double_progression"]
    elif mutation == "capability":
        rule["requested_capability"] = "trial_candidate"
    elif mutation == "dependency":
        rule["claim_refs"][0]["version"] = "unreviewed"
    elif mutation == "condition":
        rule["conditions"] = []
    elif mutation == "claim_target":
        data["claim_revisions"][0]["claim"]["answer_task"]["outcome"] = "personal_optimum"
    else:
        data["claim_revisions"][0]["replaces"]["version"] = "missing"
    with pytest.raises(ValueError):
        COMPLETION.validate_contracts(previous(), data)


def test_general_hhs_quantities_do_not_authorize_personal_numeric_candidates(library):
    w, data, _ = library
    COMPLETION.activate(w, data)
    hhs = [item["claim"] for item in data["claims"] if item["claim"]["answer_task"]["subject"] == "physical_activity"]
    assert all(c["numeric"] for c in hhs)
    for rule in COMPLETION.new_rules(data):
        elevated = copy.deepcopy(rule)
        elevated.update(rule_version="unreviewed-promotion", requested_capability="trial_candidate")
        with pytest.raises(ValueError, match="candidate requires"):
            w.review_rule(elevated, {"reviewer": "Synthetic promotion test", "reviewer_kind": "synthetic_fixture",
                "reviewed_at": "2026-11-12T00:00:00+00:00", "application_checked": True, "rationale": "Software only."})


def test_source_byte_mismatch_cannot_be_reviewed(library):
    w, data, _ = library
    for item in data["claims"] + data["claim_revisions"]:
        link = item["claim"]["evidence_links"][0]
        data["sources"][link["source_id"]]["source_version_id"] = link["source_version_id"]
    with pytest.raises(ValueError, match="source bytes changed"):
        COMPLETION.verify_sources(w, data)
