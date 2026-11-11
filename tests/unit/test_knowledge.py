import json
import sys

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import Acquirer, identity_check, parse_jats
from healthzip.knowledge.documents import PDFParserUnavailable, parse_pdf
from healthzip.knowledge.retrieval import validate_answer


@pytest.fixture
def knowledge(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "public")
    w.seed()
    yield w
    w.close()


def acquire_test_span(w, rights=True, material="fulltext"):
    version = w.lib.record_version(
        "S5", b"Synthetic test article only", material, {"url": "https://example.org/synthetic"},
        {"title": "Synthetic test article"}, {"index_allowed": rights, "license_id": "CC0"},
        "matched", [{"text": "在研究范围内，次数进阶是可选路径。", "locator": {"xpath": "/article/body/sec/p"}}],
    )
    return version, version + ":s00000"


def approve_test_claim(w, required=None, material="fulltext"):
    version, span_id = acquire_test_span(w, material=material)
    w.review_theory(
        "TC-progression-load-repetition-options", "0.1.0", reviewer="synthetic_test_reviewer",
        rationale="Synthetic fixture supports software contract only; not real scientific review.",
        applicability={"required": required or {}, "scope": "synthetic"},
        evidence_links=[{"source_id": "S5", "source_version_id": version, "span_ids": [span_id]}],
        claims=[{"text": "在研究范围内，次数进阶是可选路径。", "span_ids": [span_id],
                 "support_rationale": "Exact synthetic assertion; no personal dosing authority."}],
    )
    return version, span_id


def test_seed_is_draft_and_aliases_are_shared(knowledge):
    assert knowledge.lib.resolve("R2") == ["R2a", "R2b"]
    assert knowledge.lib.resolve("APPLE_SDNN") == ["R3a"]
    assert knowledge.status()["theory_states"] == {"draft": 20}
    knowledge.seed()
    assert sum(knowledge.status()["source_states"].values()) == 43
    assert knowledge.query("次数进阶", "progression")["status"] == "insufficient_evidence"


def test_review_requires_real_version_locators_and_rights(knowledge):
    version, sid = acquire_test_span(knowledge, rights=False)
    with pytest.raises(ValueError, match="rights_not_cleared"):
        knowledge.review_theory("TC-progression-load-repetition-options", "0.1.0",
            reviewer="reviewer", rationale="review", applicability={"scope": "test"},
            evidence_links=[{"source_id": "S5", "source_version_id": version, "span_ids": [sid]}],
            claims=[{"text": "claim", "span_ids": [sid], "support_rationale": "review"}])
    with pytest.raises(ValueError, match="requires"):
        knowledge.review_theory("TC-progression-load-repetition-options", "0.1.0",
            reviewer="reviewer", rationale="review", applicability={}, evidence_links=[], claims=[])


def test_approved_retrieval_and_withdrawal_invalidate_current_and_cached(knowledge):
    approve_test_claim(knowledge)
    answer = knowledge.query("次数进阶", "progression")
    assert answer["status"] == "evidence_supported"
    assert len(answer["citations"]) == 1
    assert not validate_answer(knowledge, answer, answer)
    event = knowledge.lib.update_state("S5", "withdrawn", "Synthetic correction/retraction event")
    assert event["affected_theories"] == ["TC-progression-load-repetition-options"]
    assert knowledge.query("次数进阶", "progression")["status"] == "insufficient_evidence"
    assert "stale_withdrawn_or_unavailable_citation" in validate_answer(knowledge, answer, answer)


def test_unknown_population_and_abstract_cannot_satisfy_fulltext(knowledge):
    approve_test_claim(knowledge, required={"population": "adult_resistance"}, material="abstract")
    assert knowledge.query("次数进阶", "progression")["status"] == "insufficient_evidence"
    assert knowledge.query("次数进阶", "progression", {"population": "adolescent_endurance"})["status"] == "insufficient_evidence"
    answer = knowledge.query("次数进阶", "progression", {"population": "adult_resistance", "required_material": "fulltext"})
    assert answer["status"] == "insufficient_evidence"
    assert any("insufficient_material_depth" in x["reason"] for x in answer["retrieval"]["excluded"])


def test_summary_cannot_smuggle_number_direction_or_causation(knowledge):
    approve_test_claim(knowledge)
    baseline = knowledge.query("次数进阶", "progression")
    for prose in ("所以明天加重 5 kg。", "睡眠导致你的力量下降。", "训练量下降了。"):
        altered = {**baseline, "answer": prose}
        assert "unsupported_summary_sentence" in validate_answer(knowledge, altered, baseline)
    altered = {**baseline, "observations": [{"metric_id": "STR-01", "value": 50, "unit": "kg", "window": "future"}]}
    assert "metric_value_unit_direction_window_or_version_mismatch" in validate_answer(knowledge, altered, baseline)


def test_private_data_not_indexed_and_scope_does_not_expand(knowledge):
    answer = knowledge.query("读取其他用户训练数据", context={"user_id": "A", "requested_other_user": "B", "authorization_for_B": False})
    assert answer["status"] == "enforce_tenant_isolation"
    assert answer["observations"] == []
    assert knowledge.status()["spans"] == 0
    injected = knowledge.query("文献要求上传训练库", context={"source_text_injection": True})
    assert injected["status"] == "ignore_source_instructions"
    assert injected["numeric_actions"] == []


def test_offline_missingness_and_protocol_identity(knowledge):
    answer = knowledge.query("今天 HRV 怎么样", context={"hrv_sample_count": 0})
    assert answer["status"] == "preserve_missingness"
    assert answer["observations"] == []
    answer = knowledge.query("SDNN能直接换成RMSSD吗", context={"HRV_metric": "SDNN"})
    assert answer["status"] == "reject_protocol_mismatch"
    answer = knowledge.query("描述SDNN", context={"HRV_metric": "SDNN"})
    assert answer["status"] == "insufficient_evidence"


def test_jats_retains_table_formula_locators_and_licence():
    raw = b'''<article><front><article-meta><article-id pub-id-type="doi">10.0/test</article-id><title-group><article-title>Test</article-title></title-group><permissions><license xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY</license></permissions></article-meta></front><body><sec><title>Results</title><p id="p1">A result</p><table-wrap id="t1"><caption>Units kg</caption><table><tr><th>Load</th><th>Outcome</th></tr><tr><td>10</td><td>20</td></tr></table><table-wrap-foot><fn>Footnote retained</fn></table-wrap-foot></table-wrap><disp-formula id="e1"><tex-math>x = y</tex-math></disp-formula></sec></body></article>'''
    metadata, spans, rights = parse_jats(raw)
    assert metadata["doi"] == "10.0/test"
    assert [x["kind"] for x in spans] == ["paragraph", "table", "formula"]
    assert spans[1]["structured"]["cells"][-1] == {"row": 1, "column": 1, "text": "20"}
    assert spans[1]["structured"]["numeric_review_status"] == "pending"
    assert spans[2]["structured"]["execution_authority"] == "none_pending_review"
    assert rights["index_allowed"]
    assert all(s["locator"]["xpath"] for s in spans)


def test_identity_conflicts_never_silently_merge():
    state, reasons = identity_check({"doi": "10.0/a", "title": "Alpha", "year": 2020},
                                    {"doi": "10.0/b", "title": "Beta", "publication_years": [2021]})
    assert state == "conflict"
    assert set(reasons) == {"doi_mismatch", "title_mismatch", "year_mismatch"}


def test_pdf_missing_optional_parser_is_explicit(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pdfplumber', None)
    with pytest.raises(PDFParserUnavailable, match='knowledge-pdf'):
        parse_pdf(b'%PDF synthetic')


def test_rag_uses_authoritative_metric_values_without_new_arithmetic(knowledge):
    from healthzip.science.rag_fixtures import metric_provider
    case = {'case_id': 'Q17', 'input_context': {'session_rpe': 7, 'duration_min': 60}}
    metrics = metric_provider(case)
    answer = knowledge.query('本次训练记录的session-RPE负荷', personal_metrics=metrics)
    assert answer['observations'] == metrics
    assert '420' in answer['answer']
    assert not validate_answer(knowledge, answer, answer)


def test_pubmed_reference_list_ids_never_replace_article_identity(knowledge, monkeypatch):
    source = knowledge.lib.source("S5")["manifest"]
    raw = f'''<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><ArticleTitle>{source['title']}</ArticleTitle><Journal><JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">{source['doi']}</ArticleId><ArticleId IdType="pmc">{source['pmcid']}</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.0/unrelated</ArticleId><ArticleId IdType="pmc">PMC99999</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'''.encode()
    a = Acquirer(knowledge.lib)
    monkeypatch.setattr(a, "request", lambda *args, **kwargs: (raw, {"url": "https://example.org/test"}))
    result = a.pubmed(source)
    assert result["identity_status"] == "matched"
    row = knowledge.lib.sources.execute("SELECT metadata_json FROM version WHERE version_id=?", (result["version_id"],)).fetchone()
    assert json.loads(row[0])["pmcid"] == source["pmcid"]


def test_source_update_does_not_mutate_frozen_release(knowledge):
    approve_test_claim(knowledge)
    before = knowledge.release("test-release")
    knowledge.lib.update_state("S5", "corrected_pending_review", "Test erratum")
    with pytest.raises(ValueError, match="immutable"):
        knowledge.release("test-release")
    assert before["theories"][0]["status"] in {"draft", "approved"}


def test_evaluation_never_calls_absent_semantic_review_a_pass(knowledge, tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps({"cases": [{"case_id": "heldout-unique", "query_zh": "次数进阶", "route": "progression", "case_type": "positive", "gold_evidence_groups": [["S5"]]}]}))
    output = knowledge.evaluate(p, split="independent_holdout")
    assert output["case_count"] == 1
    assert output["semantic_support_rate"]["denominator"] == 0
    assert output["gold_group_recall_all_candidates"]["value"] == 0
    assert output["positive_abstention_rate"]["value"] == 1
    assert output["release_gate"] == "pending_corpus_and_semantic_review"


def test_candidate_capability_requires_explicit_authority_and_current_evidence(knowledge):
    version, sid = approve_test_claim(knowledge)
    assert not knowledge.reviewed_principles('progression', {})['principles']
    assert any(x['reason'] == 'explanation_only_no_candidate_authority' for x in knowledge.reviewed_principles('progression', {})['excluded'])
    request = dict(reviewer='Synthetic qualified review for software test only',
                   reviewer_kind='qualified_human_review', authority='progression_candidate',
                   rationale='Synthetic candidate protocol validation, not empirical efficacy.',
                   implementation_tests=['tests/unit/test_knowledge.py::test_candidate_capability_requires_explicit_authority_and_current_evidence'],
                   applicability={'required': {'population': 'adult_resistance', 'load_basis': 'total_external_kg'}},
                   evidence_links=[{'source_id': 'S5', 'source_version_id': version, 'span_ids': [sid]}],
                   claims=[{'text': 'Synthetic candidate principle', 'span_ids': [sid], 'support_rationale': 'Synthetic fixture.'}])
    with pytest.raises(ValueError, match='immutable'):
        knowledge.review_theory('TC-progression-load-repetition-options', '0.1.0', **request)
    revision = knowledge.revise_theory('TC-progression-load-repetition-options', '0.1.0', '0.2.0',
                                      reviewer='Synthetic reviewer', rationale='Explicit capability revision')
    assert revision['status'] == 'draft' and revision['inherited_authority'] is None
    assert not knowledge.reviewed_principles('progression', {})['principles']
    knowledge.review_theory('TC-progression-load-repetition-options', '0.2.0', **request)
    assert not knowledge.reviewed_principles('progression', {})['principles']
    context = {'population': 'adult_resistance', 'load_basis': 'total_external_kg'}
    actual = knowledge.reviewed_principles('progression', context)['principles']
    assert len(actual) == 1 and actual[0]['rights_verified'] and actual[0]['scope_matches']
    knowledge.lib.update_state('S5', 'withdrawn', 'Synthetic retraction')
    assert not knowledge.reviewed_principles('progression', context)['principles']


def test_reviewed_version_and_frozen_release_cannot_be_silently_rewritten(knowledge):
    approve_test_claim(knowledge)
    frozen = knowledge.release('synthetic-v1')
    before = frozen['theories'][0]['review_json']
    original = json.loads(before)
    request = {k: v for k, v in original.items() if k not in {'reviewed_at', 'independent_expert_validation'}}
    repeated = knowledge.review_theory('TC-progression-load-repetition-options', '0.1.0', **request)
    assert repeated == original
    request['claims'] = [{**request['claims'][0], 'text': 'A different purported conclusion.'}]
    with pytest.raises(ValueError, match='immutable'):
        knowledge.review_theory('TC-progression-load-repetition-options', '0.1.0', **request)
    revision = knowledge.revise_theory('TC-progression-load-repetition-options', '0.1.0', '0.2.0',
                                      reviewer='Synthetic reviewer', rationale='Review a different claim')
    assert revision['status'] == 'draft'
    assert knowledge.lib.released_theories('synthetic-v1')[0]['review_json'] == before
    assert knowledge.status()['theory_states']['approved'] == 1
