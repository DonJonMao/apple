"""Software authority/lifecycle checks; not independent source-content review."""

import copy
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("practical", ROOT / "tools/v14_practical_source_explanations.py")
PRACTICAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRACTICAL)


def previous():
    return json.loads((ROOT / "artifacts/v14/knowledge/release-1.4.13.json").read_text())


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    data, base = PRACTICAL.definition(), previous()
    predecessor_rules = {(item["replaces"]["rule_id"], item["replaces"]["version"])
                         for item in data["rule_revisions"]}
    old_rules = [json.loads(row["payload_json"]) for row in base["rules"]
                 if (row["rule_id"], row["version"]) in predecessor_rules
                 or json.loads(row["payload_json"])["requested_capability"] in {"plan_candidate", "trial_candidate"}]
    refs = {(ref["claim_id"], ref["version"]) for rule in old_rules for ref in rule["claim_refs"]}
    old_claims = [json.loads(row["payload_json"]) for row in base["claims"]
                  if (row["claim_id"], row["version"]) in refs]
    all_claims = old_claims + [item["claim"] for item in data["claims"] + data["claim_revisions"]]
    versions = {}
    for source_id in data["sources"]:
        maximum = max(int(sid.rsplit(":s", 1)[1]) for claim in all_claims for link in claim["evidence_links"]
                      if link["source_id"] == source_id for sid in link["span_ids"])
        versions[source_id] = w.lib.record_version(
            source_id, ("Synthetic " + source_id).encode(), "fulltext", {}, {},
            {"index_allowed": True, "license_id": "CC0"}, "matched",
            [{"text": f"Synthetic source {source_id} region {i}; software fixture only.",
              "locator": {"synthetic_region": i, "chapter_id": "4"}}
             for i in range(maximum + 1)], "synthetic-only")

    def bind(claim):
        spans = {}
        for link in claim["evidence_links"]:
            link["source_version_id"] = versions[link["source_id"]]
            for sid in link["span_ids"]:
                spans[sid] = link["source_version_id"] + ":s" + sid.rsplit(":s", 1)[1]
            link["span_ids"] = [spans[sid] for sid in link["span_ids"]]
        for part in claim["answer_task"]["answer_parts"]:
            part["span_ids"] = [spans[sid] for sid in part["span_ids"]]

    review = {"reviewer": "Synthetic software test", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-11-12T00:00:00+00:00", "content_checked": True,
              "application_checked": True, "rationale": "Authority and lifecycle behavior only."}
    for claim in old_claims:
        # The synthetic fixture omits earlier answer revisions, but retains the
        # exact rule dependencies and targets needed for this software test.
        claim.pop("answer_revision_of", None)
        bind(claim)
        w.review_claim(claim, review)
    for rule in old_rules:
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
    before = PRACTICAL.TOPICS.HHS.snapshot(w)
    sources = PRACTICAL.TOPICS.source_snapshot(w)
    release, _, _, _ = PRACTICAL.activate(w, data)
    assert len(release["claims"]) == len(frozen["claims"]) + 6
    assert len(release["rules"]) == len(frozen["rules"]) + 6
    assert PRACTICAL.candidate_records(release) == PRACTICAL.candidate_records(frozen)
    assert len(PRACTICAL.candidate_records(release)["rules"]) == 4
    assert PRACTICAL.TOPICS.source_snapshot(w) == sources
    after = PRACTICAL.TOPICS.HHS.snapshot(w)
    assert all(row in after[table] for table, rows in before.items() for row in rows)
    assert PRACTICAL.activate(w, data)[0] == release


@pytest.mark.parametrize("index", range(6))
def test_explicit_contracts_resolve_new_versions_without_numeric_actions(library, index):
    w, data, _ = library
    PRACTICAL.activate(w, data)
    claim = (data["claims"] + data["claim_revisions"])[index]["claim"]
    task = claim["answer_task"]
    context = {"question_contract": {**{k: task[k] for k in ("subject", "outcome", "requested_relation")},
                                     "user_confirmed": True}, "corpus_roles": ["core"]}
    result = w.query("解释选定来源主题。", route="strength", context=context, release_id=data["release_id"])
    assert result["answer_status"] == "answered_with_support"
    selected = [c for c in result["claims"] if c["theory_id"] == claim["claim_id"]]
    assert selected and {c["theory_version"] for c in selected} == {data["version"]}
    assert not result["numeric_actions"]
    assert not w.reviewed_principles("strength", {"requested_capability": "source_explanation"})["principles"]


@pytest.mark.parametrize("mutation", [
    "action", "capability", "numeric_provenance", "dependency", "condition", "claim_target", "predecessor",
    "numeric_false", "unknown_source", "individual_scope", "population", "aggregation", "review_permission",
    "candidate_permission", "review_source", "review_kind", "supersedes", "rule_predecessor",
])
def test_preflight_rejects_authority_or_predecessor_tampering(mutation):
    data = PRACTICAL.definition()
    item = data["claim_revisions"][0]
    claim, rule = item["claim"], data["rule_revisions"][0]["rule"]
    if mutation == "action":
        rule["permitted_actions"] = ["double_progression"]
    elif mutation == "capability":
        rule["requested_capability"] = "trial_candidate"
    elif mutation == "numeric_provenance":
        rule["numeric_provenance"] = [{"parameter": "sets", "value": 2}]
    elif mutation == "dependency":
        rule["claim_refs"][0]["version"] = "unreviewed"
    elif mutation == "condition":
        rule["conditions"] = []
    elif mutation == "claim_target":
        claim["answer_task"]["outcome"] = "personal_optimum"
    elif mutation == "predecessor":
        item["replaces"]["version"] = "missing"
    elif mutation == "numeric_false":
        claim["numeric"] = False
    elif mutation == "unknown_source":
        claim["evidence_links"][0]["source_id"] = "UNREVIEWED"
    elif mutation == "individual_scope":
        claim["scope"]["individual_inference"] = "authorized"
    elif mutation == "population":
        claim["scope"]["population"] = "children"
    elif mutation == "aggregation":
        claim["scope"]["aggregation"] = "individual_prediction"
    elif mutation == "review_permission":
        item["numeric_explanation_review"]["personal_parameter_authorized"] = True
    elif mutation == "candidate_permission":
        item["numeric_explanation_review"]["candidate_action_authorized"] = True
    elif mutation == "review_source":
        item["numeric_explanation_review"]["source_id"] = "CORE-US-HHS-PAG-2"
    elif mutation == "review_kind":
        item["numeric_explanation_review"]["kind"] = "individual_target"
    elif mutation == "supersedes":
        claim["supersedes"] = item["replaces"]["version"]
    else:
        data["rule_revisions"][0]["replaces"]["version"] = "missing"
    with pytest.raises(ValueError):
        PRACTICAL.validate_contracts(previous(), data)


def test_preflight_failure_does_not_append_any_rows(library):
    w, data, _ = library
    before = PRACTICAL.TOPICS.HHS.snapshot(w)
    data["rule_revisions"][0]["rule"]["permitted_actions"] = ["double_progression"]
    with pytest.raises(ValueError):
        PRACTICAL.activate(w, data)
    assert PRACTICAL.TOPICS.HHS.snapshot(w) == before


@pytest.mark.parametrize("mutation", ["population", "age_range", "goal"])
def test_hhs_quantities_cannot_expand_the_reviewed_adult_health_scope(mutation):
    data = PRACTICAL.definition()
    claim = next(item["claim"] for item in data["claim_revisions"]
                 if item["claim"]["claim_id"] == "CORE-CLAIM-HHS-MUSCLE-START")
    claim["scope"][mutation] = {"population": "all_ages", "age_range": [0, 120], "goal": "individual_optimum"}[mutation]
    with pytest.raises(ValueError, match="HHS Chapter 4"):
        PRACTICAL.validate_contracts(previous(), data)


def test_new_identity_cannot_duplicate_an_existing_answer_target():
    data, base = PRACTICAL.definition(), previous()
    old = next(json.loads(row["payload_json"]) for row in base["claims"]
               if row["claim_id"] == "CORE-CLAIM-ADULT-SCOPE")
    for key in ("subject", "outcome", "requested_relation"):
        data["claims"][0]["claim"]["answer_task"][key] = old["answer_task"][key]
    with pytest.raises(ValueError, match="previous answer target"):
        PRACTICAL.validate_contracts(base, data)


@pytest.mark.parametrize("stage", ["review", "after_release"])
def test_late_failure_rolls_back_every_append_and_new_release(library, monkeypatch, stage):
    w, data, _ = library
    before = PRACTICAL.TOPICS.HHS.snapshot(w)
    connection = w.lib.theories

    def fail(*args, **kwargs):
        raise ValueError("injected late failure")

    # Both hooks execute after all six new claims have been appended; the
    # second additionally executes after rules and the release were inserted.
    monkeypatch.setattr(w, "review_rule" if stage == "review" else "reviewed_principles", fail)
    with pytest.raises(ValueError, match="injected late failure"):
        PRACTICAL.activate(w, data)
    assert w.lib.theories is connection
    assert not connection.in_transaction
    assert PRACTICAL.TOPICS.HHS.snapshot(w) == before


def test_live_membership_drift_fails_before_reviewing_claims(library, monkeypatch):
    w, data, _ = library
    with w.lib.theories:
        w.lib.theories.execute("UPDATE source_claim SET status='disabled' WHERE claim_id='CORE-CLAIM-PROGRESSION'")
    before = PRACTICAL.TOPICS.HHS.snapshot(w)

    def unexpected(*args, **kwargs):
        pytest.fail("claim review must not begin when frozen membership has drifted")

    monkeypatch.setattr(w, "review_claim", unexpected)
    with pytest.raises(ValueError, match="live knowledge membership"):
        PRACTICAL.activate(w, data)
    assert PRACTICAL.TOPICS.HHS.snapshot(w) == before


def test_general_source_quantities_cannot_be_promoted_to_numeric_candidates(library):
    w, data, frozen = library
    PRACTICAL.activate(w, data)
    assert all(item["claim"]["numeric"] for item in data["claims"] + data["claim_revisions"])
    for rule in PRACTICAL.validate_contracts(frozen, data):
        elevated = copy.deepcopy(rule)
        elevated.update(rule_version="unreviewed-promotion", requested_capability="trial_candidate")
        with pytest.raises(ValueError, match="candidate requires"):
            w.review_rule(elevated, {"reviewer": "Synthetic promotion test", "reviewer_kind": "synthetic_fixture",
                "reviewed_at": "2026-11-12T00:00:00+00:00", "application_checked": True, "rationale": "Software only."})


def test_readonly_verification_cannot_write_either_database(library):
    w, data, frozen = library
    before = PRACTICAL.TOPICS.HHS.snapshot(w)
    with PRACTICAL.readonly_workbench(w.root) as readonly:
        assert PRACTICAL.previous_release(readonly, data)["claims"] == frozen["claims"]
        for connection in (readonly.lib.sources, readonly.lib.theories):
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("CREATE TABLE should_never_exist (id INTEGER)")
    assert PRACTICAL.TOPICS.HHS.snapshot(w) == before


def test_source_byte_mismatch_cannot_be_reviewed(library):
    w, data, _ = library
    for item in data["claims"] + data["claim_revisions"]:
        link = item["claim"]["evidence_links"][0]
        data["sources"][link["source_id"]]["source_version_id"] = link["source_version_id"]
    with pytest.raises(ValueError, match="source bytes changed"):
        PRACTICAL.verify_sources(w, data)
