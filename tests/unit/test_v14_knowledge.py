"""v1.4 knowledge contracts: synthetic sources, no real approval fixtures."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import Acquirer, parse_jats
from healthzip.knowledge.core import POLICY
from healthzip.knowledge.rights import PARSER_VERSION
from healthzip.knowledge.store import identity

QUESTION = "合成方案是否允许增加重复次数？"
TARGET = {"proposition": "合成方案允许增加重复次数", "scope": {"population": "synthetic_adults", "time_scale": "protocol"}}


@pytest.fixture
def kb(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    yield w
    w.close()


def approved(w, theory="TC-progression-load-repetition-options", relation="supports", version="0.1.0"):
    raw = ("Synthetic adult protocol " + relation + " repetition progression; longevity was not measured.").encode()
    vid = w.lib.record_version("S5", raw, "fulltext", {}, {}, {"index_allowed": True, "license_id": "CC0"}, "matched",
                               [{"text": raw.decode(), "locator": {"synthetic_line": 1}}], "synthetic-v14")
    sid = vid + ":s00000"
    w.review_theory(theory, version, reviewer="Synthetic fixture", reviewer_kind="synthetic_fixture", rationale="Software fixture only",
        applicability={"required": {}, "scope": "synthetic"}, evidence_links=[{"source_id": "S5", "source_version_id": vid, "span_ids": [sid]}],
        claims=[{"text": "合成方案增加重复次数。", "span_ids": [sid], "support_rationale": "Invented assertion",
                 "answer_bindings": [{"question": QUESTION, "target_claim": TARGET, "relation": relation, "rationale": "Synthetic relation"}]}])
    return vid, sid


def test_f10_conflicts_cannot_be_hidden_by_display_budget(kb):
    cards = [{"theory_id": f"SYNTH-{i}", "version": "0.1.0", "title": QUESTION, "domains": ["progression"]} for i in range(7)]
    kb.lib.seed({"sources": []}, {"cards": cards})
    for i in range(7):
        approved(kb, f"SYNTH-{i}", "supports" if i < 6 else "refutes")
    for budget in (1, 6, 7):
        result = kb.query(QUESTION, "progression", k=budget)
        assert result["status"] == "conflicting_evidence"
        assert result["support_assessment"]["conflict_screen"]["eligible_theories_checked"] == 7
        assert len(result["retrieval"]["candidates"]) == budget
        assert not result["claims"]


@pytest.mark.parametrize("article_open,child_open", [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize("container", ["p", "table-wrap"])
def test_f11_every_serialized_evidence_unit_respects_component_ownership(kb, article_open, child_open, container):
    def grant(allowed):
        return "<license>CC BY 4.0</license>" if allowed else "<copyright-statement>All rights reserved.</copyright-statement>"
    raw = f'''<article><front><article-meta><permissions>{grant(article_open)}</permissions></article-meta></front>
<body><{container} id="parent">PARENT_MARKER<fig id="child"><caption><p>CHILD_MARKER</p></caption>
<permissions>{grant(child_open)}</permissions></fig>PARENT_TAIL</{container}></body></article>'''.encode()
    metadata, spans, rights = parse_jats(raw)
    vid = kb.lib.record_version("S5", raw, "fulltext", {}, metadata, rights, "matched", spans, PARSER_VERSION)
    active = [s for i, s in enumerate(spans) if kb.lib.eligible(kb.lib.span(vid + f":s{i:05d}"))[0]]
    assert any("PARENT_MARKER" in s["text"] for s in active) == article_open
    assert any("CHILD_MARKER" in s["text"] for s in active) == child_open
    if not child_open:
        assert "CHILD_MARKER" not in json.dumps(active)
    parent = next(s for s in spans if s["locator"]["native_id"] == "parent")
    assert "CHILD_MARKER" not in json.dumps(parent)
    assert "PARENT_TAIL" in parent["text"]


def test_f12_identical_provider_notice_is_idempotent_but_changed_content_invalidates(kb):
    vid, sid = approved(kb)
    source = kb.lib.source("S5")["manifest"]
    from xml.sax.saxutils import escape
    def raw(correction):
        return f'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{source['pmid']}</PMID><Article>
<ArticleTitle>{escape(source['title'])}</ArticleTitle><Journal><JournalIssue><PubDate><Year>{source['year']}</Year></PubDate></JournalIssue></Journal></Article>
<CommentsCorrectionsList><CommentsCorrections RefType="ErratumIn"><RefSource>{correction}</RefSource><PMID>9999</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">{source['doi']}</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''.encode()
    acquirer = Acquirer(kb.lib)
    acquirer.request = lambda *a, **k: (raw("One notice"), {"url": "synthetic"})
    acquirer.pubmed(source)
    kb.review_source_state("S5", reviewer="synthetic", rationale="Exact notice and version checked", source_version_ids=[vid])
    kb.revise_theory("TC-progression-load-repetition-options", "0.1.0", "0.2.0", reviewer="synthetic", rationale="Explicit re-review")
    approved(kb, version="0.2.0")
    epoch = kb.lib.source("S5")["scientific_epoch"]
    acquirer.pubmed(source)
    assert kb.lib.source("S5")["scientific_epoch"] == epoch
    assert kb.lib.eligible(kb.lib.span(sid))[0]
    assert kb.query(QUESTION, "progression")["status"] == "evidence_supported"
    acquirer.request = lambda *a, **k: (raw("Changed substantive notice"), {"url": "synthetic"})
    acquirer.pubmed(source)
    assert kb.lib.source("S5")["scientific_epoch"] == epoch + 1
    assert not kb.lib.eligible(kb.lib.span(sid))[0]


def core_claim(w, outcome="progression_options", text="合成成人方案允许增加次数；没有个人效果保证。", relation="supports", *, scope=None, claim_id=None):
    raw = text.encode()
    vid = w.lib.record_version("S5", raw, "fulltext", {}, {}, {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "locator": {"synthetic_line": 1}}], "synthetic-core-v14")
    sid = vid + ":s00000"
    requested = "individual_inference" if outcome in {"longevity", "personal_temperature"} else "options"
    claim = {"claim_id": claim_id or "CLAIM-" + outcome, "version": "1", "statement": text,
        "scope": scope or {"population": "synthetic_adults", "time_scale": "protocol"}, "limitations": ["Synthetic only"],
        "evidence_links": [{"source_id": "S5", "source_version_id": vid, "span_ids": [sid]}],
        "answer_task": {"subject": "device_measurement" if outcome == "personal_temperature" else "resistance_training",
            "outcome": outcome, "requested_relation": requested, "evidence_relation": relation, "answer_complete": True,
            "answer_parts": [{"text": text, "span_ids": [sid]}]}}
    review = {"reviewer": "Synthetic implementing fixture", "reviewer_kind": "synthetic_fixture", "reviewed_at": "2026-11-11T00:00:00Z", "rationale": "Exact invented statement", "content_checked": True}
    w.review_claim(claim, review)
    return claim


def test_normalized_tasks_answer_new_expressions_and_explicit_unmeasured_boundaries(kb):
    core_claim(kb)
    for query in ("训练时可不可以多做一些重复？", "Is increasing repetitions allowed in this training protocol?", "这个方案能增加次数吗"):
        answer = kb.query(query, "progression")
        assert answer["answer_status"] == "answered_with_support"
        assert "允许增加次数" in answer["answer"]
    core_claim(kb, "longevity", "该合成训练没有测量寿命，因此不能据此证明个人寿命增加；这也不证明没有效应。", "refutes")
    core_claim(kb, "personal_temperature", "温度计试验没有测量明日个人体温，不能确定你的明日绝对体温。", "refutes")
    assert "不能据此证明" in kb.query("多做重复能让我活得更久吗？", "progression")["answer"]
    assert "不能确定" in kb.query("温度计研究可以预测我明天的体温吗？", "energy")["answer"]
    # A supported scope limitation can fully answer a question; completeness is
    # separate from whether the source gives an unconditional positive assertion.
    assert kb.query("方案增加次数能证明寿命增长？", "progression")["answer_status"] == "answered_with_support"


def core_rule(kb):
    claim = core_claim(kb)
    rule = {"rule_id": "SYNTH-RULE", "rule_version": "1", "requested_capability": "plan_candidate",
        "permitted_actions": ["double_progression"],
        "capability_policy_version": POLICY["version"], "claim_refs": [{"claim_id": claim["claim_id"], "version": "1"}],
        "conditions": [{"field": "age", "op": "range", "min": 18, "origin": "source_scope"},
                       {"field": "training_goal", "op": "eq", "value": "strength", "origin": "user_plan"}],
        "application_logic": "Synthetic bounded task; source does not predict success.", "limits": ["No causal guarantee"],
        "exit_conditions": ["user stops"], "followup": "Observe actual execution", "numeric_provenance": {"load": "equipment_constraint"},
        "implementation_validation_refs": ["tests/unit/test_v14_knowledge.py"]}
    review = {"reviewer": "Synthetic implementing fixture", "reviewer_kind": "synthetic_fixture", "reviewed_at": "2026-11-11T00:00:00Z", "rationale": "Synthetic contract check", "application_checked": True}
    kb.review_rule(rule, review)
    return claim, rule, review


def test_core_rule_requires_real_claim_context_and_truthful_review(kb):
    kb.seed_core()
    _, rule, review = core_rule(kb)
    context = {"age": 25, "training_goal": "strength"}
    result = kb.reviewed_principles("progression", context)
    assert result["principles"][0]["rule_id"] == "SYNTH-RULE"
    assert result["principles"][0]["reviewer_kind"] == "synthetic_fixture"
    assert not result["principles"][0]["independent_expert_validation"]
    assert not kb.reviewed_principles("progression", {"training_goal": "strength"})["principles"]
    assert not kb.reviewed_principles("progression", {"age": 17, "training_goal": "strength"})["principles"]
    kb.environment_kind = "production"
    assert not kb.reviewed_principles("progression", context)["principles"]
    wrong = deepcopy(review)
    wrong.update(reviewer_kind="ai_assisted", independent_expert_validation=True)
    with pytest.raises(ValueError, match="AI cannot claim"):
        kb.review_rule({**rule, "rule_version": "2"}, wrong)


def test_core_release_history_is_immutable_but_current_claim_revocation_blocks_use(kb):
    from healthzip.knowledge.retrieval import validate_answer
    claim, rule, review = core_rule(kb)
    context = {"age": 25, "training_goal": "strength"}
    frozen = kb.release_core("synthetic-release-1")
    old_answer = kb.query("训练方案允许增加次数吗？", "progression")
    old_payload = kb.lib.theories.execute("SELECT payload_json FROM source_claim WHERE claim_id=?", (claim["claim_id"],)).fetchone()[0]
    assert kb.reviewed_principles("progression", context, release_id="synthetic-release-1")["principles"]
    kb.review_rule({**rule, "rule_version": "2", "supersedes": "1"}, review)
    assert not kb.reviewed_principles("progression", context, release_id="synthetic-release-1")["principles"]
    assert kb.reviewed_principles("progression", context)["principles"][0]["version"] == "2"
    assert json.loads(kb.lib.theories.execute("SELECT manifest_json FROM core_release WHERE release_id='synthetic-release-1'").fetchone()[0])["rules"] == frozen["rules"]
    with pytest.raises(ValueError, match="immutable"):
        kb.release_core("synthetic-release-1")
    kb.core_state("claim", claim["claim_id"], "1", "revoked", actor="Synthetic fixture", rationale="Invented content withdrawn")
    assert kb.lib.theories.execute("SELECT payload_json FROM source_claim WHERE claim_id=?", (claim["claim_id"],)).fetchone()[0] == old_payload
    assert not kb.reviewed_principles("progression", context)["principles"]
    assert validate_answer(kb, old_answer, old_answer)
    assert not kb.query("训练方案允许增加次数吗？", "progression")["citations"]
    assert kb.core_status()["effective_rule_count"] == 0


def test_core_source_correction_invalidates_current_rule_without_changing_review(kb):
    _, _, _ = core_rule(kb)
    before = kb.lib.theories.execute("SELECT review_json FROM application_rule WHERE rule_id='SYNTH-RULE'").fetchone()[0]
    kb.lib.update_state("S5", "corrected_pending_review", "Synthetic source correction")
    assert not kb.reviewed_principles("progression", {"age": 25, "training_goal": "strength"})["principles"]
    assert kb.lib.theories.execute("SELECT review_json FROM application_rule WHERE rule_id='SYNTH-RULE'").fetchone()[0] == before


def test_core_seed_books_aliases_partitions_and_unread_rules_do_not_activate(kb):
    before = kb.lib.sources.execute("SELECT COUNT(*) FROM version WHERE source_id='S1'").fetchone()[0]
    status = kb.seed_core()
    assert status["distinct_rule_count"] == 21 and status["effective_rule_count"] == 0
    assert kb.lib.source("CORE-ACSM-RT-2026")["source_id"] == "S1"
    assert kb.lib.sources.execute("SELECT COUNT(*) FROM version WHERE source_id='S1'").fetchone()[0] == before
    assert identity({"manifestation_id": "textbook-ed4-zh"}) != identity({"manifestation_id": "textbook-ed5-en"})
    assert not kb.reviewed_principles("progression", {})["principles"]
    assert all(c["payload_json"].find("missing_source_content") >= 0 for c in status["chapter_coverage"])


def test_catalog_and_interface_text_cannot_authorize_source_claims(kb):
    kb.seed_core()
    with kb.lib.sources:
        source = kb.lib.source("S5")["manifest"]
        source["corpus_roles"] = ["catalog"]
        kb.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id='S5'", (json.dumps(source),))
    with pytest.raises(ValueError, match="catalog/interface"):
        core_claim(kb)


def test_authorized_partial_chapter_keeps_prose_but_blocks_table_parameters(kb):
    pytest.importorskip("pdfplumber")
    kb.lib.seed({"sources": [{"source_id": "SYNTH-BOOK", "manifestation_id": "synthetic-en-ed5", "edition_id": "synthetic-ed5",
        "title": "Synthetic evidence only", "corpus_roles": ["core"], "source_kind": "professional_textbook"}]}, {"cards": []})
    result = kb.import_chapter("SYNTH-BOOK", Path(__file__).parents[1] / "fixtures/synthetic_knowledge.pdf",
        edition_id="synthetic-ed5", chapter_id="1", page_indices=[0], expected_page_indices=[0, 1],
        license_id="CC0-synthetic", rights_evidence_url="https://example.test/synthetic", authorized_by="Synthetic fixture",
        identity_review={"decision": "matched", "reviewer": "Synthetic fixture", "rationale": "Invented book identity"},
        missing_footnote_ids=["f1"])
    assert result["status"] == "partial_chapter" and result["missing_pages"] == [1]
    spans = [kb.lib.span(sid) for sid in result["span_ids"]]
    table = next(s for s in spans if s["kind"] == "table")
    paragraph = next(s for s in spans if s["kind"] == "paragraph" and not json.loads(s["structured_json"]).get("table_overlap_indices"))
    table_line = next(s for s in spans if s["kind"] == "paragraph" and json.loads(s["structured_json"]).get("table_overlap_indices"))
    from healthzip.knowledge.core import _spans
    def link(span):
        return [{"source_id": "SYNTH-BOOK", "source_version_id": result["version_id"], "span_ids": [span["span_id"]]}]
    assert _spans(kb, link(paragraph), numeric=True)
    with pytest.raises(ValueError, match="footnotes"):
        _spans(kb, link(table), numeric=True)
    with pytest.raises(ValueError, match="footnotes"):
        _spans(kb, link(table_line), numeric=True)
    assert json.loads(table["locator_json"])["printed_page_label"] is None


def test_qal_adapter_uses_sufficient_paths_and_keeps_unjudged_semantics_unknown(kb):
    from healthzip.knowledge.quality import run_quality
    from healthzip.science.evaluation import sufficient_recall
    core_claim(kb)
    output = kb.query("训练方案允许增加次数吗？", "progression")
    result = run_quality(kb, [{"case_id": "q", "question": "训练方案允许增加次数吗？", "output": output,
        "gold_review_status": "approved", "gold_groups": {"A": [["S5"]], "B": [["missing"]], "C": [["S5"]]},
        "sufficient_bundles": [["A", "B"], ["C"]]}])
    metrics = {m["metric_id"]: m["value"] for m in result["metrics"]}
    assert metrics["QAL-01"]["queries"][0]["sufficient_bundle_hit"]
    assert metrics["QAL-03"]["support_precision"]["rate"] is None
    assert result["annotation_counts"] == {"independent_human": 0, "independent_ai": 0}
    assert not sufficient_recall({"gold_groups": {"A": [["a", "b"]]}, "sufficient_bundles": [["A"]], "retrieved_unit_ids": ["a"]})["sufficient_bundle_hit"]


def test_qal_incomplete_trace_is_an_observed_lower_bound():
    from healthzip.science import evaluate
    result = evaluate("QAL-08", [], cutoff_time="2026-11-11T00:00:00Z", window_start="2026-11-10T00:00:00Z", window_end="2026-11-11T00:00:00Z",
        context={"requests": [{"request_id": "seen", "eligible": True, "trace_complete": True, "fallback_events": []},
                              {"request_id": "unknown", "eligible": True, "trace_complete": False}]})["value"]
    assert result["fallback_rate_kind"] == "observed_lower_bound_incomplete_trace"
    assert result["fallback_requests"]["rate"] == 0 and result["fallback_upper_bound"]["rate"] == .5


def test_time_modifier_never_becomes_frequency_target_and_ambiguous_goals_need_confirmation(kb):
    core_claim(kb)
    core_claim(kb, "volume", "合成组量解释，不给个人精确组数。")
    assert kb.query("每周这个训练方案可以增加次数吗？", "progression")["answer_status"] == "answered_with_support"
    unknown = kb.query("每周这个训练怎么样？", "progression")
    assert not unknown["claims"] and unknown["retrieval"]["question_contract"]["outcome"] is None
    ambiguous = kb.query("训练组数和频率如何安排？", "progression")
    assert ambiguous["status"] != "evidence_supported"
    assert "multiple_possible_outcomes" in ambiguous["retrieval"]["question_contract"]["issues"]
    narrowed = kb.query("训练组数和频率如何安排？", "progression", context={"question_contract": {
        "subject": "resistance_training", "outcome": "volume", "requested_relation": "options", "user_confirmed": True}})
    assert narrowed["answer_status"] == "answered_with_support" and "组量解释" in narrowed["answer"]
    child = kb.query("儿童训练组数如何安排？", "progression", context={"question_contract": {
        "subject": "resistance_training", "outcome": "volume", "requested_relation": "options", "user_confirmed": True}})
    assert child["status"] != "evidence_supported" and not child["citations"]


def test_specific_source_edition_and_chapter_constraints_cannot_be_replaced_by_related_paper(kb):
    core_claim(kb)
    missing_book = kb.query("依据教材第3版第8章，方案可以增加次数吗？", "progression")
    assert not missing_book["claims"] and "其他文献不能替代" in missing_book["answer"]
    for constraint in ({"source_ids": ["S1"]}, {"source_ids": ["S5"], "edition_id": "unheld-edition"},
                       {"source_ids": ["S5"], "chapter_id": "unheld-chapter"}):
        result = kb.query("训练方案可以增加次数吗？", "progression", context={"source_constraints": constraint})
        assert result["status"] != "evidence_supported" and not result["citations"]
    available = kb.query("根据S5，训练方案可以增加次数吗？", "progression")
    assert available["answer_status"] == "answered_with_support"
    for question in ("根据 S5 第三版第八章，训练方案可以增加次数吗？", "根据 S5，训练方案可以增加次数吗，并给出页码？",
                     "依据《尚未取得的材料》，训练方案可以增加次数吗？", "According to UnheldJournal, is training repetition progression allowed?",
                     "According to S5 3rd edition chapter 8, is training repetition progression allowed?"):
        assert not kb.query(question, "progression")["citations"]


def test_compound_personal_numeric_request_cannot_be_declared_fully_answered(kb):
    core_claim(kb)
    answer = kb.query("训练方案允许增加次数吗，再计算我应该加多少公斤？", "progression")
    assert answer["answer_status"] == "partially_answered"
    assert answer["claims"] and not answer["numeric_actions"]
    assert "复合目标" in answer["answer"]


def test_composed_answer_requires_every_requested_part_and_every_rendered_part(kb):
    core_claim(kb, "volume", "合成组量取决于任务，没有个人最优组数。")
    question = "请分别说明训练组数与频率的依据。"
    partial = kb.query(question, "progression")
    assert partial["answer_status"] == "partially_answered"
    assert partial["claims"]
    assert {p["part_id"] for p in partial["support_assessment"]["uncovered_parts"]} == {"frequency"}
    core_claim(kb, "frequency", "合成频率取决于任务，没有个人最优天数。")
    complete = kb.query(question, "progression")
    assert complete["answer_status"] == "answered_with_support"
    assert {p["part_id"] for p in complete["support_assessment"]["covered_parts"]} == {"volume", "frequency"}
    limited = kb.query(question, "progression", k=1)
    assert limited["answer_status"] == "partially_answered"
    assert len(limited["support_assessment"]["uncovered_parts"]) == 1
    assert limited["support_assessment"]["uncovered_parts"][0]["reason"] == "display_budget_omitted_supported_part"


def test_domain_route_and_word_boundaries_do_not_invent_answer_targets(kb):
    core_claim(kb, "frequency", "合成频率说明。")
    assert kb.query("How often?", "strength")["answer_status"] == "answered_with_support"
    core_claim(kb, "volume", "合成组数说明。")
    unrelated = kb.query("Are training datasets anonymized?", "strength")
    assert not unrelated["claims"]
    assert unrelated["retrieval"]["question_contract"]["outcome"] is None


def test_question_goal_requires_matching_reviewed_goal_and_combination_is_complete(kb):
    core_claim(kb, "rest", "合成力量任务的休息说明。", scope={"population": "synthetic", "goal": "strength"})
    question = "组间休息对力量收益与肌肥大有什么依据？"
    partial = kb.query(question, "strength")
    assert partial["answer_status"] == "partially_answered"
    assert [p["part_id"] for p in partial["support_assessment"]["uncovered_parts"]] == ["rest:hypertrophy"]
    assert not kb.query("增肌的组间休息有什么依据？", "strength")["claims"]
    narrowed = kb.query("增肌的组间休息有什么依据？", "strength", context={"question_contract": {
        "subject": "resistance_training", "outcome": "rest", "requested_relation": "options", "user_confirmed": True}})
    assert not narrowed["claims"]
    core_claim(kb, "rest", "合成肌肥大任务的休息证据不足。", scope={"population": "synthetic", "goal": "hypertrophy"}, claim_id="CLAIM-REST-GROWTH")
    complete = kb.query(question, "strength")
    assert complete["answer_status"] == "answered_with_support"
    assert len(complete["claims"]) == 2
    ordinary_comparison = kb.query("力量与增肌的休息依据有何不同？", "strength")
    assert {p["requested_goal"] for p in ordinary_comparison["support_assessment"]["covered_parts"]} == {"strength", "hypertrophy"}


def test_registered_source_title_is_resolved_without_substituting_another_work(kb):
    core_claim(kb)
    title = kb.lib.source("S5")["manifest"]["title"]
    answer = kb.query(f"根据《{title}》，方案能增加次数吗？", "progression")
    assert answer["answer_status"] == "answered_with_support"
    assert answer["retrieval"]["question_contract"]["source_constraints"]["source_ids"] == ["S5"]


def test_unconfirmed_structured_target_does_not_remove_personal_numeric_request(kb):
    core_claim(kb)
    result = kb.query("可以增加次数吗，再计算我该加多少公斤？", "progression", context={"question_contract": {
        "subject": "resistance_training", "outcome": "progression_options", "requested_relation": "options"}})
    assert result["answer_status"] == "partially_answered"
    assert result["support_assessment"]["uncovered_parts"][0]["part_id"] == "personal_numeric_request"


@pytest.mark.parametrize("question,outcome,missing", [
    ("我的训练休息多久最好？", "rest", "personal_numeric_request"),
    ("How many sets should I do?", "volume", "personal_numeric_request"),
    ("Compare the 2011 and 2024 guidelines on training volume.", "volume", "source_comparison"),
    ("两个版本的训练组数建议有哪些区别？", "volume", "source_comparison"),
])
def test_unreviewed_personal_parameter_or_source_comparison_cannot_be_complete(kb, question, outcome, missing):
    core_claim(kb, outcome, "合成一般解释；不提供个人最优参数或两个版本对照。")
    result = kb.query(question, "strength")
    assert result["answer_status"] == "partially_answered"
    assert missing in {p["part_id"] for p in result["support_assessment"]["uncovered_parts"]}


def test_between_sets_is_a_rest_modifier_not_a_request_for_training_volume(kb):
    core_claim(kb, "rest", "合成休息解释。")
    core_claim(kb, "volume", "合成组量解释。")
    result = kb.query("Explain rest between sets, then choose exactly 90 seconds for my session.", "strength")
    assert result["answer_status"] == "partially_answered"
    assert {c["theory_id"] for c in result["claims"]} == {"CLAIM-rest"}
    assert result["retrieval"]["question_contract"]["possible_outcomes"] == ["rest"]


@pytest.mark.parametrize("relations,scopes,accepted", [
    (["supports", "qualifies"], [True, True], True),
    (["qualifies", "qualifies"], [True, True], False),
    (["supports", "refutes"], [True, True], False),
    (["supports", "qualifies"], [True, False], False),
])
def test_evidence_bundle_qualifiers_preserve_scope_without_fabricating_direct_support(relations, scopes, accepted):
    from healthzip.knowledge.adjudication import annotation_identity, validate_annotation
    output = {"claims": [{"theory_id": "s", "theory_version": "1", "span_ids": ["a", "b"], "evidence_relation": "supports"}],
        "citations": [{"theory_id": "s", "theory_version": "1", "span_ids": ["a", "b"], "source_version_id": "v"}],
        "evidence_bundle_hash": "synthetic"}
    annotation = {**annotation_identity("synthetic", "q", output), "reviewer_kind": "synthetic_fixture", "reviewer": "Invented fixture",
        "reviewed_at": "2026-11-11T00:00:00Z", "answer_judgment": {"decision": "pass", "rationale": "synthetic",
        "addresses_target": True, "scope_correct": True, "relation_supported": True},
        "evidence_judgments": [{"claim_index": 0, "span_id": sid, "source_version_id": "v", "relation": relation,
            "scope_matches": scope, "rationale": "Synthetic relation"} for sid, relation, scope in zip(["a", "b"], relations, scopes)]}
    assert validate_annotation(annotation, "synthetic", "q", output)["accepted"] is accepted


def test_knowledge_ui_requires_target_confirmation_before_using_structured_selection(kb):
    from streamlit.testing.v1 import AppTest
    core_claim(kb)
    app = AppTest.from_string(f'''from healthzip.knowledge import KnowledgeWorkbench
from healthzip.ui.knowledge_page import _render
w=KnowledgeWorkbench({str(kb.root)!r}, environment_kind="synthetic_test")
try: _render(w)
finally: w.close()
''').run()
    app.text_input[0].set_value("请解释我说的那种做法。")
    app.checkbox(key="knowledge_explicit_target").check().run()
    app.button[0].click().run()
    assert not app.exception
    assert not any("answered_with_support" in c.value for c in app.caption)
    app.checkbox(key="knowledge_target_confirmed").check().run()
    app.button[0].click().run()
    assert not app.exception
    assert any("answered_with_support" in c.value for c in app.caption)
