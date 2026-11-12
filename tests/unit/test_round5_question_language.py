"""Development regressions after round5; these are not independent QA scores."""

import json

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.question_parts import RELATIONS
from healthzip.knowledge.tasks import parse_task


def parts(question, context=None):
    return parse_task(question, context)["required_answer_parts"]


def outcomes(question, context=None):
    return {p["outcome"] for p in parts(question, context) if p.get("outcome")}


@pytest.mark.parametrize("question", [
    "回归研究中一组误差独立，另一组前后相关。HC和HAC分别处理哪些情形？",
    "HC2和HC3的小样本表现有什么区别？",
    "回归已拟合。报告区间之前还需要检查误差吗？请结合HC和HAC解释。",
    "只有很短的训练序列，用了HAC就能保证区间覆盖率吗？",
])
def test_covariance_context_survives_clause_boundaries_and_estimator_versions(question):
    assert outcomes(question) == {"regression_covariance_scope"}
    assert not any(p.get("reason") for p in parts(question))
    assert parts(question)[0]["subject"] == "statistical_inference"


@pytest.mark.parametrize("question,expected", [
    ("做TOST时只有一个单侧检验拒绝，可以判等效吗？", {"equivalence_test_logic"}),
    ("TOST的整体P值应选两个单侧P值中的哪个？", {"equivalence_test_logic"}),
    ("用TOST时显著性水平与置信区间水平如何对应？区间跨过一侧界值怎么办？", {"equivalence_test_logic"}),
    ("等效检验的平行组示例能直接用于同一个人反复测量吗？", {"equivalence_design_scope"}),
    ("力竭具体指什么？每组必须练到那个程度吗？足够努力该怎样理解？", {"failure_definition", "failure_necessity", "effort_precision"}),
    ("增加负荷后次数下降，训练特异性原则怎样解释？", {"load_repetition_relation", "comparability"}),
    ("换成另一品牌的训练机，能直接换算成多少公斤吗？", {"comparability"}),
    ("多做一组之后1RM提高，能确认就是这一组对我有效吗？", {"individual_effect"}),
])
def test_method_and_training_targets_use_grammatical_families(question, expected):
    assert outcomes(question) == expected


@pytest.mark.parametrize("question", [
    "我想在研究中用通用效应量作为等效界值，这个选择有什么方法学问题？",
    "我准备比较两个干预，界值应依据什么确定？",
    "Please explain how equivalence margins should be chosen for a study.",
    "请解释研究中应该依据什么确定等效界值。",
])
def test_describing_a_study_plan_is_not_a_request_to_calculate_personal_bounds(question):
    assert "statistical_calculation" not in {p["part_id"] for p in parts(question)}


@pytest.mark.parametrize("question", [
    "请给我的训练数据选择等效界值。",
    "请计算连续训练的个人误判率。",
    "请算出以后每次加一组对我的成功概率。",
])
def test_personal_statistical_actions_remain_unanswered_targets(question):
    assert "statistical_calculation" in {p["part_id"] for p in parts(question)}


@pytest.mark.parametrize("question", [
    "HC0俱乐部的样本标签在哪里下载？",
    "The HC and HAC clubs have different names. Explain their workout rest intervals.",
    "我需要在新机器上换算文件大小。",
    "TOST文件夹里的两个图形大小相同吗？",
])
def test_acronyms_machine_names_and_equality_do_not_supply_statistical_authority(question):
    targets = parts(question)
    assert not any(p.get("subject") == "statistical_inference" for p in targets)
    assert "comparability" not in {p.get("outcome") for p in targets}


@pytest.fixture
def kb(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "kb", environment_kind="synthetic_test")
    w.seed()
    yield w
    w.close()


def add_claim(w, outcome, subject, *, source_id="S5", scope=None):
    text = "Synthetic explanation for " + outcome
    vid = w.lib.record_version(source_id, text.encode(), "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "locator": {"chapter_id": "4"}}], "synthetic-round5")
    sid = vid + ":s00000"
    w.review_claim({"claim_id": source_id + "-" + outcome, "version": "1", "statement": text,
        "scope": scope or {"population": "adults"}, "limitations": ["Synthetic fixture only"],
        "evidence_links": [{"source_id": source_id, "source_version_id": vid, "span_ids": [sid]}],
        "answer_task": {"subject": subject, "outcome": outcome,
            "requested_relation": RELATIONS[outcome], "answer_complete": True,
            "answer_parts": [{"text": text, "span_ids": [sid]}]}},
        {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture",
         "rationale": "Software check, no scientific authority", "reviewed_at": "2026-11-12",
         "content_checked": True})


def update_source(w, **fields):
    manifest = w.lib.source("S5")["manifest"]
    manifest.update(fields)
    with w.lib.sources:
        w.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id='S5'", (json.dumps(manifest),))


def test_author_reference_resolves_registered_identity_and_keeps_ambiguity(kb):
    add_claim(kb, "regression_covariance_scope", "statistical_inference")
    update_source(kb, authors="Robin Exampleton", query_names=[])
    result = kb.query("按Exampleton的文章解释HAC协方差设置。", context={"corpus_roles": ["core", "research"]})
    assert result["answer_status"] == "answered_with_support"
    assert result["retrieval"]["question_contract"]["source_constraints"]["source_ids"] == ["S5"]
    kb.lib.seed({"sources": [{"source_id": "SYNTH-OTHER", "title": "Another study",
        "authors": "Robin Exampleton", "doi": "10.1234/synthetic-other", "corpus_roles": ["research"]}]}, {"cards": []})
    unresolved = kb.query("按Exampleton的文章解释HAC协方差设置。", context={"corpus_roles": ["core", "research"]})
    assert not unresolved["claims"]
    assert unresolved["retrieval"]["question_contract"]["source_constraints"]["unresolved_named_source"]


def test_registered_citation_author_and_mixed_chinese_acronym_reach_real_query(kb):
    add_claim(kb, "equivalence_test_logic", "statistical_inference")
    update_source(kb, authors=None, citation="Exampleton R, Person AB. Synthetic methods study.")
    answer = kb.query("Exampleton等讨论的TOST为何要两个单侧检验都通过？",
                      context={"corpus_roles": ["core", "research"]})
    assert answer["answer_status"] == "answered_with_support"
    assert {x["source_id"] for x in answer["citations"]} == {"S5"}
    assert answer["retrieval"]["question_contract"]["source_constraints"]["source_ids"] == ["S5"]


def test_named_activity_source_preserves_public_health_goal_and_start_target(kb):
    update_source(kb, query_names=["Synthetic Activity Guide"], edition=2, document_kind="guideline")
    for outcome, subject in [("adult_guideline_scope", "physical_activity"), ("frequency", "resistance_training"),
                             ("goal_scope", "resistance_training"), ("muscle_strengthening_start", "resistance_training"),
                             ("activity_increment_size", "physical_activity")]:
        add_claim(kb, outcome, subject, scope={"population": "adults", "goal": "public_health"})
    result = kb.query("Synthetic Activity Guide第二版每周两天肌力活动针对谁？能认定是我的最佳增肌频率吗？")
    assert result["answer_status"] == "answered_with_support"
    assert {p["part_id"] for p in result["support_assessment"]["covered_parts"]} == {
        "adult_guideline_scope", "frequency:public_health", "goal_scope"}
    for question in ("Synthetic Activity Guide第4章怎样开始肌力训练？",
                     "Synthetic Activity Guide：同样每周多跑一些分钟，为什么不算同等幅度的增加？"):
        answer = kb.query(question)
        assert answer["answer_status"] == "answered_with_support"
        assert not answer["numeric_actions"]
    wrong_edition = kb.query("Synthetic Activity Guide第三版怎样开始肌力训练？")
    assert not wrong_edition["claims"]
    prescription = kb.query("按Synthetic Activity Guide为我的增肌训练选择最佳频率。")
    assert prescription["answer_status"] != "answered_with_support"
