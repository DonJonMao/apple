"""Versioned domain concepts and compositional requested-answer parts.

These rules recognize questions, not truth or source authority. Each recognized
part still needs an eligible reviewed claim with the same semantic task. There
is no question whitelist, similarity cutoff, or personal-number generation.
"""
from __future__ import annotations

import re

RELATIONS = {
    "progression_options": "options", "failure_necessity": "necessity",
    "effort_precision": "precision", "volume": "options", "frequency": "options",
    "rest": "options", "capability_change": "inference",
    "longevity": "individual_inference", "personal_temperature": "individual_inference",
    "individual_error_bound": "individual_inference",
    "progression_necessity": "necessity", "load_repetition_relation": "explanation",
    "comparability": "scope", "population_scope": "scope", "gradual_progression": "options",
    "symptoms": "scope", "individual_effect": "inference", "goal_scope": "scope",
    "variation": "necessity",
}

LABELS = {
    "progression_options": "渐进训练的任务选择", "failure_necessity": "是否必须达到力竭",
    "effort_precision": "余力与努力程度的精度边界", "volume": "训练组量及其适用边界",
    "frequency": "训练频次及其适用目标", "rest": "组间休息及其适用边界",
    "capability_change": "可比表现与能力变化", "longevity": "个人寿命推断",
    "personal_temperature": "个人体温推断", "individual_error_bound": "个人误差界限",
    "progression_necessity": "持续进阶与初始收益", "load_repetition_relation": "负荷和可完成次数的关系",
    "comparability": "训练与测量任务可比性", "population_scope": "来源的人群适用范围",
    "gradual_progression": "逐步增加活动", "symptoms": "症状及活动范围",
    "individual_effect": "个人效果与因果边界", "goal_scope": "不同训练目标",
    "variation": "变化和周期组织是否必要",
}

# A finite public vocabulary with grammatical variants. English terms use word
# boundaries so incidental substrings (e.g. 'sets' inside 'datasets') cannot
# authorize a target. Chinese inflections are represented by local patterns.
PATTERNS = {
    "progression_options": [
        r"(?:增加|提高|提升|多做|加|往上调).{0,8}(?:次数|重复|重量|负荷|负重)",
        r"(?:次数|重复|重量|负荷|负重).{0,6}(?:增加|提高|提升|往上|加一点|多一点)",
        r"多(?:完成|做上|做出|举).{0,6}(?:次|重复)",
        r"\b(?:add|adding|raise|raising|increase|increasing|more|extra|additional)\b.{0,30}\b(?:reps?|repetitions?|weight|load)\b",
        r"\b(?:reps?|repetitions?|weight|load)\b.{0,30}\b(?:increase|higher|more|add)\b",
    ],
    "failure_necessity": [r"(?:举|推|拉|做|抬|完成)不(?:起来|动|了)", r"不能再完成", r"筋疲力尽", r"\b(?:failure|exhaustion)\b", r"\b(?:cannot|can't|unable to)\b.{0,25}\b(?:rep|repetition|lift)\b"],
    "effort_precision": [r"(?:还|尚|剩|保留).{0,6}(?:能做|能完成|做得了|重复|次数)", r"储备次数|余次|留几次|接近力竭程度", r"\b(?:reps?|repetitions?) (?:left|remaining|in reserve)\b"],
    "volume": [r"训练总量|总组量|工作组|每个(?:动作|肌群).{0,5}组", r"\b(?:set count|number of sets|training volume|weekly sets|how many sets|sets per)\b", r"\b(?:many|more|fewer|additional|multiple|single|one|two|three|\d+) (?:work |working )?sets?\b"],
    "frequency": [r"(?:每周|一周|每星期|一星期).{0,12}(?:练|训练|进行|做|至少|最少).{0,6}(?:几|多少|两|二|三|四|五|六|七|\d+)(?:次|天|日)", r"一周几练|每周几练|每周练几次", r"\b(?:how often|days per week|times per week|sessions per week|training frequency)\b"],
    "rest": [r"两组之间|组与组之间|组间歇|歇多久|间歇时长", r"\b(?:between sets|interset|inter-set|rest interval|rest period)\b"],
    "capability_change": [r"记录.{0,4}(?:不变|一样|没变化)|表现.{0,4}(?:不变|一样|没变化)|(?:同|一样的)重量.{0,5}(?:同|一样的)次数", r"\b(?:same|unchanged)\b.{0,18}\b(?:load|weight|performance|reps|repetitions)\b"],
    "progression_necessity": [r"(?:必须|一定|非得).{0,10}(?:进阶|渐进|不断加|持续加)|不(?:进阶|加重|增加负荷).{0,14}(?:收益|效果|进步)", r"\b(?:must|necessary|without)\b.{0,25}\b(?:progression|progressive overload|increasing load)\b"],
    "load_repetition_relation": [r"(?:增重|加重|负荷增加|重量增加).{0,16}(?:次数减少|少做|次数下降)|负荷.{0,6}次数.{0,6}(?:关系|反向)", r"\b(?:heavier|higher load)\b.{0,25}\b(?:fewer|less|decrease)\b.{0,12}\b(?:reps|repetitions)\b"],
    "comparability": [r"可比|换(?:动作|器械|握距|动作幅度)|测量特异性", r"\b(?:comparab\w*|specificity|different equipment)\b"],
    "population_scope": [r"(?:适用|研究|样本|纳入).{0,8}(?:人群|对象)|适用于谁|哪些人", r"\b(?:population|who does|who is|applicable to whom)\b"],
    "gradual_progression": [r"逐步增加|循序渐进|刚开始活动|从不活动", r"\b(?:gradual\w*|start slowly|inactive people)\b"],
    "symptoms": [r"症状|胸痛|胸闷|头晕|不适|疼痛", r"\b(?:symptom\w*|pain|dizziness|chest discomfort)\b"],
    "individual_effect": [r"(?:证明|导致|因果|归因).{0,16}(?:个人|我|效果|进步)|(?:个人|我).{0,16}(?:必然有效|保证有效|因果)|群体.{0,16}个人", r"\b(?:causal|causation|cause|guarantee|individual effect)\b"],
    "goal_scope": [r"(?:力量|增肌|肌肥大|健康).{0,8}(?:目标|目的).{0,8}(?:区别|不同)|(?:目标|目的).{0,8}(?:力量|增肌|健康)", r"\b(?:different goals|strength versus hypertrophy|strength vs hypertrophy)\b"],
    "variation": [r"周期化|周期组织|变化方案|经常换动作", r"\b(?:periodi[sz]ation|program variation)\b"],
}


def lexical_concepts(question, vocabulary):
    text = question.lower()
    found = set()
    for outcome, terms in vocabulary.items():
        for term in terms:
            pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])" if term.isascii() else re.escape(term)
            if re.search(pattern, text):
                found.add(outcome)
                break
    for outcome, patterns in PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.add(outcome)
    return found


def requested_parts(question, found, context):
    outcomes = found & RELATIONS.keys()
    text = question.lower()
    # 'Same load' can be the condition for adding repetitions; it is not by
    # itself a question about stalled capacity. Explicit change/inference words
    # keep that separate outcome when it really is asked.
    if "progression_options" in outcomes and "capability_change" in outcomes and not re.search(r"停滞|平台|没进步|没有进步|不进步|能力|plateau|stagnat|capacity", text):
        outcomes.discard("capability_change")
    if "progression_necessity" in outcomes:
        outcomes.discard("progression_options")
    if "load_repetition_relation" in outcomes:
        outcomes.discard("progression_options")
    if "effort_precision" in outcomes and "failure_necessity" in outcomes:
        if re.search(r"是否必须|一定要|必须.*力竭|非得|\bmust\b|\bnecessary\b", text) and not re.search(r"(?:多少|几次|精确|量化).{0,8}(?:余力|rir)|(?:余力|rir).{0,8}(?:多少|精确)|\bexact\b", text):
            outcomes.discard("effort_precision")
    inference = outcomes & {"longevity", "personal_temperature", "individual_error_bound"}
    if inference and not re.search(r"分别|同时回答|两件事|also explain|and separately", text):
        # E.g. repetition training is the intervention, longevity the endpoint.
        outcomes -= {"progression_options", "frequency", "volume", "rest"}
    if "device_measurement" in found:
        subject = "device_measurement"
    elif "resistance_training" in found or outcomes & {"failure_necessity", "effort_precision", "volume", "progression_options", "variation", "load_repetition_relation"}:
        subject = "resistance_training"
    elif context.get("query_route_explicit") in {"strength", "progression", "plateau"} and outcomes:
        subject = "resistance_training"
    else:
        subject = None
    goals = set()
    for goal, pattern in {
        "hypertrophy": r"增肌|肌肥大|\bhypertrophy\b|\bmuscle growth\b",
        "strength": r"(?:提高|提升|增加|最大|以|对)力量|力量(?!训练)|\bstrength\b(?!\s+training)",
        "public_health": r"公共健康|总体健康|一般健康|\bpublic health\b|\bgeneral health\b",
        "power": r"爆发力|功率收益|\bpower (?:gains|outcomes?|goals?)\b",
    }.items():
        if re.search(pattern, text):
            goals.add(goal)
    if not goals and context.get("training_goal") in {"hypertrophy", "strength", "public_health", "power"}:
        goals.add(context["training_goal"])
    sensitive = {"progression_options", "failure_necessity", "effort_precision", "volume", "frequency", "rest"}
    labels = {"hypertrophy": "肌肥大", "strength": "力量", "public_health": "总体健康", "power": "功率"}
    parts = []
    for outcome in sorted(outcomes):
        for goal in sorted(goals) if outcome in sensitive and goals else [None]:
            parts.append({"part_id": outcome + (":" + goal if goal else ""),
                "label": LABELS[outcome] + ("（" + labels[goal] + "目标）" if goal else ""),
                "subject": subject, "outcome": outcome, "requested_relation": RELATIONS[outcome],
                **({"requested_goal": goal} if goal else {})})
    return parts
