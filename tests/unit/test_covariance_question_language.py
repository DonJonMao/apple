"""Developer examples for a new research-method explanation, not source review."""

import pytest

from healthzip.knowledge.tasks import parse_task


@pytest.mark.parametrize("question", [
    "HC和HAC协方差估计有什么适用范围区别？",
    "回归误差异方差或存在自相关时，普通置信区间为什么要谨慎？",
    "Explain the assumptions of heteroskedasticity and autocorrelation consistent covariance estimation.",
    "What is the difference between HC and HAC standard errors?",
    "Does using a HAC estimator automatically make a small-sample regression interval reliable?",
    "HAC协方差中的排序、带宽和滞后选项有哪些限制？",
    "只有几次训练记录，改用HAC后置信区间就一定可靠吗？",
])
def test_covariance_method_questions_have_a_separate_statistical_target(question):
    task = parse_task(question)
    parts = [p for p in task["required_answer_parts"] if "outcome" in p]
    assert {p["outcome"] for p in parts} == {"regression_covariance_scope"}
    assert parts[0]["subject"] == "statistical_inference"
    assert parts[0]["requested_relation"] == "scope"


@pytest.mark.parametrize("question", [
    "HAC俱乐部的力量训练每组是否必须力竭？",
    "The HC and HAC clubs use the same training program. Must sets reach failure?",
    "网络带宽不足，如何下载训练视频？",
    "My thermometer has an error bar. What does it mean?",
    "Explain an equivalence test confidence interval.",
])
def test_acronyms_and_generic_errors_do_not_invent_covariance_authority(question):
    task = parse_task(question)
    assert "regression_covariance_scope" not in {p.get("outcome") for p in task["required_answer_parts"]}


@pytest.mark.parametrize("question", [
    "Compute HAC standard errors for my training data.",
    "计算我的回归协方差和标准误。",
    "Choose the HAC bandwidth and lag order for my training data.",
    "根据N1，帮我选择HAC回归的带宽和滞后阶数。",
])
def test_actual_covariance_computation_or_personal_model_settings_remain_separate(question):
    task = parse_task(question)
    assert "statistical_calculation" in {p["part_id"] for p in task["required_answer_parts"]}


def test_covariance_method_preserves_a_separate_training_request():
    task = parse_task("Explain HAC standard errors. Also explain rest between training sets.")
    assert {p.get("outcome") for p in task["required_answer_parts"]} == {"regression_covariance_scope", "rest"}
