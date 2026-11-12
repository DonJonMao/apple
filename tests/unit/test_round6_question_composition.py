"""Post-freeze development checks, not independent round6 evaluations."""

import pytest
from test_round5_question_language import add_claim
from test_round5_question_language import kb as kb

from healthzip.knowledge.tasks import parse_task


def outcomes(question, context=None):
    return {p.get("outcome") for p in parse_task(question, context)["required_answer_parts"] if p.get("outcome")}


@pytest.mark.parametrize("question", [
    "保留2到3次重复与必须做到力竭有什么区别？",
    "是不是必须力竭？接近力竭、RIR2分别如何理解？",
    "Must every set reach failure, or can two repetitions in reserve describe sufficient effort?",
])
def test_reserve_effort_is_not_consumed_by_failure_necessity(question):
    assert {"failure_necessity", "effort_precision"} <= outcomes(question)


@pytest.mark.parametrize("question", [
    "请解释保留几次重复的限制，我能把每组恰好2RIR当作最佳安排吗？",
    "我的训练每组固定RIR2是否最佳？",
    "活动时间一般如何增加？能替我确定下周跑多快、跑多久吗？",
    "Can this general advice determine my exact running pace and duration?",
])
def test_personal_effort_and_activity_parameters_remain_unanswered(question):
    parts = parse_task(question)["required_answer_parts"]
    assert "personal_numeric_request" in {p["part_id"] for p in parts}


@pytest.mark.parametrize("question", [
    "我的连续训练记录前后差异不显著，可以说明没有实质进步吗？这种分析框架适用于个人记录吗？",
    "把我最近几次训练成绩划为前后两段，差异检验不显著就能断言没有有意义的变化吗？",
    "Does a non-significant comparison of my repeated training measurements before and after establish no meaningful change? Is this design appropriate?",
])
def test_repeated_personal_comparisons_require_meaning_and_design_explanations(question):
    assert {"practical_equivalence", "equivalence_design_scope"} <= outcomes(question)


@pytest.mark.parametrize("question", [
    "我的连续训练记录按前后分段保存在什么位置？",
    "The training log has a before and after tab. Where are my records?",
])
def test_record_storage_alone_does_not_request_statistical_design(question):
    assert not outcomes(question) & {"practical_equivalence", "equivalence_design_scope"}


@pytest.mark.parametrize("question", [
    "等效界值怎么定，TOST需要满足哪些条件才能支持等效？",
    "How should equivalence margins be chosen, and what criteria must TOST meet to support equivalence?",
])
def test_equivalence_bounds_do_not_consume_a_separate_test_criterion(question):
    assert {"equivalence_margin_basis", "equivalence_test_logic"} <= outcomes(question)


def test_covariance_estimator_validity_does_not_invent_an_equivalence_request():
    question = "HC3改善小样本表现是什么意思？能保证我少量连续记录的训练成绩正确判断是否停滞吗？"
    assert outcomes(question) == {"regression_covariance_scope"}


@pytest.mark.parametrize("question", [
    "我很少活动而且关节疼痛，增加活动为什么要循序渐进？一般应先增加什么？",
    "身体活动应如何慢慢增加，通常先加时长还是强度？",
    "When building up physical activity, what should usually increase first: duration or intensity?",
])
def test_activity_progression_order_is_not_resistance_load_progression(question):
    assert "gradual_progression" in outcomes(question)
    assert "progression_options" not in outcomes(question)


@pytest.mark.parametrize("question,topic,subject", [
    ("抗阻锻炼的不同形式是否都有效，选择时怎样考虑个人偏好和坚持？", "training_modality_adherence", "resistance_training"),
    ("How do preferences and adherence matter when choosing a resistance training modality?", "training_modality_adherence", "resistance_training"),
    ("快走通勤和短时有氧活动如何累计到每周活动目标？", "aerobic_activity_volume", "physical_activity"),
    ("Can short bouts of aerobic activity during commuting count toward weekly activity targets?", "aerobic_activity_volume", "physical_activity"),
    ("有氧和肌力活动分别有什么作用？拉伸可以替代它们吗？", "activity_type_complementarity", "physical_activity"),
    ("Can stretching replace aerobic and muscle-strengthening activity, and what does each contribute?", "activity_type_complementarity", "physical_activity"),
])
def test_new_topics_have_source_independent_structured_tasks(question, topic, subject):
    parts = parse_task(question)["required_answer_parts"]
    assert any(p.get("outcome") == topic and p.get("subject") == subject
               and p.get("requested_relation") == "explanation" for p in parts)


@pytest.mark.parametrize("question", [
    "My preferences for the training app's display are not saved.",
    "每周活动日志文件能合并计入存储量吗？",
    "在图片编辑中拉伸和缩放能互相替代吗？",
])
def test_similar_words_outside_topic_relations_do_not_create_new_targets(question):
    assert not outcomes(question) & {"training_modality_adherence", "aerobic_activity_volume", "activity_type_complementarity"}


def test_answer_status_does_not_hide_a_missing_effort_explanation(kb):
    add_claim(kb, "failure_necessity", "resistance_training")
    result = kb.query("每组必须力竭吗，保留两次重复该如何理解？")
    assert result["answer_status"] == "partially_answered"
    assert "effort_precision" in {p["part_id"] for p in result["support_assessment"]["uncovered_parts"]}
    assert not result["numeric_actions"]


def test_personal_series_cannot_be_fully_answered_by_a_significance_summary(kb):
    add_claim(kb, "non_significance_interpretation", "statistical_inference")
    result = kb.query("我的连续训练记录分为前后两段，差异不显著。能说明没有实质进步吗，分析框架能直接对应个人记录吗？")
    assert result["answer_status"] == "partially_answered"
    assert {"practical_equivalence", "equivalence_design_scope"} <= {
        p["part_id"] for p in result["support_assessment"]["uncovered_parts"]}


@pytest.mark.parametrize("question,topic,subject", [
    ("不同抗阻训练形式的选择为何要考虑偏好和坚持？", "training_modality_adherence", "resistance_training"),
    ("短时有氧活动如何计入每周目标？", "aerobic_activity_volume", "physical_activity"),
    ("有氧活动、肌力活动和拉伸能互相替代吗？", "activity_type_complementarity", "physical_activity"),
])
def test_new_topic_requires_eligible_source_support_and_keeps_partition_gate(kb, question, topic, subject):
    assert kb.query(question)["answer_status"] != "answered_with_support"
    add_claim(kb, topic, subject)
    answer = kb.query(question, context={"corpus_roles": ["core", "research"]})
    assert answer["answer_status"] == "answered_with_support"
    assert {c["source_id"] for c in answer["citations"]} == {"S5"}
    assert not answer["numeric_actions"]
    assert not kb.query(question, context={"corpus_roles": ["core"]})["claims"]
