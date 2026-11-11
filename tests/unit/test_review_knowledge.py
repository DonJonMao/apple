"""Review R05/R06/R15 and answer-support counterexamples; synthetic evidence only."""

import json
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from lxml import etree

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import parse_jats, rights_from_xml
from healthzip.knowledge.adjudication import annotation_identity, validate_annotation
from healthzip.knowledge.retrieval import validate_answer

THEORY = "TC-progression-load-repetition-options"
QUESTION = "合成方案是否允许增加重复次数？"
TARGET = {"proposition": "合成方案允许增加重复次数", "scope": {"population": "synthetic_adults", "time_scale": "study_protocol"}}


@pytest.fixture
def library(tmp_path):
    workbench = KnowledgeWorkbench(tmp_path / "knowledge")
    workbench.seed()
    yield workbench
    workbench.close()


def approve(workbench, version="0.1.0", *, theory=THEORY, relation="supports", bound=True):
    source = workbench.lib.record_version("S5", b"Synthetic protocol permits repetition progression.", "fulltext",
        {"url": "https://example.test/synthetic"}, {"title": "Synthetic protocol"},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic protocol permits repetition progression.", "locator": {"xpath": "/article/body/p"}}])
    sid = source + ":s00000"
    claim = {"text": "合成方案允许增加重复次数；不表示个人寿命或其他长期效果。", "span_ids": [sid],
             "support_rationale": "Synthetic assertion for software regression only."}
    if bound:
        claim["answer_bindings"] = [{"question": QUESTION, "target_claim": TARGET, "relation": relation,
                                     "rationale": "Synthetic test annotation; not an independent scientific review."}]
    request = {"reviewer": "Synthetic implementing-agent fixture", "reviewer_kind": "synthetic_fixture",
        "rationale": "Software fixture only; no real professional authority.", "claims": [claim],
        "evidence_links": [{"source_id": "S5", "source_version_id": source, "span_ids": [sid]}],
        "applicability": {"required": {}, "scope": "synthetic"}}
    workbench.review_theory(theory, version, **request)
    return source, sid, request


def test_r05_revocation_keeps_review_and_frozen_history_but_stops_current_use(library):
    _, _, request = approve(library)
    release = library.release("before-withdrawal")
    old_review = release["theories"][0]["review_json"]
    old_answer = library.query(QUESTION, "progression")
    assert old_answer["status"] == "evidence_supported"
    library.review_theory(THEORY, "0.1.0", **{**request, "decision": "needs_review", "rationale": "Synthetic claim error; source itself remains correct."})
    assert library.query(QUESTION, "progression")["status"] == "insufficient_evidence"
    assert library.query(QUESTION, "progression", release_id="before-withdrawal")["status"] == "insufficient_evidence"
    assert library.lib.released_theories("before-withdrawal")[0]["review_json"] == old_review
    assert "theory_approval_no_longer_current" in validate_answer(library, old_answer, old_answer)
    assert library.lib.source("S5")["scientific_state"] == "current"
    assert library.lib.theories.execute("SELECT COUNT(*) FROM theory_lifecycle").fetchone()[0] == 1


def test_r05_revision_activates_only_replacement_and_records_supersedes(library):
    approve(library)
    library.revise_theory(THEORY, "0.1.0", "0.2.0", reviewer="synthetic", rationale="Explicit replacement")
    assert [x["theory_version"] for x in library.query(QUESTION, "progression")["retrieval"]["candidates"]] == ["0.1.0"]
    approve(library, "0.2.0")
    assert [x["theory_version"] for x in library.query(QUESTION, "progression")["retrieval"]["candidates"]] == ["0.2.0"]
    event = library.lib.theories.execute("SELECT * FROM theory_lifecycle WHERE action='superseded'").fetchone()
    assert event["version"] == "0.1.0" and event["superseded_by"] == "0.2.0"
    library.theory_state(THEORY, "0.2.0", "disabled", actor="synthetic", rationale="Temporarily suspend")
    assert not library.query(QUESTION, "progression")["citations"]
    library.theory_state(THEORY, "0.2.0", "activate", actor="synthetic", rationale="Same reviewed content eligible again")
    assert library.query(QUESTION, "progression")["status"] == "evidence_supported"


def test_r15_fetch_success_never_clears_correction_or_withdrawal(library):
    version, sid, _ = approve(library)
    library.lib.update_state("S5", "corrected_pending_review", "Synthetic correction notice")
    for material in ("metadata", "abstract", "fulltext"):
        library.lib.record_version("S5", material.encode(), material, {}, {}, {"index_allowed": True}, "matched")
        assert library.lib.source("S5")["acquisition_state"] == "acquired"
        assert library.lib.source("S5")["scientific_state"] == "corrected_pending_review"
        assert library.lib.eligible(library.lib.span(sid)) == (False, "corrected_pending_review")
    library.lib.update_state("S5", "acquired", "Ordinary retry success")
    assert not library.lib.eligible(library.lib.span(sid))[0]
    library.review_source_state("S5", reviewer="synthetic", rationale="Explicit review of correction",
                                source_version_ids=[version])
    assert library.lib.eligible(library.lib.span(sid))[0]
    assert not library.query(QUESTION, "progression")["citations"]  # theory needs its own new review
    library.lib.update_state("S5", "withdrawn", "Synthetic withdrawal")
    library.lib.update_state("S5", "corrected_pending_review", "Lower-priority metadata update")
    assert library.lib.source("S5")["scientific_state"] == "withdrawn"


def test_source_clearance_applies_only_to_the_reviewed_version_and_current_notice(library):
    version, sid, _ = approve(library)
    metadata = library.lib.record_version("S5", b"synthetic metadata", "metadata", {}, {}, {"index_allowed": False}, "matched")
    library.lib.update_state("S5", "corrected_pending_review", "First correction")
    library.review_source_state("S5", reviewer="synthetic", rationale="Metadata identity checked only", source_version_ids=[metadata])
    assert not library.lib.eligible(library.lib.span(sid))[0]
    library.review_source_state("S5", reviewer="synthetic", rationale="Exact fulltext correction reviewed", source_version_ids=[version])
    assert library.lib.eligible(library.lib.span(sid))[0]
    library.revise_theory(THEORY, "0.1.0", "0.2.0", reviewer="synthetic", rationale="Exact cleared version re-reviewed")
    approve(library, "0.2.0")
    assert library.release("after-exact-clearance")["source_versions"][0]["version_id"] == version
    library.lib.update_state("S5", "corrected_pending_review", "Second correction")
    assert not library.lib.eligible(library.lib.span(sid))[0]
    library.lib.update_state("S5", "withdrawn", "Retraction")
    with pytest.raises(ValueError, match="withdrawn"):
        library.review_source_state("S5", reviewer="synthetic", rationale="No retraction resolution", source_version_ids=[version])


def test_r06_component_license_never_licenses_the_parent_or_other_components(library):
    raw = (Path(__file__).parents[1] / "fixtures/synthetic_scoped_permissions.xml").read_bytes()
    metadata, spans, rights = parse_jats(raw)
    assert metadata["doi"] == "10.0/synthetic-main"
    assert rights["index_allowed"] is False and rights["partially_indexable"] is True
    by_id = {span["locator"]["native_id"]: span for span in spans if span["locator"]["native_id"]}
    assert not by_id["main"]["rights"]["index_allowed"]
    assert not by_id["closed-table"]["rights"]["index_allowed"]
    assert by_id["child"]["rights"]["index_allowed"]
    version = library.lib.record_version("S5", raw, "fulltext", {}, metadata, rights, "matched", spans, "jats-scoped-1.4.0")
    resolved = [library.lib.span(f"{version}:s{i:05d}") for i in range(len(spans))]
    assert any(library.lib.eligible(s)[0] for s in resolved)
    assert not library.lib.eligible(next(s for s in resolved if json.loads(s["locator_json"])["native_id"] == "main"))[0]
    child = next(s for s in resolved if json.loads(s["locator_json"])["native_id"] == "child")
    library.review_theory(THEORY, "0.1.0", reviewer="synthetic", rationale="Only licensed child evidence",
        applicability={"scope": "synthetic", "required": {}},
        evidence_links=[{"source_id": "S5", "source_version_id": version, "span_ids": [child["span_id"]]}],
        claims=[{"text": "Synthetic child statement.", "span_ids": [child["span_id"]], "support_rationale": "Synthetic exact child."}])
    assert library.release("component-only")["source_versions"][0]["version_id"] == version


@pytest.mark.parametrize("body", [
    '<permissions><copyright-statement>All rights reserved.</copyright-statement><license>CC BY 4.0</license></permissions>',
    '<permissions><license>CC BY 4.0</license><license>CC BY-NC-ND 4.0</license></permissions>',
    '<permissions><license>Figure only: CC BY 4.0</license></permissions>',
    '<permissions><license>Figure 1 only: CC BY 4.0</license></permissions>',
    '<permissions><license>CC BY 4.0. This license applies only to Table 2.</license></permissions>',
    '<permissions><license>CC BY 4.0 solely for supplementary material.</license></permissions>',
])
def test_r06_conflicting_or_scope_mismatched_article_grants_stay_pending(body):
    root = etree.fromstring(f"<article><front><article-meta>{body}</article-meta></front></article>")
    assert rights_from_xml(root)["index_allowed"] is False


def test_r05_revocation_cannot_be_laundered_through_temporary_disable(library):
    approve(library)
    library.theory_state(THEORY, "0.1.0", "revoked", actor="synthetic", rationale="Incorrect claim")
    with pytest.raises(ValueError, match="cannot be reset"):
        library.theory_state(THEORY, "0.1.0", "disabled", actor="synthetic", rationale="Attempted reset")
    with pytest.raises(ValueError, match="only a disabled"):
        library.theory_state(THEORY, "0.1.0", "activate", actor="synthetic", rationale="Attempted activation")


def test_r15_cached_span_cannot_bypass_a_new_source_notice(library):
    _, sid, _ = approve(library)
    cached_span = library.lib.span(sid)
    assert library.lib.eligible(cached_span)[0]
    library.lib.update_state("S5", "corrected_pending_review", "New notice after cached retrieval")
    assert library.lib.eligible(cached_span) == (False, "corrected_pending_review")


def test_r06_reparse_preserves_old_version_and_does_not_reapprove_theory(library):
    _, _, review = approve(library)
    doi = library.lib.source("S5")["manifest"]["doi"]
    title = escape(library.lib.source("S5")["manifest"]["title"])
    raw = f'''<article><front><article-meta><article-id pub-id-type="doi">{doi}</article-id>
<title-group><article-title>{title}</article-title></title-group>
<permissions><license>CC BY 4.0</license></permissions></article-meta></front>
<body><p id="p1">Synthetic licensed content.</p></body></article>'''.encode()
    metadata, spans, rights = parse_jats(raw)
    legacy_rights = {key: value for key, value in rights.items() if key != "scope_policy_version"}
    for span in spans:
        span.pop("rights")
    old = library.lib.record_version("S5", raw, "fulltext", {}, metadata, legacy_rights, "matched", spans)
    assert library.lib.eligible(library.lib.span(old + ":s00000")) == (False, "legacy_jats_scope_review_required")
    result = library.reparse_source_version(old)
    assert result["version_id"] != old and result["eligible_spans"] == 1
    assert library.lib.span(old + ":s00000") is not None
    stored = json.loads(library.lib.theories.execute("SELECT review_json FROM theory WHERE theory_id=?", (THEORY,)).fetchone()[0])
    assert stored["evidence_links"] == review["evidence_links"]
    assert result["theory_reviews_changed"] is False


def test_rag_related_statement_does_not_answer_an_unreviewed_target(library):
    approve(library)
    answer = library.query("合成方案增加重复次数能否证明个人寿命增长？", "progression")
    assert answer["status"] == "related_material_only"
    assert answer["related_materials"] and not answer["claims"] and not answer["citations"]
    assert "尚未建立" in answer["answer"]
    supported = library.query(QUESTION, "progression")
    assert supported["status"] == "evidence_supported"
    assert supported["claims"][0]["evidence_relation"] == "supports"
    changed_scope = {**TARGET, "scope": {"population": "synthetic_children", "time_scale": "lifelong"}}
    mismatch = library.query(QUESTION, "progression", context={"target_claims": [changed_scope]})
    assert mismatch["status"] == "related_material_only"


def test_rag_conflicting_relations_are_not_resolved_by_ranking(library):
    approve(library)
    approve(library, theory="TC-measurement-load-comparability", relation="refutes")
    answer = library.query(QUESTION, "progression")
    assert answer["status"] == "conflicting_evidence"
    assert not answer["claims"] and not answer["citations"]


def test_knowledge_page_labels_related_material_without_claiming_answer_support(library):
    from streamlit.testing.v1 import AppTest

    approve(library)
    app = AppTest.from_string(f'''from healthzip.knowledge import KnowledgeWorkbench
from healthzip.ui.knowledge_page import _render
w=KnowledgeWorkbench({str(library.root)!r})
try: _render(w)
finally: w.close()
''').run()
    app.selectbox[0].select("progression")
    app.text_input[0].set_value("合成方案增加重复次数能否证明个人寿命增长？")
    app.button[0].click().run()
    assert not app.exception
    assert any("missing_answer_relation" in x.value for x in app.caption)
    assert any("不等于当前问题已获支持" in x.label for x in app.expander)


def test_independent_annotation_requires_answer_and_exact_evidence_judgments(library):
    _, sid, _ = approve(library)
    output = library.query(QUESTION, "progression")
    annotation = {**annotation_identity("NEW-01", QUESTION, output),
        "reviewer": "Separate synthetic AI reviewer", "reviewer_kind": "independent_ai",
        "reviewed_at": "2026-11-11T00:00:00Z", "independent_of_implementation": True,
        "answer_judgment": {"decision": "pass", "addresses_target": True, "scope_correct": True,
                            "relation_supported": True, "rationale": "Synthetic source explicitly permits the stated option."},
        "evidence_judgments": [{"claim_index": 0, "span_id": sid,
            "source_version_id": output["citations"][0]["source_version_id"], "relation": "supports",
            "scope_matches": True, "rationale": "Exact synthetic source and target scope agree."}]}
    checked = validate_annotation(annotation, "NEW-01", QUESTION, output)
    assert checked["accepted"] and checked["ai_semantic_denominator_increment"] == 1
    assert checked["human_semantic_denominator_increment"] == 0
    for mutate in (lambda a: a.update(output_sha256="stale"),
                   lambda a: a.update(evidence_judgments=[]),
                   lambda a: a.update(independent_of_implementation=False),
                   lambda a: a["answer_judgment"].update(addresses_target=False)):
        invalid = deepcopy(annotation)
        mutate(invalid)
        assert not validate_annotation(invalid, "NEW-01", QUESTION, output)["accepted"]
