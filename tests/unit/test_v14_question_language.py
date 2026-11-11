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
    # The separately reviewed interpretation task now names this narrower target.
    assert outcomes(question) == {"non_significance_interpretation"}
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


@pytest.mark.parametrize("question,expected", [
    ("What evidence is needed to say a trial's two treatments differ by an unimportant amount?",
     {"practical_equivalence"}),
    ("研究两个方案的差别是否小到没有实际重要性，应怎样判定？", {"practical_equivalence"}),
    ("What does a nonsignificant statistical result actually establish?",
     {"non_significance_interpretation"}),
    ("研究的差异检验未能拒绝零假设，可以说明什么？", {"non_significance_interpretation"}),
    ("Explain how two one-sided tests establish equivalence.", {"equivalence_test_logic"}),
    ("双单侧检验为什么需要同时排除两个方向的效应？", {"equivalence_test_logic"}),
    ("Must the confidence interval lie entirely within equivalence bounds?", {"equivalence_test_logic"}),
    ("Can a generic small standardized effect be reused as the boundary of a meaningful difference?",
     {"equivalence_margin_basis"}),
    ("最小重要效应与通用的小效应分界是同一回事吗？", {"equivalence_margin_basis"}),
    ("For equivalence tests, do independent parallel groups and repeated measurements require the same assumptions?",
     {"equivalence_design_scope"}),
    ("平行组的两组独立观测所用等效方法可以直接用于同一个人的重复测量吗？",
     {"equivalence_design_scope"}),
])
def test_statistical_subtopics_have_their_own_semantic_tasks(question, expected):
    task = parse_task(question)
    assert outcomes(question) == expected
    assert all(part["subject"] == "statistical_inference"
               for part in task["required_answer_parts"] if "outcome" in part)


def test_independent_statistical_topics_survive_a_compound_request():
    assert outcomes(
        "Explain the logic of TOST. Separately, how should equivalence margins be justified? "
        "Also, is the method valid for repeated measurements rather than independent parallel groups?"
    ) == {"equivalence_test_logic", "equivalence_margin_basis", "equivalence_design_scope"}


@pytest.mark.parametrize("question", [
    "两组文件名称的差别很小，需要重新命名吗？",
    "Are two one-sided drawings the same size?",
    "Where is the boundary between two panels on the exercise screen?",
])
def test_ordinary_differences_and_boundaries_are_not_statistical_methods(question):
    task = parse_task(question)
    assert all(part.get("subject") != "statistical_inference" for part in task["required_answer_parts"])


@pytest.mark.parametrize("question", [
    "Which people were represented in this resistance training review?",
    "Were the participants experienced lifters or novices?",
    "这些抗阻研究主要来自有训练经验的人，还是初学者？",
    "训练综述中的样本是否能代表高龄人群？",
    "Did the resistance training review exclude patients and children?",
])
def test_population_scope_means_inclusion_representativeness_or_experience(question):
    assert outcomes(question) == {"population_scope"}


@pytest.mark.parametrize("question,expected", [
    ("How many training sets should children do?", {"volume"}),
    ("有疾病的患者训练频次应怎么安排？", {"frequency"}),
    ("Which medicine should this patient population take?", set()),
])
def test_population_mentions_in_application_requests_are_not_source_scope(question, expected):
    assert outcomes(question) == expected


@pytest.mark.parametrize("question", [
    "不继续增加刺激，抗阻训练是否仍然能有收益？",
    "如果不再提高训练负荷，就一定完全没有训练收益吗？",
    "Can resistance training produce benefits without further increases in stimulus?",
    "Does the absence of progressive overload imply that training offers no benefit?",
])
def test_negated_progression_is_a_necessity_question_not_an_extra_numeric_target(question):
    assert outcomes(question) == {"progression_necessity"}


@pytest.mark.parametrize("question", [
    "Does momentary muscular failure mean being unable to complete another repetition?",
    "抗阻训练里再也无法完成一次向心动作，是否就是瞬时肌肉力竭？",
])
def test_failure_definition_is_distinct_from_prescribing_failure(question):
    assert outcomes(question) == {"failure_definition"}


@pytest.mark.parametrize("question", [
    "Must a resistance exercise continue until no further repetition can be completed?",
    "训练是否必须做到无法再完成一次？",
])
def test_failure_necessity_accepts_inability_and_passive_forms(question):
    assert outcomes(question) == {"failure_necessity"}


@pytest.mark.parametrize("question", [
    "The training sessions have the same title. Where are they saved?",
    "这些训练方案的名称一样吗？",
])
def test_same_wording_or_titles_are_not_personal_capability_inference(question):
    assert "capability_change" not in outcomes(question)


def test_background_weekly_sets_do_not_turn_frequency_into_a_volume_request():
    assert outcomes(
        "With weekly sets held equal, how often should adults train for hypertrophy?"
    ) == {"frequency"}
    assert outcomes("在训练组量一样时，训练频次对肌肥大有什么证据？") == {"frequency"}
    assert outcomes(
        "With weekly sets held equal, explain training frequency; separately explain training volume."
    ) == {"frequency", "volume"}


def test_cross_goal_inference_preserves_both_requested_goals():
    task = parse_task("Can evidence about training frequency for strength be carried over to hypertrophy?")
    assert {p["part_id"] for p in task["required_answer_parts"]} == {
        "frequency:strength", "frequency:hypertrophy", "goal_scope",
    }
    task = parse_task("提高力量的组间休息结论，是否也能直接用于增肌目标？")
    assert {p["part_id"] for p in task["required_answer_parts"]} == {
        "rest:strength", "rest:hypertrophy", "goal_scope",
    }


@pytest.mark.parametrize("question,expected,subject", [
    ("Which age range does the adult chapter of physical activity guidelines address?",
     "adult_guideline_scope", "physical_activity"),
    ("身体活动指南的成人建议面向什么年龄段？", "adult_guideline_scope", "physical_activity"),
    ("How can an inactive adult begin muscle strengthening activity?",
     "muscle_strengthening_start", "resistance_training"),
    ("初次进行肌力活动应该从哪里开始？", "muscle_strengthening_start", "resistance_training"),
    ("Why should an increase in physical activity be a small increment?",
     "activity_increment_size", "physical_activity"),
    ("身体活动每次增加的幅度为什么要小一些？", "activity_increment_size", "physical_activity"),
    ("How do age and fitness affect the rate of increasing physical activity?",
     "progression_rate_factors", "physical_activity"),
    ("年龄和以往经验怎样影响身体活动增加的速度？", "progression_rate_factors", "physical_activity"),
])
def test_activity_subtopics_do_not_collapse_into_a_generic_progression(question, expected, subject):
    task = parse_task(question)
    assert outcomes(question) == {expected}
    assert task["subject"] == subject


@pytest.mark.parametrize("question", [
    "Should adults increase account limits in small increments?",
    "How does experience affect the rate of database backup?",
    "成人账户的年龄范围在哪里设置？",
])
def test_activity_subtopics_require_an_activity_subject(question):
    task = parse_task(question)
    assert all(p.get("subject") != "physical_activity" for p in task["required_answer_parts"])


@pytest.mark.parametrize("question,expected", [
    ("What is the basis for a smallest effect size of interest?", "equivalence_margin_basis"),
    ("为什么没有持续增加训练刺激也可能带来收益？", "progression_necessity"),
    ("Must resistance training be progressive to produce benefits?", "progression_necessity"),
    ("How representative were experienced lifters in this review?", "population_scope"),
    ("How quickly should physical activity increase given age and previous experience?", "progression_rate_factors"),
])
def test_semantic_tasks_accept_additional_noun_and_adjective_families(question, expected):
    assert outcomes(question) == {expected}


@pytest.mark.parametrize("question,outcome,subject", [
    ("成人建议面向什么年龄段？", "adult_guideline_scope", "physical_activity"),
    ("Why should the increment be small?", "activity_increment_size", "physical_activity"),
])
def test_named_source_context_supplies_only_the_matching_activity_topic(question, outcome, subject):
    context = {"named_source_task_subjects": {outcome: subject}}
    task = parse_task(question, context)
    assert outcomes(question, context) == {outcome}
    assert task["subject"] == subject
    assert outcome not in outcomes(question)


@pytest.mark.parametrize("question,unexpected", [
    ("Must a measurement confidence interval lie entirely within a device operating range?",
     "equivalence_test_logic"),
    ("How should repeated measurements be summarized statistically?", "equivalence_design_scope"),
    ("How do age and fitness affect adults' rate of increasing physical activity?", "adult_guideline_scope"),
])
def test_method_operands_and_activity_modifiers_do_not_supply_a_different_topic(question, unexpected):
    assert unexpected not in outcomes(question)


@pytest.mark.parametrize("question", [
    "在M2介绍的等效分析中，两个单侧检验要怎样同时满足要求，才与置信区间的判断相对应？",
    "两个单侧检验的判断如何对应置信区间？",
    "两项单侧检验为什么都要满足条件？",
])
def test_two_one_sided_tests_accept_chinese_classifiers(question):
    task = parse_task(question)
    assert outcomes(question) == {"equivalence_test_logic"}
    assert task["subject"] == "statistical_inference"


@pytest.mark.parametrize("question", [
    "HHS的成人章节说的是哪些年龄的人？",
    "HHS的成人章节说的是哪些年龄的人？落实其中的建议时，需要考虑已有活动量和自己的健康目标吗？",
    "成人建议适用于什么年龄的人群？",
])
def test_adult_age_group_interrogatives_use_matching_source_context(question):
    context = {"named_source_task_subjects": {"adult_guideline_scope": "physical_activity"}}
    assert outcomes(question, context) == {"adult_guideline_scope"}
    assert "adult_guideline_scope" not in outcomes(question)


@pytest.mark.parametrize("question", [
    "HHS为什么强调相对于原来活动量的小幅增加？安排增加速度时，年龄、体能与既往经验分别起什么作用？",
    "为什么要小幅增加身体活动？另外，身体活动增加速度受到年龄和经验怎样的影响？",
])
def test_increment_magnitude_and_progression_rate_remain_independent_targets(question):
    context = {"named_source_task_subjects": {
        "activity_increment_size": "physical_activity",
        "progression_rate_factors": "physical_activity",
    }}
    assert outcomes(question, context) == {"activity_increment_size", "progression_rate_factors"}


@pytest.mark.parametrize("question,unexpected", [
    ("成人身体活动增加的速度，要考虑哪些年龄因素？", "adult_guideline_scope"),
    ("成人账户说的是哪些年龄的人？", "adult_guideline_scope"),
    ("为什么要相对于原来容量小幅增加数据库空间？", "activity_increment_size"),
    ("两个单侧图形要怎样对应？", "equivalence_test_logic"),
])
def test_classifier_age_and_magnitude_words_keep_domain_and_relation_guards(question, unexpected):
    assert unexpected not in outcomes(question)


@pytest.mark.parametrize("question", [
    "抗阻训练的力竭指到了什么状态？每组必须做到这种状态吗？能精确确定余力吗？",
    "练到力竭究竟是什么状态？想长力气和长肌肉，必须练到那里吗？精确余力是多少？",
])
def test_failure_definition_anaphoric_necessity_and_precision_are_separate(question):
    assert outcomes(question) == {"failure_definition", "failure_necessity", "effort_precision"}


def test_colloquial_training_goals_are_preserved_for_both_requested_tasks():
    task = parse_task("想长力气和长肌肉，训练必须力竭吗？能确定精确余力吗？")
    assert {part["part_id"] for part in task["required_answer_parts"]} == {
        "failure_necessity:strength", "failure_necessity:hypertrophy",
        "effort_precision:strength", "effort_precision:hypertrophy",
    }


@pytest.mark.parametrize("question,expected", [
    ("身体活动都多出相同的分钟数，为何增加的负担可能不同？", "activity_increment_size"),
    ("身体活动每周增长的百分比是否能统一规定？", "activity_increment_size"),
    ("身体活动量要加得快还是慢，应考虑什么因素？", "progression_rate_factors"),
    ("年龄和既往经验怎样影响身体活动加得快慢？", "progression_rate_factors"),
    ("过去按某个速度增加身体活动的经验有什么意义？", "progression_rate_factors"),
    ("研究未发现显著差异能证明没有效果吗？", "non_significance_interpretation"),
    ("试验没有检出两种干预的统计显著差别，这说明什么？", "non_significance_interpretation"),
    ("为什么不能用通用效应量分界来设研究的等效界？", "equivalence_margin_basis"),
    ("等效检验中的界值要排除什么差异？", "equivalence_margin_basis"),
    ("抗阻训练不每次加负重，就完全没有收益吗？", "progression_necessity"),
    ("训练没有每回增加重量是否也能取得效果？", "progression_necessity"),
    ("训练是否一定得安排线性或波动周期？", "variation"),
    ("周期安排对抗阻训练是必要的吗？", "variation"),
    ("训练综述里健康成人的范围怎么定？", "population_scope"),
    ("抗阻证据包含有训练经验的人吗？", "population_scope"),
])
def test_development_chinese_relation_families(question, expected):
    assert outcomes(question) == {expected}


@pytest.mark.parametrize("question", [
    "训练不每次加重量就没收益吗？长期继续进步时，哪些变量可能需要改变？",
    "不持续增加训练刺激也会有收益吗？另外，长期进展可改变哪些训练变量？",
])
def test_progression_necessity_does_not_consume_separate_long_term_choices(question):
    assert outcomes(question) == {"progression_necessity", "progression_options"}


@pytest.mark.parametrize("question", [
    "在训练总量相同时，把训练分到更多天，对力量和肌肥大各有什么影响？",
    "如果训练总量一样，将训练分散到更多天，对力量和肌肥大各有何影响？",
])
def test_equal_volume_is_background_to_distribution_across_more_days(question):
    task = parse_task(question)
    assert {part["part_id"] for part in task["required_answer_parts"]} == {
        "frequency:strength", "frequency:hypertrophy",
    }


def test_separate_volume_question_survives_equal_volume_frequency_background():
    assert outcomes("在训练总量相同时，把训练分到更多天有何影响？另外，训练总量怎样选择？") == {
        "frequency", "volume",
    }


@pytest.mark.parametrize("question", [
    "抗阻训练换成更重的配重后，完成次数少了，为何不能就说力量退步？",
    "训练使用较重的负荷，重复次数下降有什么原因？",
])
def test_prenominal_heavier_load_and_fewer_repetitions_are_related(question):
    assert outcomes(question) == {"load_repetition_relation"}


def test_named_source_strength_measurement_and_load_relation_remain_separate():
    question = "换成更重的负重，一组次数少了说明什么？该综述的力量通常是怎么测的？"
    context = {"named_source_task_subjects": {"comparability": "resistance_training"}}
    assert outcomes(question, context) == {"load_repetition_relation", "comparability"}


@pytest.mark.parametrize("question,unexpected", [
    ("训练结束后到了什么状态？", "failure_definition"),
    ("力竭是什么状态？保存训练记录必须填写哪些字段？", "failure_necessity"),
    ("身体活动的动作做得快还是慢？", "progression_rate_factors"),
    ("两人身体活动的时间相同，怎么记录？", "activity_increment_size"),
    ("给数据清洗设阈值，需要排除什么记录？", "equivalence_margin_basis"),
    ("健康成人每周训练几天？", "population_scope"),
])
def test_development_relation_words_do_not_create_unasked_targets(question, unexpected):
    assert unexpected not in outcomes(question)


@pytest.mark.parametrize("question", [
    "训练研究没有发现显著差异，能说两个方案效果相同吗？",
    "统计检验不显著是否意味着两种干预有一样的效果？",
    "研究未发现显著差别，就能认定干预效果一样吗？",
])
def test_non_significance_to_equal_effect_inference_requests_equivalence_explanation(question):
    assert outcomes(question) == {"practical_equivalence"}


@pytest.mark.parametrize("question", [
    "不同品牌器械之间的配重能精确换算吗？",
    "跨品牌训练器械的负重怎么换算？",
    "负重在不同器械之间如何换算？",
])
def test_equipment_load_conversion_requests_comparability(question):
    assert outcomes(question) == {"comparability"}


def test_personal_equipment_conversion_keeps_numeric_authority_unresolved():
    task = parse_task("请给我不同品牌腿推器械之间精确的配重换算表。")
    assert {part["part_id"] for part in task["required_answer_parts"]} == {
        "comparability", "personal_numeric_request",
    }


@pytest.mark.parametrize("question,unexpected", [
    ("两种网页滤镜的效果一样吗？", "practical_equivalence"),
    ("两个文件的金额相同，汇率怎样换算？", "practical_equivalence"),
    ("美元金额怎样按汇率转换成人民币？", "comparability"),
    ("公斤和磅的重量单位怎样换算？", "comparability"),
    ("不同器械显示的重量单位如何换算？", "comparability"),
    ("训练研究没有发现显著差异，能够说明什么？", "practical_equivalence"),
])
def test_effect_equivalence_and_equipment_conversion_keep_local_relation_guards(question, unexpected):
    assert unexpected not in outcomes(question)
