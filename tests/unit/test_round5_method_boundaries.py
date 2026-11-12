"""Further development boundary checks; preserve all frozen QA results."""

import pytest
from test_round5_question_language import add_claim
from test_round5_question_language import kb as kb

from healthzip.knowledge.tasks import parse_task


@pytest.mark.parametrize("question", [
    "我的连续训练记录用HAC区间判断是否进入平台期，还需要哪些方法条件？",
    "Can HAC intervals from my repeated training measurements reliably determine a plateau?",
])
def test_personal_series_plateau_question_includes_equivalence_prerequisites(question):
    outcomes = {p.get("outcome") for p in parse_task(question)["required_answer_parts"]}
    assert outcomes == {"regression_covariance_scope", "practical_equivalence", "equivalence_design_scope"}


@pytest.mark.parametrize("question", [
    "少量训练记录的HAC区间就一定可靠吗？",
    "Does a small-sample HAC correction guarantee confidence interval coverage?",
    "我的训练记录一直一样，这些记录保存在哪里？",
])
def test_generic_covariance_or_record_queries_do_not_invent_equivalence_requests(question):
    outcomes = {p.get("outcome") for p in parse_task(question)["required_answer_parts"]}
    assert not outcomes & {"practical_equivalence", "equivalence_design_scope"}


def test_method_prerequisite_explanations_keep_source_and_personal_decision_gates(kb):
    add_claim(kb, "regression_covariance_scope", "statistical_inference")
    for outcome in ("practical_equivalence", "equivalence_design_scope"):
        add_claim(kb, outcome, "statistical_inference", source_id="M2")
    question = "我的连续训练记录用了HAC区间，就能判断平台期并给出个人误判率吗？"
    answer = kb.query(question, context={"corpus_roles": ["core", "research"]})
    assert answer["answer_status"] == "partially_answered"
    assert {c["source_id"] for c in answer["citations"]} == {"S5", "M2"}
    assert {p["part_id"] for p in answer["support_assessment"]["uncovered_parts"]} == {"statistical_calculation"}
    assert not answer["numeric_actions"]
    restricted = kb.query(question, context={"corpus_roles": ["core", "research"],
        "source_constraints": {"source_ids": ["S5"]}})
    assert {c["source_id"] for c in restricted["citations"]} == {"S5"}
    assert restricted["answer_status"] == "partially_answered"
    assert {p["part_id"] for p in restricted["support_assessment"]["uncovered_parts"]} >= {
        "practical_equivalence", "equivalence_design_scope", "statistical_calculation"}


def test_missing_book_body_explains_legal_exact_version_review_path(kb):
    kb.seed_core()
    answer = kb.query("请核对NSCA第4版的训练进阶规则和页码。")
    assert answer["answer_status"] == "missing_source_content"
    assert "可合法核对" in answer["answer"]
    assert "相关正文" in answer["answer"]
    assert "版次" in answer["answer"]
    assert "其他文献不能替代指定正文" in answer["answer"]
    assert not answer["claims"]
    assert not answer["numeric_actions"]
