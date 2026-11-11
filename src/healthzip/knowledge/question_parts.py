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
    "variation": "necessity", "variation_comparison": "comparison",
    "practical_equivalence": "explanation",
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
    "variation": "变化和周期组织是否必要", "variation_comparison": "周期或阶段组织的比较效果",
    "practical_equivalence": "统计不显著与实用等效的区别",
}

# Finite grammatical families describe concepts and local relations, never whole
# questions. Word boundaries prevent substrings such as "sets" in "datasets".
REPETITIONS = r"\b(?:reps?|repetitions?)\b"
LOAD = r"(?:\b(?:loads?|weights?)\b|\bresistance\b(?!\s+(?:training|exercises?)\b))"
INCREASE = r"\b(?:add(?:s|ed|ing)?|rais(?:e[sd]?|ing)|increas(?:e[sd]?|ing)|higher|more|extra|additional)\b"
TRAINING = r"\b(?:train(?:s|ed|ing)?|workouts?|exercis(?:e[sd]?|ing)|lift(?:s|ed|ing|ers?)|resistance|strength|hypertrophy)\b"
STATISTICAL_METHOD = (
    r"统计|显著|实用等效|等效(?:性)?(?:检验|界|范围)|两单侧检验|零假设|原假设|"
    r"\b(?:statistic(?:s|al|ally)?|significan(?:t|ce)|insignifican(?:t|ce)|"
    r"non[- ]?significant|tost|null hypothes(?:is|es)|practical equivalence)\b|"
    r"\bequivalence\s+(?:test(?:s|ing)?|bounds?|margins?)\b|"
    r"\bp\s*(?:[<>≤≥=])\s*0?\.\d+"
)

PATTERNS = {
    "progression_options": [
        r"(?:增加|提高|提升|多做|加|往上调).{0,8}(?:次数|重复|重量|负荷|负重)",
        r"(?:次数|重复|重量|负荷|负重).{0,6}(?:增加|提高|提升|往上|加一点|多一点)",
        r"(?:多|再)(?:完成|做上|做出|举|做).{0,8}(?:次|重复)",
        INCREASE + r".{0,30}(?:" + REPETITIONS + "|" + LOAD + ")",
        r"(?:" + REPETITIONS + "|" + LOAD + r").{0,30}" + INCREASE,
    ],
    "failure_necessity": [r"(?:举|推|拉|做|抬|完成)不(?:起来|动|了)", r"不能再完成", r"筋疲力尽", r"\b(?:failure|exhaustion)\b", r"\b(?:cannot|can't|unable to)\b.{0,25}\b(?:rep|repetition|lift)\b"],
    "effort_precision": [r"(?:还|尚|剩|保留).{0,6}(?:能做|能完成|做得了|重复|次数)", r"储备次数|余次|留几次|接近力竭程度", r"\b(?:reps?|repetitions?) (?:left|remaining|in reserve)\b"],
    "volume": [r"训练总量|总组量|工作组|每个(?:动作|肌群).{0,5}组", r"\b(?:set count|number of sets|training volume|weekly sets|how many sets|sets per)\b", r"\b(?:many|more|fewer|additional|multiple|single|one|two|three|\d+) (?:work |working )?sets?\b"],
    "frequency": [
        r"频次|频率|(?:每周|一周|每星期|一星期).{0,12}(?:练|训练|进行|做|至少|最少).{0,6}(?:几|多少|两|二|三|四|五|六|七|\d+)(?:次|天|日|回)",
        r"(?:一周|每周)几练|(?:训练|锻炼|练).{0,6}(?:几天|多少天).{0,6}(?:一次|合适)|(?:每周|每星期).{0,6}(?:几天|多少天)",
        r"\b(?:how often|how frequently|days per week|times per week|sessions per week|training frequency)\b",
        r"\b(?:once|twice|thrice|(?:one|two|three|four|five|six|seven|\d+) (?:times?|days?|sessions?))\s+(?:a|per|each|every)\s+week\b",
        r"\b(?:sessions?|workouts?|training)\b.{0,35}\b(?:distribut(?:e[sd]?|ing|ion)|spread(?:ing)?|spac(?:e[sd]?|ing))\b.{0,30}\b(?:week|days)\b",
        r"\b(?:distribut(?:e[sd]?|ing|ion)|spread(?:ing)?|spac(?:e[sd]?|ing))\b.{0,30}\b(?:sessions?|workouts?|training)\b.{0,30}\b(?:week|days)\b",
        r"(?:训练|锻炼).{0,12}(?:分配|分布|分散|安排).{0,12}(?:周内|一周|每周|天)|(?:周内|一周|每周).{0,12}(?:分配|分布|分散|安排).{0,12}(?:训练|锻炼)",
    ],
    "rest": [r"两组之间|组与组之间|组间歇|歇多久|间歇时长", r"\b(?:between sets|interset|inter-set|rest intervals?|rest periods?)\b"],
    "capability_change": [r"记录.{0,4}(?:不变|一样|没变化)|表现.{0,4}(?:不变|一样|没变化)|(?:同|一样的)重量.{0,5}(?:同|一样的)次数", r"\b(?:same|unchanged)\b.{0,18}\b(?:load|weight|performance|reps|repetitions)\b"],
    "progression_necessity": [r"(?:必须|一定|非得).{0,10}(?:进阶|渐进|不断加|持续加)|不(?:进阶|加重|增加负荷).{0,14}(?:收益|效果|进步)", r"\b(?:must|necessary|without)\b.{0,25}\b(?:progression|progressive overload|increasing load)\b"],
    "load_repetition_relation": [
        r"(?:增重|加重|(?:负荷|重量|配重|负重).{0,6}(?:增加|调高|更重|提高)).{0,24}(?:(?:次数|重复数).{0,8}(?:减少|下降|变少)|少做)",
        r"(?:负荷|重量|配重|负重).{0,10}(?:次数|重复).{0,10}(?:关系|反向|联系)|(?:次数|重复).{0,10}(?:负荷|重量|配重|负重).{0,10}(?:关系|反向|联系)",
        r"(?:\bheavier\b|\b(?:higher|greater|increased)\b.{0,24}" + LOAD + r").{0,16}\b(?:fewer|less|reduc(?:e[sd]?|ing)|decreas(?:e[sd]?|ing))\b.{0,22}" + REPETITIONS,
        r"\b(?:fewer|less|reduc(?:e[sd]?|ing)|decreas(?:e[sd]?|ing))\b.{0,22}" + REPETITIONS + r".{0,65}" + LOAD + r".{0,24}" + INCREASE,
        REPETITIONS + r".{0,16}\b(?:decreas(?:e[sd]?|ing)|fall(?:s|ing)?|drop(?:s|ped|ping)?)\b.{0,40}" + LOAD + r".{0,20}" + INCREASE,
        r"\b(?:relation(?:ship)?|association|connection)\b.{0,35}(?:" + LOAD + r".{0,20}" + REPETITIONS + "|" + REPETITIONS + r".{0,20}" + LOAD + ")",
        r"(?:" + LOAD + r".{0,20}" + REPETITIONS + "|" + REPETITIONS + r".{0,20}" + LOAD + r").{0,25}\b(?:relat(?:e[sd]?|ion(?:ship)?)|connect(?:ed|ion)?)\b",
    ],
    "comparability": [r"可比|换(?:动作|器械|握距|动作幅度)|测量特异性", r"\b(?:comparab(?:le|ility)|specificity|different equipment)\b"],
    "population_scope": [
        r"(?:适用|研究|样本|纳入|涵盖|包括).{0,12}(?:人群|对象|年龄|参加者|参与者)|适用于谁|哪些人",
        r"\b(?:population|who does|who is|applicable to whom)\b",
        r"\b(?:ages?|age groups?|participants?)\b.{0,20}\b(?:includ(?:e[sd]?|ing)|exclud(?:e[sd]?|ing)|studied|eligible)\b",
        r"\b(?:includ(?:e[sd]?|ing)|exclud(?:e[sd]?|ing)|limited to|restricted to|eligible)\b.{0,25}\b(?:ages?|age groups?|adults?|children|adolescents?|teenagers?|participants?|patients?)\b",
    ],
    "gradual_progression": [
        r"逐步增加|循序渐进|刚开始活动|从不活动",
        r"(?:身体活动|活动量|锻炼).{0,16}(?:一点点|慢慢|逐渐|逐步).{0,8}(?:增加|加大|提高)|(?:一点点|慢慢|逐渐|逐步).{0,8}(?:增加|加大|提高).{0,8}(?:身体活动|活动量|锻炼)",
        r"\b(?:gradual(?:ly)?|start slowly|inactive people)\b",
        r"\b(?:activity|exercise)\b.{0,35}\b(?:little by little|small steps|small increments)\b",
        r"\b(?:little by little|small steps|small increments)\b.{0,35}\b(?:activity|exercise)\b",
    ],
    "symptoms": [r"症状|胸痛|胸闷|头晕|不适|疼痛", r"\b(?:symptoms?|pain|dizziness|chest discomfort)\b"],
    "individual_effect": [
        r"(?:证明|导致|因果|归因|归功于).{0,16}(?:个人|我|效果|进步|训练)|(?:个人|我|进步|效果).{0,16}(?:必然有效|保证有效|因果|归功于)|群体.{0,16}个人",
        r"\b(?:causal(?:ly)?|causation|caus(?:e[sd]?|ing)|guarantee[sd]?|individual effects?)\b",
        r"\b(?:workouts?|training|exercise|intervention)\b.{0,24}\b(?:produc(?:e[sd]?|ing)|led to|result(?:s|ed|ing)? in)\b.{0,20}\b(?:gains?|improvements?|benefits?|effects?)\b",
        r"\b(?:group|population|average)\b.{0,45}\b(?:predict(?:s|ed)?|establish(?:es|ed)?|apply|applies)\b.{0,40}\b(?:individual|person|everyone)\b",
    ],
    "goal_scope": [r"(?:力量|增肌|肌肥大|健康).{0,8}(?:目标|目的).{0,8}(?:区别|不同)|(?:目标|目的).{0,8}(?:力量|增肌|健康)", r"\b(?:different goals|strength versus hypertrophy|strength vs hypertrophy)\b"],
    "variation": [
        r"(?:按|分|依|各|不同).{0,4}(?:阶段|周期|区块).{0,20}(?:组织|安排|调整|改变|变化|轮换|规划|增加)",
        r"\b(?:organi[sz](?:e[sd]?|ing|ation)|arrang(?:e[sd]?|ing|ement)|divid(?:e[sd]?|ing)|structur(?:e[sd]?|ing)|schedul(?:e[sd]?|ing))\b.{0,100}\b(?:in(?:to)?|across|by|over)\b.{0,20}\b(?:phases?|blocks?|cycles?)\b",
        r"\b(?:phase|block|cycle)[ -]based\b.{0,30}\b(?:training|program(?:me)?|schedule)\b",
        r"周期化|周期组织|变化方案|经常换动作|(?:训练|方案|计划).{0,12}(?:定期|经常|周期性).{0,6}(?:调整|改变|变化)",
        r"\b(?:periodi[sz](?:ation|e[sd]?|ing)|program(?:me)? variation|planned variation)\b",
        r"\b(?:vary|varies|varied|varying|variations?)\b.{0,25}\b(?:training|workouts?|program(?:me)?|schedule)\b",
        r"\b(?:training|workouts?|program(?:me)?|schedule)\b.{0,25}\b(?:vary|varies|varied|varying|variations?)\b",
    ],
    "practical_equivalence": [
        r"统计不显著|无统计学意义|(?:实用)?等效(?:性|检验|界|范围)?|两单侧检验|统计.{0,10}未达显著|(?:未达(?:到)?|没有达到).{0,6}统计显著|未能拒绝.{0,6}(?:零|原)假设",
        r"\b(?:non[- ]?significant|equivalence|equivalent|tost|statistically insignificant|absence of statistical significance)\b",
        r"\bnot\b.{0,16}\bstatistically significant\b|\bfail(?:s|ed|ing)? to reject\b.{0,16}\bnull hypothesis\b",
        r"\bp\s*(?:>|≥).{0,16}(?:没有|没|无|证明|no effect|no change)",
    ],
}


def _lexical_hits(text, vocabulary):
    found = set()
    for outcome, terms in vocabulary.items():
        for term in terms:
            # A time-window modifier is not by itself a recurrence question.
            if outcome == "frequency" and term in {"几天", "多少天"}:
                continue
            pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])" if term.isascii() else re.escape(term)
            if re.search(pattern, text):
                found.add(outcome)
                break
    for outcome, patterns in PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.add(outcome)
    if re.search(TRAINING, text) or re.search(
        r"身体活动|活动量|\bphysical(?:ly inactive)?\b.{0,35}\bactivity\b", text
    ):
        found.add("resistance_training")
    return found


# These predicates bind requests to the organization of variables. The variables
# named as its objects or comparator are not independent questions by default.
ORGANIZATION_NECESSITY = (
    r"必要|必需|必须|非得|一定要|需要|需不需要|"
    r"\b(?:must|necessary|necessity|required|requirements?|need(?:s|ed)?|"
    r"have to|has to|essential|prerequisites?)\b"
)
ORGANIZATION_COMPARISON = (
    r"相比|比较|对比|优于|胜过|优劣|优势|额外收益|更好|更有效|"
    r"\b(?:compar(?:e[sd]?|ing|ison)|versus|vs|superior|better|"
    r"outperform(?:s|ed|ing)?|advantages?|additional benefits?)\b"
)
REQUEST_BOUNDARY = (
    r"[;；。！？?!]|\.(?=\s|$)|另外|此外|另请|再请|"
    r"\b(?:and\s+)?(?:separately|additionally|also)\b|"
    r"\b(?:and|but)\s+(?=(?:how|what|why|when|explain|describe|discuss|can|could|should|must)\b)"
)
VARIABLE_REQUEST = (
    r"解释|说明|讨论|如何|怎么|什么|几组|几次|多少|能否|可否|是否可以|是否应该|呢|"
    r"\b(?:explain|describe|discuss|how|what|why|when|can|could|should)\b|"
    r"^\s*(?:is|are|do|does|must)\b"
)
ORGANIZED_VARIABLES = {
    "volume", "frequency", "rest", "progression_options", "progression_necessity",
    "gradual_progression", "capability_change",
}


def lexical_concepts(question, vocabulary):
    text = question.lower()
    found = _lexical_hits(text, vocabulary)
    if "variation" not in found:
        return found
    clauses = [clause for clause in re.split(REQUEST_BOUNDARY, text) if clause.strip()]
    organization_clauses = [
        clause for clause in clauses
        if any(re.search(pattern, clause) for pattern in PATTERNS["variation"])
    ]
    # A later sentence can ask about the same arrangement using an anaphor.
    relation_clauses = organization_clauses + [
        clause for clause in clauses if clause not in organization_clauses
        and re.search(r"这样|这种安排|该安排|上述组织|\b(?:it|this|that|such)\b", clause)
    ]
    necessity = any(re.search(ORGANIZATION_NECESSITY, clause) for clause in relation_clauses)
    comparison = any(re.search(ORGANIZATION_COMPARISON, clause) for clause in relation_clauses)
    if not necessity and not comparison:
        return found
    if comparison:
        found.add("variation_comparison")
        if not necessity:
            found.discard("variation")
    independent_variables = set()
    for clause in clauses:
        if clause not in relation_clauses and re.search(VARIABLE_REQUEST, clause):
            independent_variables |= _lexical_hits(clause, vocabulary) & ORGANIZED_VARIABLES
    found -= ORGANIZED_VARIABLES - independent_variables
    return found


def requested_parts(question, found, context):
    outcomes = found & RELATIONS.keys()
    text = question.lower()
    health_boundary = bool(
        re.search(r"公共健康|总体健康|一般健康|最低健康|\b(?:public|general) health\b", text)
        and re.search(r"力量|增肌|肌肥大|\b(?:strength|hypertrophy|muscle growth)\b", text)
        and re.search(r"证明|推出|意味着|代表|\b(?:prove|imply|establish|mean)\b", text)
        and re.search(r"最优|最佳|\b(?:optimal|optimum|best)\b", text)
    )
    if health_boundary:
        outcomes.add("goal_scope")
    # 'Same load' can be the condition for adding repetitions; it is not by
    # itself a question about stalled capacity. Explicit change/inference words
    # keep that separate outcome when it really is asked.
    if "progression_options" in outcomes and "capability_change" in outcomes and not re.search(r"停滞|平台|没进步|没有进步|不进步|能力|plateau|stagnat|capacity", text):
        outcomes.discard("capability_change")
    if "progression_necessity" in outcomes:
        outcomes.discard("progression_options")
    if "load_repetition_relation" in outcomes:
        # A relation consumes its load/repetition modifiers, but not a distinct
        # progression question connected in a separate clause.
        clauses = re.split(r"[;；]|\b(?:and separately|also explain|and (?:can|could|should))\b|另外|分别", text)
        separate_progression = len(clauses) > 1 and any(
            any(re.search(pattern, clause) for pattern in PATTERNS["progression_options"])
            and not any(re.search(pattern, clause) for pattern in PATTERNS["load_repetition_relation"])
            for clause in clauses
        )
        if not separate_progression:
            outcomes.discard("progression_options")
    if {"gradual_progression", "progression_options"} <= outcomes and not re.search(
        r"身体活动|活动量|\b(?:increas(?:e[sd]?|ing)|build(?:ing)? up)\b.{0,18}\bactivity\b|"
        r"\bactivity\b.{0,18}\bincreas(?:e[sd]?|ing)\b", text
    ):
        # Gradually changing the repetitions/load describes that task; it does
        # not independently ask about increasing general physical activity.
        outcomes.discard("gradual_progression")
    if "practical_equivalence" in outcomes and not re.search(r"分别|同时计算|also calculate|and separately", text):
        # A no-change endpoint can be the object of a statistical inference
        # question; it is not automatically a second personal trend estimate.
        outcomes.discard("capability_change")
        if not re.search(r"因果|导致|归因|归功于|\b(?:causal(?:ly)?|causation|caus(?:e[sd]?|ing))\b", text):
            outcomes.discard("individual_effect")
    if "effort_precision" in outcomes and "failure_necessity" in outcomes:
        if re.search(r"是否必须|一定要|必须.*力竭|非得|\bmust\b|\bnecessary\b", text) and not re.search(r"(?:多少|几次|精确|量化).{0,8}(?:余力|rir)|(?:余力|rir).{0,8}(?:多少|精确)|\bexact\b", text):
            outcomes.discard("effort_precision")
    inference = outcomes & {"longevity", "personal_temperature", "individual_error_bound"}
    if inference and not re.search(r"分别|同时回答|两件事|also explain|and separately", text):
        # E.g. repetition training is the intervention, longevity the endpoint.
        outcomes -= {"progression_options", "frequency", "volume", "rest"}
    if "device_measurement" in found:
        subject = "device_measurement"
    elif "resistance_training" in found or re.search(
        r"力竭|余力|储备次数|组量|组数|几组|组间|负重|加重|进阶|"
        r"\b(?:reps?|repetitions?|rir|sets?|progressive overload)\b", text
    ):
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
        part_subject = subject or context.get("named_source_task_subjects", {}).get(outcome)
        if outcome == "practical_equivalence":
            # "Equivalent" also describes currencies/files. Only a statistical
            # concept or an explicitly resolved source task supplies this subject.
            part_subject = ("statistical_inference" if re.search(STATISTICAL_METHOD, text)
                            else context.get("named_source_task_subjects", {}).get(outcome))
        part_goals = {"public_health"} if health_boundary and outcome == "frequency" else goals
        for goal in sorted(part_goals) if outcome in sensitive and part_goals else [None]:
            parts.append({"part_id": outcome + (":" + goal if goal else ""),
                "label": LABELS[outcome] + ("（" + labels[goal] + "目标）" if goal else ""),
                "subject": part_subject,
                "outcome": outcome, "requested_relation": RELATIONS[outcome],
                **({"requested_goal": goal} if goal else {})})
    return parts
