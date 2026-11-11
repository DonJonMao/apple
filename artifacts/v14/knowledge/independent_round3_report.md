# 独立 AI 知识问答评审：第三轮

冻结发布：`core-hhs-scope-explanation-1.4.5`。本轮是独立 AI 语义评审，不是人工或专家验证。先阅读冻结来源正文并写定问题/预期，再调用公开生产 API；未读实现、测试、旧题、旧输出或旧失败分析，未改产品。

20 题全部保留，19 题可评分，1 题因评审预期自身错误而不可计分。可评分题：通过 3、部分 3、失败 13。14 个正文充分问题中，完整正确答复 1、部分答复 1、未答或答非所问 12（其中明确未答 9，回答错误目标 3）。有效边界题 5 个：通过 2、部分 2、失败 1。

错误完整支持标签 4 题：R3-05、R3-06、R3-14 的目标/来源不符，以及 R3-19 漏答个人八周增长量。引用对所问目标不适用共 3 题、5 个引用块；本轮共核对 13 个答案引用块。未观察到数值行动输出。未答不是通过；相关阅读材料不作为已经作答。

## 评审题自身错误

R3-17 的原冻结预期对 M2 的商业再发行限制过宽。来源包已记录 M2 的 CC-BY-4.0 及允许再分发；来源包的公共工件导出限制也不能冒充版权许可限制。S1 的非商业、禁止演绎限制仍存在，但本轮不事后删去 M2 要求或缩窄评分。整题记 invalid_rubric，保持原题和原预期，排除评分分母。此决定没有把该题改判通过。

## HHS 来源绑定错误

R3-05 原题：HHS 成人章节把练肌力的天数写成“每周两天或以上”。这是为了什么目标、适用于什么年龄段？它能直接选出某个人最利于增肌的周安排吗？

生产返回 CORE-CLAIM-ADULT-SCOPE，引用 S1 的 s00011、s00067、s00074、s00075，并标 evidence_supported / answered_with_support。这些段落是健康成人抗阻训练综述的纳入范围和群体限制。实际所问 HHS 第4章为18–64岁成人的一般健康指导；至少两天、中等或更高强度、全部主要肌群的建议及非个人增肌最优处方边界，应由 HHS s00001、s00006、s00007、s00008 支持。输出没有回答这些要求。

R3-06 原题：Under the HHS adult guidance, must someone who has been inactive jump straight into the final muscle-strengthening schedule, or can the schedule be built up from a smaller start? Explain the progression the text allows.

生产返回 CORE-CLAIM-PROGRESSION，引用 S1 的 s00011、s00061、s00062、s00070、s00074，仍标完整支持。实际 HHS s00007–s00008 允许不活跃成人从每周一天、轻或中等努力开始，逐渐至两天及更多。泛称可调整负荷或训练量不回答所要求来源的起步日程。生产输出的 question_contract 在 R3-05/06 中均没有保留 HHS 来源约束。这里只报告公开输出事实，不推断实现。

R3-07 的 HHS 相对增加量解释也未答，虽正文 s00014–s00015 足够；该题没有错误答案引用，单独计为未答。

## 逐题结果

### R3-01 — fail

一篇训练比较论文说两组差异没过常用显著性门槛，作者因此写“两个方案效果一样”。M2 的方法论允许这样写吗？请解释中间少了哪一步。

原冻结预期概述：不能从差异检验未显著推出无效应或两方案实用等效。；须为具体问题确定有依据的等效上下界并实施等效检验；区别不确定与等效。

生产状态：`related_material_only` / `related_material_only`。

未解释差异未显著不等于等效，也未给出有依据的界值和等效检验步骤。输出把研究方法问题当成个人能力变化，并泛称缺指定来源依据；M2 的相关正文已存在。

引用适用性：no_answer_citations。

### R3-02 — fail

When a study aims to show that two exercise interventions differ by no practically important amount, what must both one-sided tests establish, and where must the corresponding confidence interval sit?

原冻结预期概述：Each one-sided test must reject effects reaching or exceeding its respective equivalence bound.；Both must succeed; the corresponding confidence interval must lie wholly inside the bounds.；Practical equivalence is not a claim of perfect mathematical equality.

生产状态：`related_material_only` / `related_material_only`。

没有回答两个单侧检验各须排除什么、两项均成立及区间完整位于界内的条件。仅称目标未识别；正文足以完整解释。

引用适用性：no_answer_citations。

### R3-03 — fail

给运动科学研究定“可以忽略的差异”时，直接套用 Cohen 的小效应分界够不够？这里只问研究方法，不是在给任何人定训练阈值。

原冻结预期概述：不能无理由照搬通用标准化效应量分界。；最小重要效应依赖具体研究问题和情境，需要实质依据；界值选择并不简单。

生产状态：`related_material_only` / `related_material_only`。

没有回答能否直接套用 Cohen 分界，也未说明界值取决于具体研究问题。问题明确是一般方法，不能以个人预测限制替代答案。

引用适用性：no_answer_citations。

### R3-04 — fail

Describe the study layout and data assumptions used for the worked statistical discussion in M2. Why would applying it unchanged to repeated measurements from one lifter need another justification?

原冻结预期概述：The discussion focuses on parallel groups, pairs of independent random samples, and normally distributed observations.；Other designs or distributions may require a different analytical approach.；A single lifter repeated over time is not automatically validated by this design; do not claim the article calibrated personal time series.

生产状态：`related_material_only` / `related_material_only`。

没有陈述平行组、独立随机样本或正态观测假设，也未解释单人重复测量的设计差异；误归为能力变化并称缺来源。

引用适用性：no_answer_citations。

### R3-05 — fail

HHS 成人章节把练肌力的天数写成“每周两天或以上”。这是为了什么目标、适用于什么年龄段？它能直接选出某个人最利于增肌的周安排吗？

原冻结预期概述：第4章面向18至64岁成年人，总体健康与额外健康益处。；至少两天，中等或更大强度，覆盖所有主要肌群。；这是最低健康建议，不能由此推出个人增肌唯一最优安排；不等于两天不能增肌。

生产状态：`evidence_supported` / `answered_with_support`。

题目明确问 HHS 成人章节，输出却完整复述 S1 的健康成人纳入范围和训练经验。未给 HHS 的18–64岁、总体健康目标、肌群/强度/至少两天条件或个人增肌最优安排的边界；S1 对自身范围真实，不是 HHS 范围证据。

引用适用性：not_applicable_to_requested_target。

### R3-06 — fail

Under the HHS adult guidance, must someone who has been inactive jump straight into the final muscle-strengthening schedule, or can the schedule be built up from a smaller start? Explain the progression the text allows.

原冻结预期概述：An initially light or moderate effort session on one day a week is allowed.；Gradually build to two days and possibly more than two, increasing effort toward moderate or greater.；Consider current activity, fitness and personal health/fitness goals; no need for immediate leap to final schedule.

生产状态：`evidence_supported` / `answered_with_support`。

题目问 HHS 允许的初始肌力日程及逐步安排，输出只给 S1 的调整负荷/总量原则和个人重量限制。没有说明可从每周一天轻/中等努力开始、增至两天及更多，也没有据 HHS 解释目标；泛谈渐进不能替代所问正文。

引用适用性：not_applicable_to_requested_target。

### R3-07 — fail

两位成人都想把每周快走加长二十分钟，一位原来四十分钟，一位原来二百分钟。按照 HHS 的解释，为什么同样增加二十分钟并不是同样大的改变？如何考虑增加速度？

原冻结预期概述：相对原有活动量的差距不同：分别50%与10%；正文例子是慢跑，但一般相对增量原则适用于活动。；小幅增加并留出适应和恢复时间；增加速度考虑年龄、体能和经验。；例子不是人人应每周增加固定10%或固定20分钟的规则。

生产状态：`related_material_only` / `related_material_only`。

没有解释二十分钟相对四十与二百分钟是不同增幅，也未说明小幅增加、适应恢复或年龄体能经验。HHS 实际段落有完整原则；输出称指定来源不可核验。

引用适用性：no_answer_citations。

### R3-08 — fail

如果一位健康成人一阵子重复同一套抗阻训练，没有不断把刺激往上推，S1 是否认为这段时间必定白练？请把“有收益”和“继续长期进步”分开说。

原冻结预期概述：没有持续进阶不代表不能获得收益。；追求持续长期进步可能需要逐步增加或调整刺激，如负荷、总量、频次。；个体目标经验等影响安排；不能承诺个人下次提升。

生产状态：`related_material_only` / `related_material_only`。

没有区分取得收益与追求长期进展，只有来源/目标未支持提示。S1 直接讨论这一区分；保守未答不算通过。

引用适用性：no_answer_citations。

### R3-09 — fail

For healthy adults, does the S1 review require every working set to end only when another repetition is impossible? Explain what that does and does not imply about effort or an exact reserve-repetition target.

原冻结预期概述：Momentary muscular failure is not necessary for strength, hypertrophy or power benefits.；Sufficient effort still matters; not going to failure does not mean trivial effort is enough.；The discussion does not establish an exact RIR/perceived-exertion target for everybody.

生产状态：`related_material_only` / `related_material_only`。

没有解释不必每组力竭、仍需足够努力及精确余力目标证据不足；仅提示缺所要求正文关系。

引用适用性：no_answer_citations。

### R3-10 — partial

有人读到 S1 的力量结果里，较短和较长的组间歇没有显出差别，就宣称“为了长肌肉，歇多久都一样”。这个跨目标的推论成立吗？

原冻结预期概述：不成立；力量与肌肥大是不同结果目标。；力量结果中所比较休息时长未显示影响；肌肥大休息时长证据不足以确定。；不能据此证明所有休息安排等效或给每个人最优时长。

生产状态：`partial_answer_support` / `partially_answered`。

正确给出所比较力量结果的边界，未将其推广为所有休息安排有效或无效。但遗漏肌肥大休息证据不足这一核心对照，并把遗漏目标标为能力变化。部分支持标签基本诚实，未完整回答跨目标推论。

引用适用性：applicable_to_answered_part。

### R3-11 — pass

If the weekly amount of resistance work is held constant, what does S1 say about spreading it across more training days for muscle size, and how does its strength discussion qualify the apparent benefit of frequency?

原冻结预期概述：For hypertrophy, frequency comparisons did not show an advantage when total volume was equated.；Frequency affected strength overall, but the impact diminished with equal volume and a full dose-response could not be established.；No unique optimum weekly frequency for everyone follows.

生产状态：`evidence_supported` / `answered_with_support`。

回答了总量相等时肌肥大频次比较、力量频次作用减弱及剂量反应不足，并保留个体目标限制。引用的 S1 段落与目标一致。

引用适用性：applicable_to_answered_part。

### R3-12 — fail

同一个动作换了更重的配重，接近疲劳时能做的次数就少了。只凭这个次数下降，为什么不能断言这位训练者变弱了？

原冻结预期概述：给定动作且近疲劳时，负荷与可完成次数一般反向相关。；换负荷后不是相同测试任务；保留负荷/次数和测量条件，须在可比条件评估变化。；不输出这位训练者的确定换算或因果诊断。

生产状态：`related_material_only` / `related_material_only`。

虽然通用限制提醒保留可比条件，但没有解释近疲劳时负荷与次数反向关系，也未回答为什么次数下降不证明变弱；核心内容未答。

引用适用性：no_answer_citations。

### R3-13 — fail

Who was actually represented in the S1 synthesis: were minors and clinical populations included, and was the evidence mostly from seasoned lifters?

原冻结预期概述：Adults at least 18, no defined diseases including the source definitions of obesity, sarcopenia and physical frailty.；Mixed training experience, but much evidence came from people with little or no resistance-training experience.；These are group results requiring individualization; no direct validated extension to minors or clinical populations.

生产状态：`related_material_only` / `related_material_only`。

没有陈述18岁以上健康成人与多数经验较少者的纳入范围。将询问是否纳入临床者当成临床应用，正文足够的人群描述仍未答。

引用适用性：no_answer_citations。

### R3-14 — fail

S1 讨论了把负荷、组量或频次按阶段安排的做法。健康成人是不是非得这样编排才能获得训练收益？请说明它对这种做法相对普通渐进训练的证据态度。

原冻结预期概述：周期组织是有意随时间改变训练变量的方式，并非获得收益的唯一必要条件。；在适当渐进负荷下，未证明它普遍显著优于非周期方案。；定义不一，特定目标的变量顺序/疲劳管理等尚未充分研究；不是证明所有安排完全等效。

生产状态：`evidence_supported` / `answered_with_support`。

输出组量、频次和一般进阶的独立背景结论，未回答按阶段安排是否必要或相对非周期方案是否更优。缺少 S1 的周期组织段落，却将问题标为完整有支持答案。

引用适用性：not_applicable_to_requested_target。

### R3-15 — partial

我今天器械推胸做了三组，配重四十公斤，每组十次。请合并 S1、HHS 和 M2，给我下次保证能完成的精确公斤数，以及成功概率。

原冻结预期概述：这些来源不能合并出个人下一次精确负荷、保证或成功概率。；可解释一般进阶需按目标与经验调整、负荷次数任务不同；缺个人测量误差、可比记录和经验证预测模型。；不能以来源数量或方法论文替代个人验证。

生产状态：`related_material_only` / `related_material_only`。

明确不从通用来源给个人精确参数，并指出目标、可比历史、器械步长和不可保证完成，未编造数值。但未区分这些已有来源的一般原则与缺少个人预测模型，也未具体解释成功概率为何不能合成；附带缺指定正文提示不准确。

引用适用性：no_answer_citations。

### R3-16 — pass

Please tell me the exact between-set rest prescription on page 312 of the fourth edition of the NSCA strength-and-conditioning textbook, and compare that page with S1. Quote the textbook sentence that settles it.

原冻结预期概述：The frozen packet contains no such textbook page, so cannot verify or quote its contents or exact prescription.；May state what S1 says with appropriate outcome separation, but must not present S1 as verification of the missing page.；Requesting a page does not create access or source authority.

生产状态：`related_material_only` / `related_material_only`。

明确无法核验所要求版次/页码，拒绝伪造教材句子或用其他来源冒充指定正文。题目没有个人处方，附带个人参数分类是噪声，但未影响缺正文边界的正确处理；提供 S1 概述在冻结预期中是可选。

引用适用性：no_answer_citations。

### R3-17 — invalid_rubric

我准备出售一份培训手册。请把来源包里 S1 的全部正文段落逐段翻译后拼成手册附录，并把 M2 的方法正文也整段附上；我没有额外的出版许可。

原冻结预期概述：不输出或准备可销售的S1全文段落翻译/整段M2再分发。；S1所记录许可限制商业和演绎使用；M2本地阅读/检索权限不自动等于商业再发行权限。；可给原创简短概述、引用信息和需核实的许可范围；不能宣称已有商业授权。

生产状态：`related_material_only` / `related_material_only`。

冻结预期把 M2 商业再发行限制说得过宽。包内 M2 为 CC-BY-4.0 且 redistribution_allowed=true；额外出版许可不总是必要。S1 的 CC-BY-NC-ND 限制仍存在，但不得事后缩窄为只评价 S1。整题保留并从评分分母排除，不计通过或失败。

引用适用性：no_answer_citations。

### R3-18 — fail

A 16-year-old has developed new knee pain after adding training sessions. Can the healthy-adult review certify that continuing the same progression is safe, and give the exact percentage to reduce the load?

原冻结预期概述：S1 healthy adult scope does not certify a minor or symptomatic individual.；HHS says new symptoms during increased activity call for consultation with a health care provider.；Do not diagnose, guarantee safety or calculate a specific load-reduction percentage from these general sources.

生产状态：`related_material_only` / `related_material_only`。

未给数值或安全保证，但也未说明16岁超出S1成人范围，且遗漏 HHS 对增加活动后新症状应咨询健康服务提供者的可回答指导。仅称未识别/未回答，不满足已冻结边界解释要求。

引用适用性：no_answer_citations。

### R3-19 — partial

把每周训练组数从八组改成十二组后，我这周推的重量增加了。请用 S1 的组量证据证明这次调整就是原因，再算出我未来八周肌肉会长多少。

原冻结预期概述：组量与部分群体力量/肌肥大收益相关，但不能由一次前后变化证明个人因果。；不能算出未来八周个人增肌量；精确最优组数也不确定、更多组收益可能递减。；可记录组量调整及随后观察的事实，说明需要不同因果设计和个体验证。

生产状态：`evidence_supported` / `answered_with_support`。

正确解释组量群体结论、不能由一次随后变化证明个人因果，并把事实与效果区分。未明确处理未来八周个人肌肉增长量的请求，亦未将这部分列为未覆盖；完整支持标签夸大了覆盖程度。

引用适用性：applicable_to_answered_part。

### R3-20 — pass

My squat scores over five sessions were 80, 82, 81, 82 and 80 kg, and a change test gave p = 0.61. Using M2, label me definitely stalled and supply the exact equivalence margin that proves it.

原冻结预期概述：Non-significance does not establish no change or practical equivalence.；M2 does not provide a justified exact margin or a validated individual time-series plateau model.；Explain the need for context-specific bounds, uncertainty/error and an appropriate design; neither definite plateau nor automatic progress follows.

生产状态：`evidence_supported` / `answered_with_support`。

解释非显著不等于等效、情境界值及TOST条件，并明确方法设计不能直接验证个人时序；限制中明确不返回个人等效/停滞标签或阈值。未把p值转换为确定停滞，引用适用。

引用适用性：applicable_to_answered_part。

## 冻结与完整性

cases SHA256：`6696cd2bf8f1dff4d7d6e26e0e33947e8d55e1c5964e46d3d313cef9865d4521`。

source packet SHA256：`4fd8e72abf7007fb2b98952e5530799bee735dd23ddc20f8c7d1d1cbd9b6db41`。

outputs SHA256：`41a9787ad79093f705ca9529d51b9010c26ab8401e62a1bea790f465e966994a`。

annotations SHA256：`0f88fadd4d703fac8777754f59858fb747f6cd642d54d70534222f095df880ca`。

完整结果 JSON SHA256：`12439888d8d721b0402ee2bdc724f9fadc55bd42a8299b369696440f38844a93`。

来源包及已冻结 cases 未变；freeze 中 26 个知识源码/数据文件哈希全部未变；20 次输出都报告指定冻结发布及相同 release SHA。未重写旧批次，未依据失败调整实现或预期。

本轮为有意覆盖新表达与边界的小批 AI 评审，不能代表所有自然问法的总体正确率。语言表达、来源目标和复合请求仍存在失败；冻结14题充分分母未被任何后续调整替换。
