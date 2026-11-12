"""Known-case development regressions, not independent semantic validation."""

import pytest
from test_round5_question_language import add_claim
from test_round5_question_language import kb as kb

from healthzip.knowledge.tasks import parse_task


def outcomes(question):
    return {p.get("outcome") for p in parse_task(question)["required_answer_parts"] if p.get("outcome")}


@pytest.mark.parametrize("question", [
    "快走和拉伸的时间，哪些能算进每周有氧目标？",
    "Can time spent stretching count toward aerobic activity targets?",
])
def test_activity_counting_keeps_the_type_boundary(question):
    assert {"aerobic_activity_volume", "activity_type_complementarity"} <= outcomes(question)


@pytest.mark.parametrize("question", [
    "两人每周慢跑的时间不同，都计划增加15分钟。相对风险会相同吗？通常优先加时间还是强度？",
    "With different starting amounts of jogging, is adding the same extra time equally risky? Should duration or intensity increase first?",
])
def test_relative_increment_and_progression_order_compose(question):
    assert {"activity_increment_size", "gradual_progression"} <= outcomes(question)
    assert "progression_options" not in outcomes(question)
    assert all(p.get("subject") for p in parse_task(question)["required_answer_parts"])


@pytest.mark.parametrize("question", [
    "健康成人有氧运动后体重没有变化，是不是没有健康益处？活动更多还有收益吗？",
    "Does aerobic activity have health benefits without weight loss, and is there a known upper benefit limit?",
])
def test_general_aerobic_benefits_are_not_a_personal_weight_prediction(question):
    assert "aerobic_activity_volume" in outcomes(question)
    assert not parse_task(question)["personal_forecast_request"]


@pytest.mark.parametrize("question", [
    "抗阻训练是否必须力竭，留两三次余力能当作精确的最优标准吗？",
    "必须练到力竭吗？保留几次余力又有什么证据？",
    "每组一定要达到力竭吗？如果留两三次余力，是不是人人都最合适的精确标准？",
])
def test_explicit_reserve_question_survives_failure_necessity(question):
    assert {"failure_necessity", "effort_precision"} <= outcomes(question)


def test_matched_set_volume_is_a_condition_of_frequency_comparison():
    question = "把相同的增肌训练总组数从三天拆成六天，肌肥大和力量会同比增长吗？这些判断可以从综述推出吗？"
    assert outcomes(question) == {"frequency"}
    assert {p["part_id"] for p in parse_task(question)["required_answer_parts"]} == {
        "frequency:hypertrophy", "frequency:strength"}
    assert outcomes(question + "另外，每个动作应该做多少组？") == {"frequency", "volume"}


@pytest.mark.parametrize("question", [
    "抗阻训练对SPPB综合评分和步行、平衡、起立分别有什么证据？",
    "What evidence links resistance training to physical performance, including SPPB and balance?",
])
def test_physical_performance_has_a_separate_source_task(question):
    parts = parse_task(question)["required_answer_parts"]
    assert any(p.get("outcome") == "physical_performance_evidence"
               and p.get("subject") == "resistance_training" for p in parts)


@pytest.mark.parametrize("question", [
    "能拿通用的“小效应”标准当作可忽略差异的界限吗？TOST又需要怎样通过？",
    "Can Cohen's conventional small effect threshold define a negligible difference? How does TOST determine equivalence?",
])
def test_conventional_effect_threshold_is_a_margin_question(question):
    assert {"equivalence_margin_basis", "equivalence_test_logic"} <= outcomes(question)


@pytest.mark.parametrize("question", [
    "以前不练力量，先从一周一天起步，与长期至少两天的目标矛盾吗？",
    "For someone new to strength training, how does starting with one day fit with a longer-term two-day goal?",
])
def test_strength_activity_start_is_distinct_from_personal_optimal_frequency(question):
    assert "muscle_strengthening_start" in outcomes(question)


@pytest.mark.parametrize("question", [
    "以前不练力量，想先从一天起步养成习惯，怎样理解参与坚持与长期安排？",
    "When starting strength training, how can building a habit fit with longer-term goals?",
])
def test_starting_a_strength_habit_requests_adherence_as_well_as_starting_scope(question):
    assert {"muscle_strengthening_start", "training_modality_adherence"} <= outcomes(question)


@pytest.mark.parametrize("question", [
    "拉伸图片后，哪些像素能算进画布？",
    "两人新增的会议时间不同，优先加天数还是时长？",
    "平衡预算对我的综合评分有什么帮助？",
    "SPPB是我的文件夹名称，应该怎样改名？",
    "I started the strength training app. Why is my profile name missing?",
    "My jogging log takes more storage. What is the upper limit of file size?",
])
def test_new_relations_require_domain_meaning(question):
    assert not outcomes(question) & {
        "activity_type_complementarity", "activity_increment_size", "gradual_progression",
        "aerobic_activity_volume", "physical_performance_evidence", "muscle_strengthening_start"}


def test_new_performance_task_keeps_source_and_partition_requirements(kb):
    question = "抗阻训练对SPPB综合评分有什么证据？"
    assert kb.query(question)["answer_status"] != "answered_with_support"
    add_claim(kb, "physical_performance_evidence", "resistance_training")
    answer = kb.query(question, context={"corpus_roles": ["core", "research"]})
    assert answer["answer_status"] == "answered_with_support"
    assert not answer["numeric_actions"]
    assert not kb.query(question, context={"corpus_roles": ["core"]})["claims"]
