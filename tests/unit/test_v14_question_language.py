"""Developer-defined language examples, independent of held-out QA questions.

These tests exercise requested meaning, not scientific support. Recognizing a
target must leave source, scope, goal, and personal calculation gates intact.
"""

import pytest

from healthzip.knowledge.tasks import parse_task


def outcomes(question, context=None):
    task = parse_task(question, context)
    return {part["outcome"] for part in task["required_answer_parts"] if "outcome" in part}


@pytest.mark.parametrize("question", [
    "Could a resistance training set be progressed by raising repetitions?",
    "Is an increase in repetitions an option for resistance training?",
    "Can repetitions be increased during resistance training?",
    "训练可以把重复数往上调吗？",
    "抗阻练习能在原重量下再完成额外几次吗？",
])
def test_actions_allow_active_passive_and_noun_forms(question):
    assert outcomes(question) == {"progression_options"}


@pytest.mark.parametrize("question", [
    "How frequently should healthy adults train for strength?",
    "Does training twice a week differ from training on four days a week for hypertrophy?",
    "抗阻训练一星期做几回合适？",
    "训练频次对力量收益有什么影响？",
    "How should resistance training sessions be distributed across the week?",
])
def test_frequency_means_recurrence_or_session_distribution(question):
    assert outcomes(question) == {"frequency"}


@pytest.mark.parametrize("question,expected", [
    ("During the coming fortnight can repetitions be increased in training?", {"progression_options"}),
    ("After three weeks of training, must every set reach failure?", {"failure_necessity"}),
    ("每隔两周回看训练记录可以吗？", set()),
    ("这几天的训练记录保存在哪里？", set()),
    ("How long should lifters pause between sets for strength?", {"rest"}),
    ("训练两组之间歇一会还是久一点？", {"rest"}),
    ("How is strength measured in this trial?", set()),
    ("训练研究报告了哪些测量结果？", set()),
])
def test_modifiers_and_generic_measurement_do_not_invent_targets(question, expected):
    assert outcomes(question) == expected


@pytest.mark.parametrize("question", [
    "Does using a greater training load reduce the repetitions a person can complete?",
    "Why can fewer repetitions be completed when a resistance training load is increased?",
    "抗阻练习中，配重调高后能完成的重复数为何变少？",
    "同一动作负重与重复次数有什么联系？",
])
def test_load_and_repetitions_are_a_relation_not_two_progression_requests(question):
    assert outcomes(question) == {"load_repetition_relation"}


@pytest.mark.parametrize("question", [
    "Does a strength training program need to be periodized?",
    "Must resistance workouts follow a periodised schedule?",
    "训练方案非得定期调整才能取得收益吗？",
    "Is planned variation necessary in resistance training?",
    "Do lifters need to vary their training program?",
])
def test_variation_and_periodization_have_finite_grammatical_families(question):
    assert outcomes(question) == {"variation"}


@pytest.mark.parametrize("question", [
    "Can the review establish that resistance training caused my improvement?",
    "Does a gain after a workout demonstrate that the workout produced the gain?",
    "抗阻训练后的进步能归功于这次训练吗？",
    "群体训练结果能保证每个人都有效吗？",
    "Can a group training result predict benefits for each individual?",
])
def test_causal_and_individual_effect_questions_keep_the_inference_boundary(question):
    assert outcomes(question) == {"individual_effect"}


@pytest.mark.parametrize("question", [
    "What ages were included in the resistance training review?",
    "Is this resistance training review limited to adults?",
    "这份抗阻研究纳入的是哪一年龄段？",
    "这份训练研究涵盖哪些参加者？",
    "Does the strength training review include teenagers?",
])
def test_population_scope_recognizes_age_and_inclusion_relations(question):
    assert outcomes(question) == {"population_scope"}


@pytest.mark.parametrize("question", [
    "Should physically inactive adults build up their activity little by little?",
    "Do adults returning to exercise need to increase activity in small steps?",
    "久坐成年人开始身体活动时可以一点点增加吗？",
    "重新开始锻炼需要慢慢加大活动量吗？",
])
def test_gradual_activity_recognizes_incremental_action(question):
    assert outcomes(question) == {"gradual_progression"}


@pytest.mark.parametrize("question", [
    "Does a statistically insignificant result establish practical equivalence?",
    "Can absence of statistical significance establish that two treatments have equivalent effects?",
    "What does failing to reject the null hypothesis say about practical equivalence?",
    "统计差异未达显著是否意味着实用等效？",
])
def test_method_questions_have_a_statistical_subject(question):
    task = parse_task(question)
    assert outcomes(question) == {"practical_equivalence"}
    assert task["subject"] == "statistical_inference"


def test_compound_targets_and_training_goals_remain_separate():
    task = parse_task("Explain training frequency and rest between sets for strength and hypertrophy.")
    assert {part["part_id"] for part in task["required_answer_parts"]} == {
        "frequency:strength", "frequency:hypertrophy", "rest:strength", "rest:hypertrophy",
    }
    assert outcomes("Do resistance workouts need to be periodized, and can group results guarantee individual benefits?") == {
        "variation", "individual_effect",
    }


@pytest.mark.parametrize("question", [
    "Who caused the server failure?",
    "Does this archive use periodized historical records?",
    "How frequently is the database backed up?",
    "Gradually increase the image brightness.",
    "Are the two currency amounts equivalent?",
    "这些文件的版本是否等效？",
])
def test_unrelated_shared_words_do_not_supply_a_training_or_method_subject(question):
    task = parse_task(question)
    assert not task["required_answer_parts"] or all(
        part.get("subject") is None for part in task["required_answer_parts"]
    )


def test_language_recognition_does_not_override_source_or_personal_constraints():
    task = parse_task("According to S5 chapter 7, can repetitions be increased, and calculate my exact load in kg?")
    assert "progression_options" in outcomes("Can repetitions be increased?")
    assert task["source_constraints"]["source_ids"] == ["S5"]
    assert task["source_constraints"]["requested_chapter_number"] == "7"
    assert task["personal_numeric_request"]
    assert "personal_numeric_request" in {part["part_id"] for part in task["required_answer_parts"]}


def test_named_source_domain_context_and_unknown_targets_are_preserved():
    task = parse_task("What ages were included in the review?", {
        "named_source_task_subjects": {"population_scope": "resistance_training"},
    })
    assert task["subject"] == "resistance_training"
    assert task["outcome"] == "population_scope"
    assert not parse_task("Please explain that thing.")["required_answer_parts"]


@pytest.mark.parametrize("question,unexpected", [
    ("Does greater training volume reduce the repetitions completed?", "load_repetition_relation"),
    ("Can repetitions gradually be increased in resistance training?", "gradual_progression"),
    ("训练重量可以逐步增加吗？", "gradual_progression"),
])
def test_adjacent_modifiers_do_not_create_another_target(question, unexpected):
    assert unexpected not in outcomes(question)


@pytest.mark.parametrize("question", [
    "How are resistance training load and repetitions related?",
    "What is the relationship between repetitions and training load?",
    "Why do repetitions decrease as resistance training load increases?",
])
def test_load_repetition_relation_preserves_direction_and_word_order(question):
    assert outcomes(question) == {"load_repetition_relation"}


def test_separate_progression_question_survives_a_load_repetition_explanation():
    assert outcomes(
        "Explain why a higher load means fewer repetitions, and separately explain "
        "whether repetitions can be increased at the same load."
    ) == {"load_repetition_relation", "progression_options"}


@pytest.mark.parametrize("question", [
    "统计差异没有达到统计显著能证明没有效果吗？",
    "Does failing to reject the null hypothesis establish that there is no effect?",
])
def test_non_significance_question_does_not_need_the_word_equivalence(question):
    task = parse_task(question)
    assert outcomes(question) == {"practical_equivalence"}
    assert task["subject"] == "statistical_inference"


def test_resistance_training_is_a_modality_not_automatically_an_added_load():
    assert outcomes("Can more resistance training sessions be distributed across the week?") == {"frequency"}


@pytest.mark.parametrize("question", [
    "训练时把负荷、训练总量与频次按不同阶段轮换，是取得收益的必要条件吗？",
    "Must resistance training load, volume and frequency be arranged in blocks to make gains?",
    "Is dividing adjustments of load and set count into successive phases required for strength training?",
    "有人训练中先提高重量，再改变组数和训练频率；这样按阶段安排是否必须？",
])
def test_phase_organization_necessity_consumes_its_background_variables(question):
    task = parse_task(question)
    assert outcomes(question) == {"variation"}
    assert task["required_answer_parts"][0]["requested_relation"] == "necessity"


@pytest.mark.parametrize("question", [
    "Is periodized training superior to simple progressive overload when volume and frequency are similar?",
    "按阶段安排抗阻训练的负荷和组量，与普通渐进训练比较，效果证据如何？",
    "How does organising training volume and frequency into phases compare with ordinary progression?",
    "训练中把频次与组量按周期轮换，有证据支持额外收益吗？",
])
def test_comparative_benefit_is_not_answered_by_necessity(question):
    task = parse_task(question)
    assert outcomes(question) == {"variation_comparison"}
    assert task["required_answer_parts"][0]["requested_relation"] == "comparison"


@pytest.mark.parametrize("question", [
    "按周期调整负荷、组量和频次是否必需，以及相比普通渐进方案有没有额外收益？",
    "Must volume and load be organised in training phases, and is that better than ordinary progression?",
])
def test_necessity_and_comparative_advantage_are_separate_requested_relations(question):
    task = parse_task(question)
    assert {(p["outcome"], p["requested_relation"]) for p in task["required_answer_parts"]} == {
        ("variation", "necessity"), ("variation_comparison", "comparison"),
    }


@pytest.mark.parametrize("question,expected", [
    ("Do load and frequency have to be periodized? Separately, explain training volume.",
     {"variation", "volume"}),
    ("负荷与组量按阶段安排是必要的吗？另外，请解释每周训练频次。",
     {"variation", "frequency"}),
    ("Explain training volume. Must load and frequency be organized into training blocks?",
     {"variation", "volume"}),
    ("Must resistance training be periodized, and how often should adults train?",
     {"variation", "frequency"}),
    ("分阶段增加训练负荷有何比较优势？另外能否在原重量下增加重复次数？",
     {"variation_comparison", "progression_options"}),
    ("How does periodized training compare with constant training? Also, explain training volume and frequency.",
     {"variation_comparison", "volume", "frequency"}),
])
def test_independently_requested_variable_parts_survive_organization_scope(question, expected):
    assert outcomes(question) == expected


@pytest.mark.parametrize("question", [
    "How should training volume and frequency be arranged across the week?",
    "Our schedule includes recovery periods. Explain training volume and frequency.",
])
def test_weekly_distribution_and_time_periods_are_not_necessarily_periodization(question):
    assert outcomes(question) == {"volume", "frequency"}


def test_unknown_program_comparison_preserves_a_named_source_and_personal_request():
    task = parse_task(
        "According to S5 chapter 4, compare periodized training with ordinary progression; "
        "separately calculate my exact load in kg."
    )
    assert "variation_comparison" in {p.get("outcome") for p in task["required_answer_parts"]}
    assert task["source_constraints"]["source_ids"] == ["S5"]
    assert task["source_constraints"]["requested_chapter_number"] == "4"
    assert task["personal_numeric_request"]
