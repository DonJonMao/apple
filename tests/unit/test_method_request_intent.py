"""Method suitability is not an instruction to compute a person's statistics."""

import pytest
from test_round5_question_language import add_claim
from test_round5_question_language import kb as kb

from healthzip.knowledge.tasks import parse_task


@pytest.mark.parametrize("question", [
    "我的数据是同一批人训练前后各测一次，指标分布还很偏斜。能把这篇运动科学等效检验文章里演示的计算方法原样照搬吗？文中的示范是建立在什么数据条件上的？",
    "等效检验文章中的计算方式能直接套用于配对资料吗？",
    "请解释等效检验计算公式的适用条件，不是每种设计都能照搬吧？",
    "这篇等效检验文章的计算步骤是否以独立样本为前提？",
    "能解释文中置信区间计算过程背后的假设吗？",
    "文章的等效检验计算示例有哪些限制？",
    "等效检验的计算框架适用于哪些研究设计？",
    "Can the equivalence article's calculation method be applied unchanged to paired observations?",
    "请给我解释置信区间的计算方法有哪些适用条件。",
    "请提供我的回归标准误的定义，以及等效计算公式的适用条件。",
])
def test_method_nouns_do_not_create_a_statistical_execution_request(question):
    task = parse_task(question)
    assert not task["statistical_calculation_request"]
    assert "statistical_calculation" not in {p["part_id"] for p in task["required_answer_parts"]}


@pytest.mark.parametrize("question", [
    "请用文中的等效检验计算方法，计算我的检验统计量。",
    "请解释等效检验计算公式，再算出这组数据的P值。",
    "文中计算步骤适用于哪些设计？然后帮我计算训练前后的等效置信区间。",
    "请解释置信区间计算过程，再给出我的连续训练误判率。",
    "能否照搬这个计算方法？请给我的训练数据选择等效界值。",
    "请按照HC3的计算方式确定我的回归标准误。并替我选择HAC带宽。",
    "Explain the equivalence calculation method, and compute the test statistic for my data.",
    "请用文中的计算方法给我置信区间。",
    "解释等效检验的计算方法，然后给出我的P值。",
    "请按计算方法提供我的回归斜率。",
])
def test_method_explanations_do_not_consume_a_separate_statistics_request(question):
    task = parse_task(question)
    assert task["statistical_calculation_request"]
    assert "statistical_calculation" in {p["part_id"] for p in task["required_answer_parts"]}


def test_actual_query_can_fully_answer_method_scope_without_fabricating_a_missing_calculation(kb):
    add_claim(kb, "practical_equivalence", "statistical_inference")
    result = kb.query("文章中的等效检验计算方法有什么限制？")
    assert result["answer_status"] == "answered_with_support"
    assert not result["support_assessment"]["uncovered_parts"]
    assert not result["numeric_actions"]


def test_actual_query_retains_a_missing_execution_part_for_mixed_requests(kb):
    add_claim(kb, "practical_equivalence", "statistical_inference")
    result = kb.query("文章中的等效检验计算方法有什么限制？再计算我的等效检验统计量。")
    assert result["answer_status"] == "partially_answered"
    assert "statistical_calculation" in {p["part_id"] for p in result["support_assessment"]["uncovered_parts"]}
    assert not result["numeric_actions"]


def test_intent_resolution_keeps_source_and_partition_gates(kb):
    question = "文章中的等效检验计算方法有什么限制？"
    assert kb.query(question)["answer_status"] != "answered_with_support"
    add_claim(kb, "practical_equivalence", "statistical_inference")
    assert not kb.query(question, context={"corpus_roles": ["core"]})["claims"]
    assert not kb.query(question, context={"source_constraints": {"source_ids": ["S1"]}})["claims"]
