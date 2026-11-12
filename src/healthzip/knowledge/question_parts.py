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
    "non_significance_interpretation": "explanation", "equivalence_test_logic": "explanation",
    "equivalence_margin_basis": "explanation", "equivalence_design_scope": "scope",
    "adult_guideline_scope": "scope", "muscle_strengthening_start": "options",
    "activity_increment_size": "explanation", "progression_rate_factors": "explanation",
    "failure_definition": "explanation",
    "regression_covariance_scope": "scope",
    "activity_safety_scope": "scope",
    "training_modality_adherence": "explanation",
    "aerobic_activity_volume": "explanation",
    "activity_type_complementarity": "explanation",
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
    "non_significance_interpretation": "差异检验不显著的解释边界",
    "equivalence_test_logic": "双单侧检验与置信区间判据",
    "equivalence_margin_basis": "等效界值与最小重要效应的依据",
    "equivalence_design_scope": "等效方法的研究设计适用范围",
    "adult_guideline_scope": "身体活动指南的成人范围",
    "muscle_strengthening_start": "开始肌力活动的一般任务",
    "activity_increment_size": "身体活动增量的大小",
    "progression_rate_factors": "身体活动增加速度的影响因素",
    "failure_definition": "瞬时肌肉力竭的定义",
    "regression_covariance_scope": "回归协方差与HC/HAC的适用范围",
    "activity_safety_scope": "安全活动建议的年龄适用范围",
    "training_modality_adherence": "抗阻训练形式、偏好与坚持",
    "aerobic_activity_volume": "有氧活动的计入、累计与每周目标",
    "activity_type_complementarity": "有氧、肌力与柔韧活动的作用和替代边界",
}

# Finite grammatical families describe concepts and local relations, never whole
# questions. Word boundaries prevent substrings such as "sets" in "datasets".
REPETITIONS = r"\b(?:reps?|repetitions?)\b"
LOAD = r"(?:\b(?:loads?|weights?)\b|\bresistance\b(?!\s+(?:training|exercises?)\b))"
INCREASE = r"\b(?:add(?:s|ed|ing)?|rais(?:e[sd]?|ing)|increas(?:e[sd]?|ing)|higher|more|extra|additional)\b"
TRAINING = r"\b(?:train(?:s|ed|ing)?|workouts?|exercis(?:e[sd]?|ing)|lift(?:s|ed|ing|ers?)|resistance|strength|hypertrophy)\b"
TWO_ONE_SIDED_TESTS = r"(?:双|两(?:个|项)?)单侧检验|(?<![a-z0-9])tost(?![a-z0-9]|文件夹|目录|俱乐部)|\btwo one[- ]sided tests?\b"
STATISTICAL_METHOD = (
    TWO_ONE_SIDED_TESTS + r"|统计|显著|实用等效|等效(?:性)?(?:检验|界|范围|方法)|零假设|原假设|"
    r"置信区间|最小重要效应|小效应|研究.{0,30}(?:差异|差别)|"
    r"\b(?:statistic(?:s|al|ally)?|significan(?:t|ce)|insignifican(?:t|ce)|"
    r"non[- ]?significant|tost|null hypothes(?:is|es)|practical equivalence)\b|"
    r"\bequivalence\s+(?:test(?:s|ing)?|bounds?|margins?)\b|"
    r"\b(?:confidence intervals?|two one[- ]sided tests?|standardi[sz]ed effects?|"
    r"smallest (?:important|meaningful) effect|smallest effect size of interest|meaningful difference)\b|"
    r"\b(?:stud(?:y|ies)|trials?|treatments?)\b.{0,60}\b(?:differ(?:ence|ences)?|unimportant|negligible)\b|"
    r"\bp\s*(?:[<>≤≥=])\s*0?\.\d+"
)
METHOD_OUTCOMES = {
    "practical_equivalence", "non_significance_interpretation", "equivalence_test_logic",
    "equivalence_margin_basis", "equivalence_design_scope",
    "regression_covariance_scope",
}
ACTIVITY_SUBJECTS = {
    "adult_guideline_scope": "physical_activity", "activity_increment_size": "physical_activity",
    "progression_rate_factors": "physical_activity", "muscle_strengthening_start": "resistance_training",
    "activity_safety_scope": "physical_activity",
    "aerobic_activity_volume": "physical_activity",
    "activity_type_complementarity": "physical_activity",
}
ACTIVITY_CONTEXT = r"身体活动|体力活动|肌力活动|肌力训练|肌肉强化|有氧|\b(?:physical activity|muscle[- ]strengthening|aerobic)\b"
RESERVE_EFFORT = (
    r"(?:还|尚|剩|保留).{0,10}(?:能做|能完成|做得了|重复|次数|[一二两三四五六七八九十\d]+次)|"
    r"储备次数|余次|留几次|接近力竭|足够努力|努力程度|"
    r"(?<![a-z])rir\s*\d*(?![a-z])|\b(?:reps?|repetitions?) (?:left|remaining|in reserve)\b|"
    r"\b(?:near failure|sufficient effort)\b"
)
PROGRESSION_CHOICE = (
    r"(?:哪些|什么).{0,6}(?:变量|方面|参数).{0,8}(?:改变|调整|增加)|"
    r"(?:改变|调整|增加).{0,4}(?:哪些|什么).{0,6}(?:变量|方面|参数)"
)


PATTERNS = {
    "progression_options": [
        r"(?:增加|提高|提升|多做|加|往上调).{0,8}(?:次数|重复|重量|负荷|负重)",
        r"(?:次数|重复|重量|负荷|负重).{0,6}(?:增加|提高|提升|往上|加一点|多一点)",
        r"(?<!无法)(?<!不能)(?:多|再)(?:完成|做上|做出|举|做).{0,8}(?:次|重复)",
        INCREASE + r".{0,30}(?:" + REPETITIONS + "|" + LOAD + ")",
        r"(?:" + REPETITIONS + "|" + LOAD + r").{0,30}" + INCREASE,
    ],
    "failure_necessity": [
        r"(?:无法|不能|没法|不再能).{0,6}(?:完成|做|举).{0,8}(?:次|动作)",
        r"\b(?:no further|no more|not another)\b.{0,16}\brepetitions?\b.{0,20}\bcompleted?\b",
        r"\b(?:reps?|repetitions?)\b.{0,12}\b(?:cannot|can't|can no longer)\b.{0,16}\bcompleted?\b",
        r"(?:举|推|拉|做|抬|完成)不(?:起来|动|了)", r"不能再完成", r"筋疲力尽", r"\b(?:failure|exhaustion)\b", r"\b(?:cannot|can't|unable to)\b.{0,25}\b(?:rep|repetition|lift)\b"],
    "effort_precision": [RESERVE_EFFORT],
    "volume": [r"\bhow many\s+(?:(?:training|working|work)\s+)?sets?\b", r"训练总量|总组量|工作组|每个(?:动作|肌群).{0,5}组", r"\b(?:set count|number of sets|training volume|weekly sets|how many sets|sets per)\b", r"\b(?:many|more|fewer|additional|multiple|single|one|two|three|\d+) (?:work |working )?sets?\b"],
    "frequency": [
        r"频次|频率|(?:每周|一周|每星期|一星期).{0,12}(?:练|训练|进行|做|至少|最少).{0,6}(?:几|多少|两|二|三|四|五|六|七|\d+)(?:次|天|日|回)",
        r"(?:一周|每周)几练|(?:训练|锻炼|练).{0,6}(?:几天|多少天).{0,6}(?:一次|合适)|(?:每周|每星期).{0,6}(?:几天|多少天)",
        r"\b(?:how often|how frequently|days per week|times per week|sessions per week|training frequency)\b",
        r"\b(?:once|twice|thrice|(?:one|two|three|four|five|six|seven|\d+) (?:times?|days?|sessions?))\s+(?:a|per|each|every)\s+week\b",
        r"\b(?:sessions?|workouts?|training)\b.{0,35}\b(?:distribut(?:e[sd]?|ing|ion)|spread(?:ing)?|spac(?:e[sd]?|ing))\b.{0,30}\b(?:week|days)\b",
        r"\b(?:distribut(?:e[sd]?|ing|ion)|spread(?:ing)?|spac(?:e[sd]?|ing))\b.{0,30}\b(?:sessions?|workouts?|training)\b.{0,30}\b(?:week|days)\b",
        r"(?:训练|锻炼).{0,12}(?:分配|分布|分散|安排).{0,12}(?:周内|一周|每周|天)|(?:周内|一周|每周).{0,12}(?:分配|分布|分散|安排).{0,12}(?:训练|锻炼)",
        r"(?:训练|锻炼).{0,12}(?:分到|分在|分散到|分配到|拆成).{0,8}(?:更多|更少|几|多少|\d+)(?:个)?(?:天|日)",
    ],
    "rest": [r"两组之间|组与组之间|组间歇|歇多久|间歇时长", r"\b(?:between sets|interset|inter-set|rest intervals?|rest periods?)\b"],
    "capability_change": [r"记录.{0,4}(?:不变|一样|没变化)|表现.{0,4}(?:不变|一样|没变化)|(?:同|一样的)重量.{0,5}(?:同|一样的)次数", r"\b(?:same|unchanged)\b.{0,18}\b(?:load|weight|performance|reps|repetitions)\b"],
    "progression_necessity": [
        r"(?:不|没有)(?:再|继续|持续|断|每次|每回)?(?:增加|提高|提升|加).{0,12}(?:刺激|负荷|重量|负重).{0,30}(?:收益|效果|进步)",
        r"\b(?:must|necessary|required|essential)\b.{0,45}\bprogressive(?:ly)?\b",
        r"\b(?:without|absence of|no further)\b.{0,30}\b(?:progressive overload|progression|increases? in (?:stimulus|load)|increasing (?:stimulus|load))\b",
        r"(?:必须|一定|非得).{0,10}(?:进阶|渐进|不断加|持续加)|不(?:进阶|加重|增加负荷).{0,14}(?:收益|效果|进步)", r"\b(?:must|necessary|without)\b.{0,25}\b(?:progression|progressive overload|increasing load)\b"],
    "load_repetition_relation": [
        r"(?:增加|提高|调高).{0,6}(?:负荷|重量|配重|负重).{0,16}(?:次数|重复数).{0,8}(?:减少|下降|变少)",
        r"(?:增重|加重|(?:负荷|重量|配重|负重).{0,6}(?:增加|调高|更重|提高)).{0,24}(?:(?:次数|重复数).{0,8}(?:减少|下降|变少)|少做)",
        r"(?:更重|较重|更高|较高)的?(?:负荷|重量|配重|负重).{0,24}(?:次数|重复数).{0,8}(?:减少|下降|变少|少了)",
        r"(?:负荷|重量|配重|负重).{0,10}(?:次数|重复).{0,10}(?:关系|反向|联系)|(?:次数|重复).{0,10}(?:负荷|重量|配重|负重).{0,10}(?:关系|反向|联系)",
        r"(?:\bheavier\b|\b(?:higher|greater|increased)\b.{0,24}" + LOAD + r").{0,16}\b(?:fewer|less|reduc(?:e[sd]?|ing)|decreas(?:e[sd]?|ing))\b.{0,22}" + REPETITIONS,
        r"\b(?:fewer|less|reduc(?:e[sd]?|ing)|decreas(?:e[sd]?|ing))\b.{0,22}" + REPETITIONS + r".{0,65}" + LOAD + r".{0,24}" + INCREASE,
        REPETITIONS + r".{0,16}\b(?:decreas(?:e[sd]?|ing)|fall(?:s|ing)?|drop(?:s|ped|ping)?)\b.{0,40}" + LOAD + r".{0,20}" + INCREASE,
        r"\b(?:relation(?:ship)?|association|connection)\b.{0,35}(?:" + LOAD + r".{0,20}" + REPETITIONS + "|" + REPETITIONS + r".{0,20}" + LOAD + ")",
        r"(?:" + LOAD + r".{0,20}" + REPETITIONS + "|" + REPETITIONS + r".{0,20}" + LOAD + r").{0,25}\b(?:relat(?:e[sd]?|ion(?:ship)?)|connect(?:ed|ion)?)\b",
    ],
    "comparability": [r"可比|换(?:动作|器械|握距|动作幅度)|(?:测量|训练)?特异性(?:原则)?", r"\b(?:comparab(?:le|ility)|specificity|different equipment)\b"],
    "population_scope": [
        r"(?:适用|研究|样本|纳入|涵盖|包括).{0,12}(?:人群|对象|年龄|参加者|参与者)|适用于谁|哪些人",
        r"健康成人[”\"」』]*的?(?:范围|定义)|(?:包含|包括|纳入).{0,8}(?:有|无|没有)?训练经验.{0,4}(?:人|者)",
        r"\b(?:population|people|participants?|samples?)\b.{0,35}\b(?:represent(?:ed|ative)?|includ(?:e[sd]?|ing)|exclud(?:e[sd]?|ing)|experienced|novices?|trained|untrained)\b",
        r"\b(?:review|stud(?:y|ies)|research|evidence)\b.{0,30}\b(?:population|representativeness|training experience)\b|\bapplicable to whom\b",
        r"\brepresentative\b.{0,65}\b(?:review|stud(?:y|ies)|sample)\b",
        r"(?:研究|样本|综述|证据).{0,24}(?:代表|训练经历|训练经验|初学者)|(?:受试者|参与者|参加者).{0,20}(?:经验|新手|初学)",
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
        r"(?:确认|证明|判定).{0,20}(?:就是|由于|因为).{0,25}(?:对我|有效|效果)|(?:证明|导致|因果|归因|归功于).{0,16}(?:个人|我|效果|进步|训练)|(?:个人|我|进步|效果).{0,16}(?:必然有效|保证有效|因果|归功于)|群体.{0,16}个人",
        r"\b(?:causal(?:ly)?|causation|caus(?:e[sd]?|ing)|guarantee[sd]?|individual effects?)\b",
        r"\b(?:workouts?|training|exercise|intervention)\b.{0,24}\b(?:produc(?:e[sd]?|ing)|led to|result(?:s|ed|ing)? in)\b.{0,20}\b(?:gains?|improvements?|benefits?|effects?)\b",
        r"\b(?:group|population|average)\b.{0,45}\b(?:predict(?:s|ed)?|establish(?:es|ed)?|apply|applies)\b.{0,40}\b(?:individual|person|everyone)\b",
    ],
    "goal_scope": [r"(?:力量|增肌|肌肥大|健康).{0,8}(?:目标|目的).{0,8}(?:区别|不同)|(?:目标|目的).{0,8}(?:力量|增肌|健康)", r"\b(?:different goals|strength versus hypertrophy|strength vs hypertrophy)\b"],
    "variation": [
        r"(?:线性|波动).{0,6}周期|周期(?:安排|计划)",
        r"(?:按|分|依|各|不同).{0,4}(?:阶段|周期|区块).{0,20}(?:组织|安排|调整|改变|变化|轮换|规划|增加)",
        r"\b(?:organi[sz](?:e[sd]?|ing|ation)|arrang(?:e[sd]?|ing|ement)|divid(?:e[sd]?|ing)|structur(?:e[sd]?|ing)|schedul(?:e[sd]?|ing))\b.{0,100}\b(?:in(?:to)?|across|by|over)\b.{0,20}\b(?:phases?|blocks?|cycles?)\b",
        r"\b(?:phase|block|cycle)[ -]based\b.{0,30}\b(?:training|program(?:me)?|schedule)\b",
        r"周期化|周期组织|变化方案|经常换动作|(?:训练|方案|计划).{0,12}(?:定期|经常|周期性).{0,6}(?:调整|改变|变化)",
        r"\b(?:periodi[sz](?:ation|e[sd]?|ing)|program(?:me)? variation|planned variation)\b",
        r"\b(?:vary|varies|varied|varying|variations?)\b.{0,25}\b(?:training|workouts?|program(?:me)?|schedule)\b",
        r"\b(?:training|workouts?|program(?:me)?|schedule)\b.{0,25}\b(?:vary|varies|varied|varying|variations?)\b",
    ],
    "practical_equivalence": [
        TWO_ONE_SIDED_TESTS,
        r"统计不显著|无统计学意义|(?:实用)?等效(?:性|检验|界|范围)?|统计.{0,10}未达显著|(?:未达(?:到)?|没有达到).{0,6}统计显著|未能拒绝.{0,6}(?:零|原)假设",
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
            if outcome == "capability_change" and term in {"一样", "unchanged"}:
                continue
            pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])" if term.isascii() else re.escape(term)
            if outcome == "progression_options" and term == "渐进":
                pattern = r"(?<!循序)渐进"
            if re.search(pattern, text):
                found.add(outcome)
                break
    for outcome, patterns in PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.add(outcome)
    if re.search(TRAINING, text) or re.search(r"(?<![a-z0-9])(?:e?1rm|rir)(?![a-z0-9])", text) or re.search(
        r"身体活动|活动量|\bphysical(?:ly inactive)?\b.{0,35}\bactivity\b", text
    ):
        found.add("resistance_training")
    return found


# These predicates bind requests to the organization of variables. The variables
# named as its objects or comparator are not independent questions by default.
ORGANIZATION_NECESSITY = (
    r"必要|必需|必须|非得|一定要|一定得|需要|需不需要|"
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


def covariance_method_context(text, named_subjects=None):
    estimator = bool(re.search(r"(?<![a-z0-9])(?:hc[0-5]?|hac|newey[ -]west)(?![a-z0-9])", text))
    statistical = bool(re.search(r"回归|协方差|标准误|异方差|自相关|置信区间|小样本|有限样本|样本量|渐近|覆盖率|误判率|统计方法|区间.{0,12}(?:准确|可靠|有效)|\b(?:regression|covariance|estimators?|standard errors?|confidence intervals?|heteros[ck]edasticity|autocorrelation)\b", text))
    statistical |= bool(re.search(r"(?<![a-z0-9])(?:hc[0-5]?|hac)\s*(?:区间|\bintervals?\b)", text))
    covariance = bool(re.search(r"协方差|\bcovariance\b", text))
    model = bool(re.search(r"回归|估计|\b(?:regression|estimat\w*)\b", text))
    dependent_errors = bool(re.search(r"异方差|同方差|自相关|误差.{0,10}(?:相关|独立)|\b(?:heteros[ck]edasticity|autocorrelat\w*|correlated errors?)\b", text))
    named = (named_subjects or {}).get("regression_covariance_scope") == "statistical_inference"
    options = bool(re.search(r"排序|带宽|滞后|预白化|\b(?:ordering|bandwidth|lag|prewhitening)\b", text))
    return (estimator and (statistical or options)) or (covariance and model) or (dependent_errors and model) or (named and (statistical or options))


def _method_topics(clause, method_context, equivalence_context, named_subjects):
    """Resolve method predicates, keeping a design or bound as a target only
    when it is asked about, rather than merely an operand of another method.
    """
    equivalent = bool(re.search(r"等效|\bequivalen(?:ce|t)\b", clause))
    non_significant = bool(re.search(
        r"不显著|未达显著|无统计学意义|(?:未达(?:到)?|没有达到).{0,6}统计显著|未能拒绝.{0,6}(?:零|原)假设|"
        r"(?:未|没有|没)(?:发现|检出|观察到|检测出).{0,24}显著的?(?:差异|差别|效果)|"
        r"\b(?:non[- ]?significant|statistically insignificant|absence of statistical significance)\b|"
        r"\bnot\b.{0,16}\bstatistically significant\b|\bfail(?:s|ed|ing)? to reject\b.{0,16}\bnull hypothesis\b|"
        r"\bp\s*(?:>|≥)\s*0?\.\d+", clause
    ))
    if non_significant and re.search(
        r"(?:效果|效应|作用).{0,6}(?:相同|一样|相等)|(?:相同|一样|相等)的?(?:效果|效应|作用)", clause
    ):
        equivalent = True
    negligible = bool(re.search(
        r"(?:差异|差别).{0,22}(?:没有实际重要性|不重要|实际意义很小)|"
        r"(?:没有|无).{0,5}(?:实质|实际|有意义).{0,6}(?:进步|变化|差异)|有意义的?(?:变化|差异)|"
        r"\bdiffer(?:ence|ences)?\b.{0,35}\b(?:unimportant|negligible|not meaningful)\b|"
        r"\b(?:no meaningful (?:change|progress)|meaningful change)\b", clause
    ))
    if not method_context:
        return {"practical_equivalence"} if equivalent else set()
    topics = set()
    logic = bool(re.search(TWO_ONE_SIDED_TESTS, clause))
    method_reference = equivalence_context and bool(re.search(
        r"(?:该|这个|上述|此)方法|\b(?:the|this|that) method\b", clause
    ))
    design = bool(re.search(
        r"独立.{0,8}(?:样本|组|观测)|平行组|重复测量|配对设计|个人时序|同一(?:个)?人.{0,12}(?:反复|重复)(?:测量|记录)|(?:研究|试验)设计.{0,12}(?:前提|条件|假设)|"
        r"\b(?:independent (?:parallel )?(?:groups?|samples?|observations?)|parallel groups?|"
        r"repeated (?:measures|measurements)|paired (?:designs?|samples?)|within[- ]subjects?|time series)\b", clause
    ))
    bounds = bool(re.search(
        r"\bsmallest effect size of interest\b|最小重要效应|小效应.{0,10}(?:分界|界值)|(?:等效界|等效范围).{0,20}(?:依据|设定|确定|选择|(?:怎么|怎样|如何).{0,6}[定设选])|"
        r"(?:依据|设(?:定|置)?|确定|选择).{0,20}(?:等效界|等效范围)|"
        r"\bequivalence margins?\b|\bsmall(?:est)?\b.{0,30}\beffects?\b.{0,45}\b(?:boundary|bounds?|meaningful|important|cut[- ]offs?)\b|"
        r"\b(?:justify|justified|choose|chosen|specify|specified|basis)\b.{0,30}\b(?:bounds?|margins?)\b", clause
    ))
    if equivalence_context and re.search(r"界值|边界|上下界", clause) and re.search(
        r"排除|界定|代表|含义|意义", clause
    ):
        bounds = True
    design = design and bool(equivalent or logic or method_reference
                             or named_subjects.get("equivalence_design_scope") == "statistical_inference")
    interval = bool(re.search(r"置信区间|区间|\bconfidence intervals?\b", clause)
                    and re.search(r"完全|落在|界内|跨过|超出|\b(?:entirely|within|inside|cross(?:es|ing)?|outside)\b", clause)
                    and (equivalent or logic or method_reference
                         or named_subjects.get("equivalence_test_logic") == "statistical_inference"))
    if design:
        topics.add("equivalence_design_scope")
    if bounds:
        topics.add("equivalence_margin_basis")
    test_criterion = re.search(
        r"(?:" + TWO_ONE_SIDED_TESTS + r").{0,20}(?:满足|通过|支持|判定|拒绝)|"
        r"\b(?:criteria|requirements)\b.{0,30}\b(?:tost|two one[- ]sided tests?)\b", clause)
    if interval or (logic and (not (design or bounds) or test_criterion
                              or re.search(r"逻辑|原理|\blogic\b", clause))):
        topics.add("equivalence_test_logic")
    if not topics:
        if equivalent or negligible:
            topics.add("practical_equivalence")
        elif non_significant:
            topics.add("non_significance_interpretation")
    return topics


def _personal_series(text):
    personal = re.search(r"我|个人|同一(?:个)?人|\b(?:my|individual|one person)\b", text)
    repeated = re.search(
        r"(?:连续|重复|反复).{0,10}(?:记录|测量|观测)|"
        r"(?:最近|近期).{0,4}(?:几|多|[二三四五六七八九十\d]+)次.{0,8}(?:表现|成绩|记录)|"
        r"\b(?:time series|(?:repeated|serial|consecutive) (?:training )?(?:measurements|records|observations))\b", text)
    split = re.search(r"(?:分|划).{0,6}前后.{0,5}(?:段|组)|\b(?:before and after|pre[- /]?post)\b", text)
    records = re.search(r"记录|测量|表现|成绩|\b(?:records|measurements|observations|performance)\b", text)
    return bool(personal and (repeated or (split and records)))


def _general_explanation_topics(text, named_subjects):
    """Require a domain object and a relation, not isolated topic words."""
    topics = set()
    resistance = bool(re.search(
        r"抗阻|力量训练|弹力带|居家训练|\b(?:resistance|strength) training\b|\b(?:resistance bands?|home training)\b", text))
    resistance |= bool(named_subjects.get("training_modality_adherence") == "resistance_training"
                       and re.search(r"训练|锻炼|\btraining\b", text))
    modality = re.search(r"形式|方式|偏好|坚持|依从|\b(?:modalit\w*|forms?|preferences?|adherence)\b", text)
    selection = re.search(r"选择|考虑|有效|改善|进步|收益|最优|作用|\b(?:choos\w*|select\w*|consider\w*|matter|effective|improv\w*|benefits?|optimal)\b", text)
    if resistance and modality and selection:
        topics.add("training_modality_adherence")
    aerobic = bool(re.search(r"有氧|快走|\b(?:aerobic|brisk walking)\b", text))
    accumulation = re.search(r"计入|算进|累计|积累|零碎|短时|每周.{0,8}(?:目标|总量)|\b(?:count\w*|accumulat\w*|short bouts?|weekly (?:activity )?(?:targets?|amounts?))\b", text)
    if aerobic and accumulation:
        topics.add("aerobic_activity_volume")
    muscle = bool(re.search(r"肌力活动|肌力训练|肌肉强化|\b(?:muscle[- ]strengthening|strength training)\b", text))
    flexibility = bool(re.search(r"拉伸|柔韧|\b(?:stretching|flexibility)\b", text))
    complementary = re.search(r"替代|代替|取代|需要|益处|作用|满足|\b(?:replace\w*|substitut\w*|need|benefits?|contribut\w*|satisf\w*|meet)\b", text)
    if sum((aerobic, muscle, flexibility)) >= 2 and complementary:
        topics.add("activity_type_complementarity")
    activity = re.search(ACTIVITY_CONTEXT + r"|(?:增加|提高)活动|\bactivity\b", text)
    order = re.search(r"先.{0,6}(?:增加|提高|加)|(?:增加|提高).{0,8}(?:先后|顺序)|\b(?:increase|increasing)\b.{0,20}\bfirst\b", text)
    if activity and order:
        topics.add("gradual_progression")
    return topics


def _activity_topics(clause, named_subjects):
    activity_context = bool(re.search(ACTIVITY_CONTEXT, clause))
    topics = set()
    if re.search(r"安全建议|安全指导|安全活动|\b(?:safety (?:advice|guidance|recommendations?)|active and safe)\b", clause) and re.search(
        r"年龄|适用|范围|儿童|老人|\b(?:ages?|scope|appl(?:y|ies|icable)|children|older adults)\b", clause
    ):
        topics.add("activity_safety_scope")
    if (re.search(r"成人|\badults?\b", clause) and re.search(
        r"年龄段|年龄范围|面向|对象|(?:哪些|什么|多大)年龄的?人|"
        r"\b(?:age range|scope|address|intended for)\b", clause
    )) or (named_subjects.get("adult_guideline_scope") == "physical_activity"
           and re.search(r"针对谁|面向谁|适用于谁|哪些人|\b(?:who|which population)\b", clause)):
        topics.add("adult_guideline_scope")
    if re.search(r"肌力活动|肌力训练|肌肉强化|\bmuscle[- ]strengthening\b", clause) and re.search(
        r"开始|初次|初学|\b(?:begin|begins|beginning|start|starts|starting|inactive)\b", clause
    ):
        topics.add("muscle_strengthening_start")
    if re.search(
        r"增量|增幅|增加的幅度|(?:同等|相同|不同)幅度|(?:小|大)幅(?:度)?(?:地)?增加|"
        r"(?:增加|增长|新增)的?(?:量|负担|比例|百分比)|"
        r"(?:多|增加).{0,8}(?:相同|同样|一样).{0,8}(?:分钟|时长|时间|活动量)|"
        r"\b(?:increments?|size of (?:the )?increase)\b", clause
    ):
        topics.add("activity_increment_size")
    if re.search(r"(?:增加|提高|进阶).{0,8}(?:速度|多快)|(?:增加|提高|进阶|加)得?(?:快|慢)|(?:速度|节奏).{0,8}(?:增加|提高)|\b(?:rate|pace|speed)\b.{0,25}\b(?:increase|increasing|progression)\b|\bhow (?:quickly|fast)\b.{0,40}\bincrease\b", clause):
        topics.add("progression_rate_factors")
    return {topic for topic in topics
            if activity_context or named_subjects.get(topic) == ACTIVITY_SUBJECTS[topic]}


def _semantic_roles(text, found, vocabulary, context):
    clauses = [clause for clause in re.split(REQUEST_BOUNDARY, text) if clause.strip()]
    named_subjects = context.get("named_source_task_subjects", {})
    explanation_topics = _general_explanation_topics(text, named_subjects)
    found |= explanation_topics
    method_context = bool(re.search(STATISTICAL_METHOD, text)) or covariance_method_context(text, named_subjects) or any(
        named_subjects.get(outcome) == "statistical_inference" for outcome in METHOD_OUTCOMES
    )
    equivalence_context = bool(re.search(TWO_ONE_SIDED_TESTS + r"|等效|\bequivalence\b", text))
    covariance_context = covariance_method_context(text, named_subjects)
    method_clauses, activity_clauses = [], []
    found -= METHOD_OUTCOMES
    for clause in clauses:
        method = _method_topics(clause, method_context, equivalence_context, named_subjects)
        if covariance_method_context(clause, named_subjects) or (covariance_context and re.search(
            r"(?<![a-z0-9])(?:hc[0-5]?|hac)(?![a-z0-9])|回归|误差|区间|\b(?:regression|errors?|intervals?)\b", clause
        )):
            method.add("regression_covariance_scope")
        activity = _activity_topics(clause, named_subjects)
        equipment_change = re.search(
            r"(?:跨品牌|不同(?:品牌|型号)?|各(?:种|个)).{0,8}(?:器械|训练设备|训练机)|(?:换|另).{0,10}品牌.{0,10}(?:机|器械|设备)", clause
        )
        load_conversion = re.search(
            r"(?:负重|配重|重量|负荷).{0,16}(?:换算|转换)|(?:换算|转换).{0,16}(?:负重|配重|重量|负荷|公斤|千克|kg)", clause
        )
        if equipment_change and load_conversion and not re.search(r"单位.{0,6}(?:换算|转换)", clause):
            found |= {"comparability", "resistance_training"}
        found |= method | activity
        if method:
            method_clauses.append(clause)
        if activity:
            activity_clauses.append(clause)
    if (covariance_context and re.search(r"区间|\bintervals?\b", text)
            and _personal_series(text)
            and re.search(r"停滞|平台期|\b(?:plateau(?:ed|ing)?|stagnation)\b", text)
            and re.search(r"判断|判定|确认|认定|确定|\b(?:determine|decide|infer|detect|confirm)\b", text)):
        # A covariance estimate alone does not define negligible change or
        # license a group-design method for a person's repeated observations.
        # These are explanation prerequisites, still subject to source filters;
        # no personal plateau decision or statistical parameter is authorized.
        found |= {"practical_equivalence", "equivalence_design_scope"}
    if (_personal_series(text) and method_context
            and found & {"practical_equivalence", "non_significance_interpretation", "equivalence_test_logic"}
            and re.search(r"对应|适用|直接|宣布|断言|说明|判断|判定|\b(?:apply|appropriate|establish|conclude|determine|decide)\b", text)):
        found.add("equivalence_design_scope")
    if method_clauses:
        independent = set()
        for clause in clauses:
            if clause not in method_clauses and re.search(VARIABLE_REQUEST, clause):
                independent |= _lexical_hits(clause, vocabulary) & ORGANIZED_VARIABLES
        found -= ORGANIZED_VARIABLES - independent
        if "regression_covariance_scope" in found and not any(
            "individual_error_bound" in _lexical_hits(clause, vocabulary)
            and clause not in method_clauses for clause in clauses
        ):
            found.discard("individual_error_bound")
    if activity_clauses:
        for generic in ("gradual_progression", "population_scope"):
            if generic not in explanation_topics and not any(generic in _lexical_hits(clause, vocabulary)
                       for clause in clauses if clause not in activity_clauses):
                found.discard(generic)
    if "resistance_training" in found or named_subjects.get("progression_options") == "resistance_training":
        if any(re.search(PROGRESSION_CHOICE, clause) and re.search(
            r"长期|持续|进步|进展|进阶|刺激", clause
        ) for clause in clauses):
            found.add("progression_options")
    if named_subjects.get("comparability") == "resistance_training" and any(re.search(
        r"力量[”\"」』]?.{0,12}(?:怎么|如何|怎样).{0,6}测|力量.{0,6}测量(?:方式|方法|定义)", clause
    ) for clause in clauses):
        found.add("comparability")
    if "failure_necessity" in found:
        definitions = [clause for clause in clauses
                       if "failure_necessity" in _lexical_hits(clause, vocabulary)
                       and re.search(r"定义|什么是|(?:具体)?指什么|是否就是|称为|什么(?:样的)?状态|\b(?:mean|means|definition|defined|refers to)\b", clause)]
        if definitions:
            found.add("failure_definition")
            if not any(re.search(ORGANIZATION_NECESSITY, clause) and (
                "failure_necessity" in _lexical_hits(clause, vocabulary)
                or (index > 0 and clauses[index - 1] in definitions and re.search(
                    r"(?:做到|练到|达到).{0,4}(?:那里|这(?:种|个)(?:状态|程度)|那(?:种|个)(?:状态|程度))", clause
                ))
            ) for index, clause in enumerate(clauses)):
                found.discard("failure_necessity")
        if not any("progression_options" in _lexical_hits(clause, vocabulary)
                   and "failure_necessity" not in _lexical_hits(clause, vocabulary)
                   and re.search(VARIABLE_REQUEST, clause) for clause in clauses):
            found.discard("progression_options")
    if "progression_necessity" in found and not re.search(
        r"因果|导致|我的|\b(?:causal|caused?|my|individual)\b", text
    ):
        found.discard("individual_effect")
    # Equality here constrains a study comparison; it is not a separate request
    # for set volume or a claim that the person's capacity has stopped changing.
    conditioned = re.sub(
        r"\b(?:with|when|holding)\b[^,;?.]{0,65}\b(?:equal|constant|matched)\b|"
        r"(?:在|如果|当)[^，；。？]{0,35}(?:一样|相等|相同|固定|不变)(?:时|的条件下|(?=[，,]))", "", text
    )
    if conditioned != text:
        retained = _lexical_hits(conditioned, vocabulary)
        found -= (ORGANIZED_VARIABLES & found) - retained
    return found


def lexical_concepts(question, vocabulary, context=None):
    text = question.lower()
    found = _semantic_roles(text, _lexical_hits(text, vocabulary), vocabulary, context or {})
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
    source_health_goal = context.get("named_source_task_goals", {}).get("frequency") == ["public_health"]
    health_boundary = bool(
        (source_health_goal or re.search(r"公共健康|总体健康|一般健康|最低健康|健康收益|健康益处|健康建议|\b(?:public|general) health\b", text))
        and re.search(r"力量|增肌|肌肥大|\b(?:strength|hypertrophy|muscle growth)\b", text)
        and re.search(r"证明|推出|意味着|代表|找到|确定|认定|就是|\b(?:prove|imply|establish|mean|determine)\b", text)
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
        separate_choices = any(
            not any(re.search(pattern, clause) for pattern in PATTERNS["progression_necessity"])
            and (re.search(PROGRESSION_CHOICE, clause) or (
                re.search(VARIABLE_REQUEST, clause)
                and any(re.search(pattern, clause) for pattern in PATTERNS["progression_options"])
            )) for clause in re.split(REQUEST_BOUNDARY, text)
        )
        if not separate_choices:
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
    if outcomes & METHOD_OUTCOMES and not re.search(r"分别|同时计算|also calculate|and separately", text):
        # A no-change endpoint can be the object of a statistical inference
        # question; it is not automatically a second personal trend estimate.
        outcomes.discard("capability_change")
        if not re.search(r"因果|导致|归因|归功于|确认.{0,8}就是|\b(?:causal(?:ly)?|causation|caus(?:e[sd]?|ing))\b", text):
            outcomes.discard("individual_effect")
    if {"individual_effect", "progression_options"} <= outcomes:
        independent_progression = any(
            "progression_options" in _lexical_hits(clause, {"progression_options": ["多做", "加重", "加次数"]})
            and not any(re.search(pattern, clause) for pattern in PATTERNS["individual_effect"])
            and re.search(VARIABLE_REQUEST, clause)
            for clause in re.split(REQUEST_BOUNDARY, text)
        )
        if not independent_progression:
            outcomes.discard("progression_options")
    if "effort_precision" in outcomes and "failure_necessity" in outcomes:
        if re.search(r"是否必须|一定要|必须.*力竭|非得|\bmust\b|\bnecessary\b", text) and not re.search(RESERVE_EFFORT + r"|(?:多少|几次|精确|量化).{0,8}余力|余力.{0,8}(?:多少|精确)|\bexact\b", text):
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
        "hypertrophy": r"增肌|肌肥大|长肌肉|\bhypertroph(?:y|ic)\b|\bmuscle growth\b",
        "strength": r"(?:提高|提升|增加|最大|以|对)力量|力量(?!训练)|长力气|\bstrength\b(?!\s+training)",
        "public_health": r"公共健康|总体健康|一般健康|\bpublic health\b|\bgeneral health\b",
        "power": r"爆发力|功率收益|\bpower (?:gains|outcomes?|goals?)\b",
    }.items():
        if re.search(pattern, text):
            goals.add(goal)
    if len(goals) > 1 and re.search(
        r"推及|推出|直接用于|套用|推广|也能|\b(?:carried over|carry over|generali[sz](?:e|ed)|extend(?:ed)?|imply|transfer)\b", text
    ):
        outcomes.add("goal_scope")
    if not goals and context.get("training_goal") in {"hypertrophy", "strength", "public_health", "power"}:
        goals.add(context["training_goal"])
    sensitive = {"progression_options", "failure_necessity", "effort_precision", "volume", "frequency", "rest"}
    labels = {"hypertrophy": "肌肥大", "strength": "力量", "public_health": "总体健康", "power": "功率"}
    parts = []
    for outcome in sorted(outcomes):
        part_subject = subject or context.get("named_source_task_subjects", {}).get(outcome)
        if outcome in METHOD_OUTCOMES:
            # "Equivalent" also describes currencies/files. Only a statistical
            # concept or an explicitly resolved source task supplies this subject.
            part_subject = ("statistical_inference" if re.search(STATISTICAL_METHOD, text) or covariance_method_context(text, context.get("named_source_task_subjects"))
                            else context.get("named_source_task_subjects", {}).get(outcome))
        if outcome in ACTIVITY_SUBJECTS:
            part_subject = (ACTIVITY_SUBJECTS[outcome] if re.search(ACTIVITY_CONTEXT, text)
                            else context.get("named_source_task_subjects", {}).get(outcome))
        if outcome == "training_modality_adherence":
            part_subject = "resistance_training"
        part_goals = {"public_health"} if health_boundary and outcome == "frequency" else goals
        for goal in sorted(part_goals) if outcome in sensitive and part_goals else [None]:
            parts.append({"part_id": outcome + (":" + goal if goal else ""),
                "label": LABELS[outcome] + ("（" + labels[goal] + "目标）" if goal else ""),
                "subject": part_subject,
                "outcome": outcome, "requested_relation": RELATIONS[outcome],
                **({"requested_goal": goal} if goal else {})})
    return parts
