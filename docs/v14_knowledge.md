# v1.4 知识、应用规则与问答验收

首次修复以 `912aefc93b9bd9c1cebf297a10728c69c827e266` 为基线；`dd8e2e1` 后继续逐项补齐可完成的来源与规则合同。公开工件位于
`artifacts/v14/knowledge/`。真实正文、版权证明缓存、未投影检索输出和独立评审阅读包均留在 `.local/`。

## 真实完成范围

已登记 8 个核心来源、21 个原规则主题；当前 **1.4.6 发布包含28个SourceClaim和28个ApplicationRule**。主张分区为23个core核心主张、5个research研究方法补充主张。补充论文没有因此变成核心教材或核心来源骨干。
当前发布 ID 为 `core-source-explanations-1.4.6`，公开清单为 [release-1.4.6.json](../artifacts/v14/knowledge/release-1.4.6.json)。前序HHS发布`core-hhs-scope-explanation-1.4.5`、M2发布`core-method-explanation-1.4.4`、原 `release.json` 和17主张发布 `core-personal-trial-1.4.3` 均保持冻结。
其中4项候选仍是双进阶、同负荷增加次数试验、较重负荷/较少次数试验、策略复盘中的试验选择；另有19项来源解释/讨论和5项记录描述/执行反馈/报告合同。
新增来源解释规则不替代原21主题中的4项个人统计推断规则；后者仍缺相应原始方法材料、个人界值或任务校准。活动合同数不能等同全部科学主题已完备。
首次6主张/4规则的`1.4.1`发布和中间`1.4.2`发布均保留；目标范围改进通过新的不可变版本完成。
`source_rule_feature_matrix.csv` 逐项区分相关解释主张、尚缺的主题和应用核对。
原21主题覆盖表保留1.4.3时点，各批独立评测保留各自冻结时的来源与实现，不因新发布回填。1.4.4新增范围和验证单列于`method_explanation-1.4.4.json`、`method-release-verification.json`及`method-verification.xml`；1.4.6的计数、能力边界及67项既有文件哈希核验见 [发布核验](../artifacts/v14/knowledge/source-topics-release-verification-1.4.6.json)。

旧版 11 张 TheoryCard 继续为 `needs_review`；没有改写其历史审核、冒充专家，或把旧解释权限提升成候选权限。
新增 SourceClaim 只授权相应解释；产品如何把一般原则变成一次可选择任务，另由 ApplicationRule 保存版本、来源、数值来源、退出条件与后续观察。
规则审阅者真实记录为 `ai_assisted`，独立人工/专家审定数量为 0。软件通过不证明个人效果。

| 核心来源 | 本轮真实材料与状态 |
| --- | --- |
| ACSM 2026 抗阻训练立场，S1 | 复用既有规范身份与原始全文；实际进一步精读段11、24–26、59–76，覆盖初始获益/持续进展、特异性、负荷次数、不同目标、努力及证据局限。另核对表2的力竭定义行、表头及脚注；当前15个主张引用S1，其中1个同时引用HHS；CC-BY-NC-ND仅按已声明本地非商业用途使用。|
| HHS《Physical Activity Guidelines for Americans》第 2 版 | 官方完整 PDF 118 页已取得；解析第4、7章共18页，实际读取正文页56–63、88–93。只使用联邦正文，排除照片/图示；当前9个主张引用HHS，其中1个跨来源。公共频次明确绑定第4章18–64岁成人范围。|
| 中国全民健身指南 2017 | 官方公开正文已取得，但未确立重用许可；保留本地原件与待审状态，不进入可用证据。|
| 中国身体活动指南 2021 | 期刊公开指南摘录已取得，明确保留“摘录”范围；版权待审，不当作完整指南或可用证据。|
| NSCA 第 5 版、ACSM GETP 第 12 版、肌肥大第 3 版、Neumann 第 4 版 | 实际尝试协会/出版社官方路径。前三类遇 403/429；Neumann 产品页返回 200，但未发现目标正文或可用章节样本。未取得的章节保持缺口。|

详细 HTTP 尝试与未取得原因见 `paid_source_attempts.json`。`core_sources_manifest.json` 将原始规划状态放入
`planning_status_declarations`，另列实际 `runtime_status`，避免把计划与已完成混算。
同一 S1 的核心别名和多个解析版本不增加独立来源数。书籍以 edition/manifestation/ISBN 区分版本及译本，不互套页码。

本轮另经此前未尝试的官方入口取得 N1：Zeileis (2004), *Econometric Computing with HC and HAC Covariance Matrix Estimators*,
JSS 11(10), 1–17，DOI `10.18637/jss.v011.i10`。官方文章页明确文章采用 CC-BY 3.0，和另列 GPL 的软件许可区分。
完整17页已实际读取，并以独立版本`N1:fulltext:194d6fc4b1e58f6312bc:pdfplumber-layout-n1-1.4.0`解析745个定位片段入本地库；
原PDF SHA256为`194d6fc4b1e58f6312bcd0eaff136e12ffc9d272165413af6e5316e99931c053`。原文不进入公开工件。
N1当前有0个活动来源主张，不加入本轮冻结发布或问答候选；材料取得、方法阅读和应用激活分别计数。
其方法范围是HC/HAC协方差估计、相关模型条件、核/带宽/滞后与渐近推断，应用示例为经济数据；它不提供个人训练重测误差、实用等效界值或任意反复查看保证。
PDF公式提取含字符/顺序瑕疵，公式和数值表格尚未核准；有限方法解释仅作为下一发布的候选记录。
详见`N1_method_review.json`，可用`tools/v14_import_method_source.py`离线复现身份/许可/解析与冻结文件核验。
N2官方Project Euclid入口虽返回HTTP 200，实际是Incapsula拦截页，未取得文章，也未绕过；见`method_source_round2.json`。

第三轮通过作者机构 TU/e 正式仓储取得 M2：Mazzolari、Porcelli、Bishop、Lakens (2022)，
*Myths and methodologies: The use of equivalence and non-inferiority tests for interventional studies in exercise physiology and sport science*，
Experimental Physiology 107(3):201–212，DOI `10.1113/EP090171`。仓储封面、正式文章身份及 Crossref 正式版许可交叉核对为 CC-BY 4.0。
PDF 共974407字节、13文件页（1页仓储封面和12页正文），SHA256为`0a7abf1ff40f4fad98efe97afa42b7187a7d893ac55847596403999afdb857e0`。
全部正文已实际阅读，六处方法区域以`M2:fulltext:0a7abf1ff40f4fad98ef:pdfplumber-reviewed-m2-regions-1.4.0`正式入库；
每处保留文件页索引、印刷页、坐标及文本哈希，封面不作为证据。公开工件只有元数据、定位、哈希和原创概述，正文留在本地。

`CORE-CLAIM-EQUIVALENCE-METHOD:1.4.4` 的三段回答分别绑定：不显著不能证明等效（s00001）；
情境化、有依据的上下界与TOST（s00000、s00002、s00003）；独立随机正态平行组研究的设计限制（s00004、s00005）。
这些片段位于印刷页203、204、208、209。`RULE-PRACTICAL-EQUIVALENCE-EXPLANATION:1.4.4`仅授予`source_explanation`，
没有个人阈值、等效结论、停滞标签或训练候选权限。M2保持`research`补充分区；核心加研究模式可使用该解释，纯核心模式不使用。
来源核对和应用核对均真实记录为`ai_assisted`，独立人工/专家审核为0；没有个人校准也可解释一般方法，但不能据此声称个人方法有效。
导入与发布分别执行，旧17项发布和所有独立评测输入输出均核验不变。详见`M2_method_review.json`、`method_explanation-1.4.4.json`和`method_source_round3.json`。

同轮取得 N2 官方 arXiv `1810.08240v9` 作者仓储稿，48页中实际读取1–5和16–22页。其`arXiv-nonexclusive-distrib-1.0`只确立向arXiv授予分发权，
没有推定下游索引或公开重用授权，也不冒充2021年期刊正式版；未导入生产语料或激活主张，见`N2_repository_review.json`。
四本付费教材的新官方入口只补得书目、目录、访谈或其他书的改编节选，目标版次章节正文仍未取得；没有重试或绕过受阻端点。

HHS新增`CORE-CLAIM-HHS-GOAL-SCOPE:1.4.5`，逐项复核第4章印刷页56、57、61–63及五处片段哈希，只解释18–64岁成人的一般健康目标、每周至少两天肌力活动的最低频次与个体优化边界。它不提供个人增肌最优频率或新的候选权限。复跑HHS新发布和M2旧发布时，48项已冻结文件的哈希保持不变，见`hhs-scope-release-verification.json`。

## 1.4.6 新增九个独立解释主题

本轮重新读取既有合法来源中的相关原文，将此前混在宽泛回答中的主题分开建模，并新增来源表格中的非数值定义。范围核对见 [逐来源阅读回执](../artifacts/v14/knowledge/source_topic_review-1.4.6.json)，九组主张/应用合同见 [新增解释清单](../artifacts/v14/knowledge/source_explanations-1.4.6.json)。

|来源与分区|新增主题|明确边界|
|---|---|---|
|M2，research，4项|不显著不等于无效或等效；TOST与对应置信区间；情境化等效界值；独立平行组示例的设计范围。|实际核对印刷页203、204、208、209及页204区间公式；只解释一般方法，不授予个人等效结论、个人训练时序算法或停滞标签。|
|HHS，core，4项|第4章18–64岁成人范围；肌力活动从较低起点开始；相对已有活动量渐进增加；年龄、体能和既往经验对增加速度的考虑。|只使用第4、7章已核对的联邦正文；一般健康建议不推导个人最优频率、固定周增比例或下一次公斤数。|
|S1，core，1项|表2对力竭的定义：重复至不能继续完成向心运动。|核对定义列、行及脚注；术语定义与“是否必须练至力竭”分别回答，不激活其他数值表格参数。|

九项均只授予`source_explanation`；4项候选权限及5项记录合同保持原边界。M2当前合计5项研究解释，纯核心模式仍不使用；新发布没有新增独立人工/专家审阅或个人校准。`source-topics-verification-1.4.6.xml`是实施者软件回归，不能作为新的独立语义通过率。既有独立题、输出和标签继续保留。

用户已明确暂时没有四本教材授权副本。其目标章节与受影响主题继续按缺口记录；本轮不再将此当作阻止其他软件修复的条件。

## 权限与适用范围

`personal-trial-policy-1.4.0` 允许真实 AI 辅助来源核对及应用核对，授权有限的解释、计划候选和一次试验候选。
它不以“尚无人体验证”阻断所有个人健身试用，也不授予个人成功预测、因果疗效、诊断或临床处方权限。
生产环境拒绝 `synthetic_fixture` 来源/规则作为权威。候选还要经过统一科学服务的数据、症状、计划、历史可比性及器械可行性门禁。

4 个活动规则所需最低声明是成年年龄、健康成人自报范围、训练目标、训练经历、所选策略。
它们不依赖睡眠/HRV。缺少信息与范围不符分别留下条件问题；当前疼痛和技术限制仍由实际上下文阻断升级。
`permitted_actions` 明确到 `double_progression`、`repetition_progression`、`heavier_lower_reps`，不从宽泛能力名推断动作权限。
负荷来自已确认器械档位，次数来自用户计划/任务；没有把文献一般原则转换为个人唯一最优数字。

新增 `record-description-policy-1.4.0` 只允许 description、task_followup、report，依据已核对的数据身份、时间可见性、目标版本和实现测试；它不要求为“计划与实际差异”等账目事实假造科学主张。
该策略明确禁止科学权威、数值训练候选、个人预测和因果效果。记录规则和来源解释规则均不会进入 `reviewed_principles` 候选权限。
1.4.3冻结的QAL-09仍分别报告12/16个有活动的有限来源合同与5/5个记录合同，不能将后者计成科学证据覆盖；该历史分母未因1.4.6新增解释而重写。

SourceClaim、已审规则和发布清单不可原地改正文；替换需新版本。
撤回、待复核或来源更正会阻断当前使用，包括指定旧 release 时的重新查询。旧发布内容及旧建议快照保持原样。
这同时保留“当时用了什么”与“现在还能否使用”的区别。

指定`release_id`的问答分别读取`core_release`与`theory_release`：仅有核心快照时排除未冻结的旧TheoryCard，
仅有旧理论快照时排除后来新增的SourceClaim，同ID同时存在两种快照时只合并各自冻结成员。
核心主张按`claim_id/version`精确筛选；当前撤销、来源更正或撤回仍会阻断使用，历史快照不能恢复科学有效状态。
两个表都无该ID时明确报`unknown release`，`retrieval.release_scope`报告分区选择及快照SHA。
该缺陷先由7项失败用例复现，修复后全部通过；真实只读检查确认1.4.3不含M2新主张、1.4.4可使用该解释，见`release-query-production-check.json`及`release-query-*.xml`。

新增和升级的来源范围：力量休息声明`CORE-CLAIM-REST:1.4.3`明确`goal=strength`，肌肥大休息另有`CORE-CLAIM-REST-HYPERTROPHY:1.4.2`说明证据不足；
`CORE-CLAIM-FREQUENCY-VOLUME:1.4.3`明确`applicable_goals=[strength,hypertrophy]`，与HHS公共健康频次不互相替代。
旧6个通用范围声明及中间频次声明留存原文与审核，当前置`needs_review`，新版本接替；候选4规则新版仍只获原来的三种动作权限。
核心书目已登记带版次的完整`query_names`；裸ACSM/NSCA不暗定某本书或版次。

## 本轮问题识别与缺项状态

仅提机构名称时，当前检索限定该机构已登记的作品范围，不自动指定一本书或一个版次；“教材”和“指南”进一步限定文献类型。完整书名、具体版次/章节仍单独核对，不能用同一机构的公开立场声明替代尚缺的教材正文。印刷页与PDF文件页分别核对真实定位，正文提及某页不能代替该页。

问题识别区分非显著解释、等效逻辑/界值/设计、指南年龄范围、活动起步/增量/速度和力竭定义。范围询问与将建议用于该人群分开，背景中的组数、频次或年龄不自动成为新请求。页面可选择并确认这九个目标，各自映射统计推断、身体活动或抗阻训练主题；未确认仍按原问题查询。

缺项也分开报告：指定位置没有当前可用正文为`missing_source_content`；有正文但问题目标未识别为`unresolved_question_target`；有材料但尚无完整已审回答关系为`missing_answer_relation`；分区未选择、适用条件缺失和人群不匹配另列。其他来源候选未匹配指定来源，不再被当作所问正文不存在的证据。多个表格按各自定位汇总材料覆盖，缺其中一张时保留部分可用状态；错误来源或分区的旧理论也不能把正确缺项覆盖成“缺上下文”。

`source-resolution-failing-before.xml`、`missing-reason-failing-before.xml`和语言失败工件保留真实反例。`source-resolution-verification.xml`记录227项定点通过；新增九项实际UI选择/确认链路与其余回归计入最终整仓结果。`semantic-integration-verification.xml`保留更新状态名称前的一次中间结果（281通过、1个旧UI状态断言失败）；该断言迁移后单项通过，不改写中间失败记录。最终知识整合检查为287项通过，见`semantic-final-integration.xml`；来源边界回归10项通过和语言新表达165项通过均是重叠的定点检查，不相加。语言识别边界见`language-semantic-roles-freeze.json`与后续`language-dev146-freeze.json`，不能将这些开发检查称为新的独立语义通过率。

九合同的实施者来源复核全部核对到原文、活动版本与发布成员。另有先冻结预期再取输出的6题实施者开发检查：初始3通过、2部分、1失败；17个引用均可定位，六题所需材料均存在。这证明引用可定位仍不能替代回答正确性。具体缺口为等效逻辑误命中宽泛任务、成人年龄问题未识别、相对增量与影响因素复合问题只答后半，见`source-topics-development-results-1.4.6.json`。修复通用语言识别后，同六题逐题开发回放为6通过、18次引用可定位且当前可用，没有数值行动，见`source-topics-development-replay-1.4.6.json`。预期、初始输出及评价保持不变，后续修复不回填成独立通过率。

## 21规则的补齐与剩余缺口

逐项机器审计见`core_coverage_audit_21.json`，来源—规则—功能映射见`source_rule_feature_matrix.csv`。

| 类别 | 已完成合同 | 仍需区分的证据边界 |
| --- | --- | --- |
| 4个候选 | 双进阶、次数试验、负荷/次数试验、策略复盘 | 用户计划和器械提供数字；不宣称个人成功/最优或因果验证 |
| 10个解释/讨论 | 原8项加实用等效一般方法解释及HHS健康目标边界 | EFFORT仍缺S3/S4原始RIR误差验证；STATE缺特定睡眠/HRV机制；OPPORTUNITY不能估计潜在能力；HYPOTHESES不构成个体生理因果解释；M2不能提供个人阈值或时序校准 |
| 5个记录合同 | 可比记录分组、计划核对、执行反馈、描述趋势、周月报告 | 可比记录键由数据合同定义；关节动作/具体生物力学仍需NSCA/Neumann合法章节，不能由名称相似推出 |
| 4个个人方法主题 | 保留条件性软件计算与明确缺项，未激活个人知识推断权限 | 重测误差需M1正文与同任务误差数据；M2已补齐一般方法解释，个人实用等效仍需有依据界值和适配模型；重复查看需权利与适用性已核对的N2及预设协议；平台期还组合上述条件。S1/HHS或一本教材都不能替代真实任务校准 |

因此先前17项草稿并非都因付费教材受阻：13项已通过现有合法正文或明确记录合同补齐有限能力。
具体教材章节、中文重用许可和方法/校准缺口分别记账，不笼统列为一个“缺教材”。
本轮来源审核仍为真实AI辅助，无新增真人/专家审核或个人校准。
N1、M2正文已取得且完成上述方法范围阅读，不能再列为正文缺失；它们未填补M1、N2可用证据及个人任务校准缺口。
上一发布的独立源包冻结在`.local/v14-knowledge-independent-round2/source_packet.json`，含当时17主张、23实际引用片段、2来源族；SHA256为
`f5f8fc6395ab5e73c2a9dfba081d0eb95d604e74e9d09a21eb1b2d87029b3fd8`。包不含旧题或检索实现，也不公开原文。

## 已复现并修复的缺陷

| 缺陷 | 基线实际结果 | v1.4 实际结果 |
| --- | --- | --- |
| F10 展示 k 隐藏反证 | k=1/6 可将相同目标的真实冲突误标为支持；k=2/7 才发现冲突 | 在全部合格目标/范围候选上先检查冲突，再裁剪展示；四种 k 均保留冲突 |
| F11 嵌套版权内容混入父段落 | 受限 figure 文本进入开放父段落，父 span 仍可检索 | 文本、表格结构与 raw XML 统一使用本组件独占子树；子组件单独按自己的许可决定 |
| F12 相同更正通知重复失效 | 完全相同元数据重取令 epoch 1→2，已有精确版本清除与审核再次失效 | 按规范身份、状态和更正关系/原因去重；同通知 epoch 保持 1，真实变化仍使旧清除失效 |

证据分别见 `baseline.json`、`fixed_findings.json` 与 `knowledge-tests.xml`。
16 个既有 JATS 解析实际重跑为 `jats-owned-text-1.4.1`；保留原始 bytes 和旧版本，并在
`parse_supersession` 显式阻止旧解析继续索引。自动重新解析不等于重新审核旧理论。
新解析共 919 个合格 span（旧解析集合 1007 个）；这是片段数，不是论文数或科学质量分。

授权 PDF 章节导入记录精确版次、章节、文件页索引、可选纸面页标签、预期/已取页面与脚注缺口。
缺页章节仍可保留独立正文；未经表头、单位、脚注完整核对的表格不得作为数值参数依据。
表格重叠的普通文本行同样受门禁，不能通过换成 paragraph 引用绕开。

## 问答与评测

自由问句先解析为 subject/outcome/requested_relation 组合任务，再匹配已核对且绑定精确原文的回答要点。
任务解析采用有限、公开的概念词表，不按完整问题白名单写答案；未知表达仍可能无法理解。
关键词命中只识别任务，不判定证据支持。问句完整性与 supports/refutes/qualifies 分离：有原文支持的范围限制可以完整回答问题。
仅有相关材料继续为 `related_material_only`；新增可读状态区分完整/部分支持、缺上下文和缺来源内容。

旧独立评审 NEW-02/05/06 已重跑，3 个软件回归均给出具体回答：未测量寿命不能证明个人寿命增长、未测量明日个人体温不能确定其绝对值、明确允许增加次数应为 supports。
前两个依赖新增明确范围主张，第三个依赖真实的内容重新核对；软件不会从关键词自动修复错误的证据关系。
`old_three_failures_replay.json` 保留旧失败理由和原包/标注哈希。旧的独立 AI 7/10 不改写为本轮通过率；新回放为实施者自检，不算新独立验收。

固定可见 30 题和留出 8 题原文件未改，SHA256 分别为
`94d0d1233659501a92c4130d7289767aebef3b62ce6337fe21c44449b0abe9d8`、
`62b2e34ece6a655341aad0b6751b3d577f10955a85c9333f208615a2ef97ca62`。
留出题没有用于调整词表或规则。实际在仅核心、核心+研究两模式执行，结果相同：

| 集合 | schema | 输出引用 | 目标来源组旧诊断数 | 路由命中 | 独立人工语义分母 |
| --- | --- | --- | --- | --- | --- |
| 可见 30 | 30/30 | 3（3/3 可定位） | 1/67；其中当前来源可用 4/67 | 23/30 | 0 |
| 固定留出 8 | 8/8 | 0 | 0/8 | 3/8 | 0 |

这里的旧候选来源组统计只作为历史诊断，不是新的充分证据路径指标；未经核对的 gold 不进入 QAL-01 分母。
两模式相同反映当前研究卡未激活，不能推断补充文献没有价值。固定题执行使用显式合成指标夹具；来源证据来自实际本地文献，没有私有健康记录。

新独立题由未参与知识实现的 science 子代理阅读实际来源包后先冻结，再生成输出和逐引用独立 AI 标签。
最终绑定、计数及逐题失败见 `independent_results.json`；完整公开输出见 `independent_frozen_public.json`。
独立 AI 与独立人工分母严格分列，不将保守拒答直接视为通过，不改冻结问题或预期来适配输出。

本轮 18 个新表达原始结果为 **3 通过、15 失败**。11 个充分题的证据召回均命中，但 10 个没有作答、1 个答错目标；9 个原文引用都能定位，却只有 3 个适用于原目标。
这里证明了召回/定位与回答正确性不是同一指标。该小型定向题集也不是总体准确率估计。
原始题目、输出和独立标签均保持冻结，见 `independent_new_*` 工件及 SHA。

冻结评测暴露两类错误支持标签后，另作通用软件修复：时间修饰不再自动成为频次目标，多目标未消歧不择一宣称全答；
指定来源/版次/章节必须与证据匹配；复合问题与个人精确负荷请求只能标部分支持。
UI 提供可选的“明确问题目标”，用户确认后只查询所选目标，仍保留人群与来源约束。
这使有限范围的已核对主张有明确可用入口；自然语言的剩余覆盖不足仍公开保留。
`independent_task_guard_replay.json` 记录同 18 题的增量软件回放：仅原错目标的 2 项由 supported 降为 related，**没有新的独立语义通过率**，也未回填原标签。

原校验器错误要求证据束内每条 span 都与总体关系相同，因而拒绝了一个合法的“直接 supports + 范围/局限 qualifies”标注。
`claim-evidence-bundle-1.4.1` 允许这类组合，但必须有直接同向证据，且无相反关系或范围错误；仅 qualifies 不能伪装直接支持。
旧 `independent_new_binding_report.json` 的 17 accepted/1 rejected 保留；新校验结果为 18 accepted/0 rejected，语义判断仍是 3/18。

实际检索、当前精确来源版本、逐引用独立标签、应用覆盖和回退日志进入同一个 QAL-01–12 执行器。
未标注的支持/适用范围保留未知并给出上下界；不把缺乏标签当作安全零错误。
没有独立数字参考或访问审计轨迹时 QAL-10/11 的相关分母为空，不生成通过结论。

本轮进一步修复请求角色：第一人称不跨句扩散到通用证据精度问题；“再也举不起来才算有效”不当作第二次计算请求；实际个人数字/完整计划请求仍保留缺项。已登记来源名称接受合理词间空格，名称本身不再注入力量/增肌目标；版次与章节分开解析，HHS确切章名绑定到已读取章节。指定附录或表格必须在定位元数据中真实存在，主文仅提到附件不能代替附件内容；逐项研究数据与营养参数请求显示具体未回答项。公共健康频次及其能否推出增肌最优的边界分别回答，不把健康最低建议升级为个人最优处方。

`request-boundaries-failing-before.xml`保留9项真实失败与2项原本通过的对照；`request-boundaries-verification.xml`记录141项定点回归。`language-development-*`另保存中英词形、频次分配与关系识别的开发失败/修复记录。它们均为开发验证，不改写两批独立评价的原始分数。

## 验收对应与边界

| 验收 | 对应实现/证据 |
| --- | --- |
| KB-01/02/04 | 核心书目种子、manifestation 身份、S1 别名复用；`test_core_seed_books_aliases_partitions_and_unread_rules_do_not_activate` |
| KB-03 | `import_chapter` 与 PDF 表格重叠行数值门禁；`test_authorized_partial_chapter_keeps_prose_but_blocks_table_parameters` |
| KB-05/06 | 组合任务、相关材料/已支持分离；新表达测试、旧三失败回放和新独立题 |
| KB-07/08/09/10/11 | 真实 reviewer 策略、输入条件、限定动作；核心规则单测与 `test_review_candidate_flow.py`/推荐 UI 集成验收 |
| KB-12/16 | 科学服务负荷方向、RIR 语义及候选限制；`docs/v14_science.md` |
| KB-13 | 不可变 release、规则替换、claim 撤回当前失效；核心生命周期单测；旧建议快照由建议服务验收 |
| KB-14 | 同目标/范围冲突检查；范围不同不平均参数；F10 与 scope 测试 |
| KB-15 | 固定 30/8 两分区实际输出与统一 QAL |
| KB-17/18/20 | 统一 advice context/截止可见性/执行反馈与因果边界；推荐和科学集成验收 |
| KB-19 | core/research 白名单；catalog/interface 不能授权科学 claim 的单测，目录/媒体另有来源记录 |

上述映射区分知识子系统证据与跨模块集成证据；整体验收状态以主代理最终矩阵和全套测试为准。
主代理还实际执行了“复制生产核心库→合成训练→页面全部声明与候选控件→结束后反馈→复制库中撤回 S1”的完整路径，见
`artifacts/v14/advice/real-core-ui.json` 与 `tools/v14_advice_evidence.py`；缺少 profile 的负例同样执行。
这为 KB-09/18/20 提供真实生产规则接入 UI 的软件证据，仍不是真人训练因果验证。
知识/质量合同阶段验证为128项通过；组合目标与范围守卫另有75项通过工件 `composed-answer-verification.xml`。两组有重叠，不相加计数；最终整仓唯一用例数见 `final-manifest.json`。逐指标机器追踪见 `metric_audit_12.json`。
当前剩余缺口是具体付费教材章节、中文材料重用范围、4项方法/校准及活动解释的明确子主题缺口、自然语言泛化覆盖，以及独立人工/专家复核。
这些缺口不影响已满足条件的4项可选择任务和已核对的记录/解释合同，也不能被软件测试通过掩盖。

## 第二批独立语义评价与后续软件回放

另一名未读实现、测试或旧题的独立AI先读冻结来源包，再冻结20个新问题、答案要点和充分证据路径；取得生产输出后逐题、逐引用判读。原结果为 **4通过、5部分、11失败**。14道正文足够题只有2道完整通过、1道部分、11道完全未答。详见 `independent_round2_results.json` 与 `independent_round2_report.md`；原18题3/18与这批4/20分别保留，不合并为一个准确率，也不是人工专家验收。

独立结果还指出三项不合理的完整支持标签。后续通用修复保留并列力量/增肌目标，把“between sets”识别为休息条件，识别个人具体参数请求和跨来源/版本比较。`independent_round2_guard_replay.json` 使用原20题作开发回放：R2-03纳入两种目标的休息依据，R2-16/R2-18保留明确缺项并改为部分回答。原问题、输出、标签及其哈希未更改；这份回放没有新独立通过率。自然语言泛化与具体缺项解释仍不足，不能据当前来源数或测试数量称自由问答已完成验收。

## 第三批独立语义评价

新评审未读取实现、测试或旧评测，只先阅读19主张、32段真实正文、3个来源族的冻结包，再冻结20个新问题与预期，随后取得生产输出并逐题/逐引用评审。20题原件保留，其中1题的M2许可预期错误（CC-BY-4.0并不禁止再分发）明确列为`invalid_rubric`、整题排除评分，没有事后缩窄预期制造通过。其余19题为**3通过、3部分、13失败**；14道正文充分题只有1道正确、1道部分，另12道未答或答非所问。存在4个错误完整支持标签、3题的5个引用块不适用于所问目标。来源、问题、原始输出及实现身份均先冻结，见`independent_round3_results.json`和`independent_round3_report.md`。这仍是AI语义评审，不是人工专家验证，三批结果不合并为总体准确率。

后续开发修复显式保留未消歧的机构约束：仅有HHS/ACSM等机构名称不能自动选择文件，也不能借用另一机构的材料回答。复合请求中的个人未来数量预测单列未回答部分，不能被一般组量或因果边界说明覆盖。阶段组织的背景变量与真正所问的必要性、比较优势分别核对；没有已审比较关系时保留缺项。相应开发测试与原批次分数分开保存，不将回放结果写回原独立评价。`request-final-verification.xml`为167项知识/语言定点软件回归；`independent_round3_development_replay.json`只回放4个原错误：两项未消歧机构问题和个人增长量请求降为未完整回答，阶段组织问题现在包含已审周期组织内容。后一项仍标完整，该回放仅验证路由变化，没有新的独立语义判定或通过率。

## 重现

```bash
PYTHONPATH=src .venv/bin/python tools/v14_build_core_knowledge.py
PYTHONPATH=src .venv/bin/python tools/v14_build_core_knowledge.py --fetch
PYTHONPATH=src .venv/bin/python tools/v14_evaluate_knowledge.py
PYTHONPATH=src .venv/bin/python tools/v14_build_quality_audit.py
PYTHONPATH=src .venv/bin/python tools/v14_import_equivalence_source.py
PYTHONPATH=src .venv/bin/python tools/v14_import_equivalence_source.py --activate-explanation
PYTHONPATH=src .venv/bin/python tools/v14_review_hhs_scope.py --activate-explanation
PYTHONPATH=src .venv/bin/python tools/v14_expand_source_explanations.py --activate-explanations
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_v14_knowledge.py tests/unit/test_knowledge.py tests/unit/test_review_knowledge.py tests/science/test_quality_acceptance.py
PYTHONPATH=src .venv/bin/python -m healthzip.knowledge --root .local/knowledge import-chapter authorized-chapter.json
```

默认构建复用本地合法缓存；`--fetch` 仅重试官方公开来源，不绕过访问限制。
M2工具默认仅核验本地原始收据和SHA后入库；`--activate-explanation`另建不可变1.4.4解释合同，重复执行幂等，不覆盖旧发布或重跑独立评测。
HHS与九主题工具分别核验既有原件/定位和权利范围后建立1.4.5、1.4.6不可变发布；重复运行核对旧成员、旧发布和独立评测文件未改，不重评旧题。
章节声明需提供 source_id/path/edition_id/chapter_id/page_indices/expected_page_indices/license_id/rights_evidence_url/authorized_by/identity_review。
导入成功只建立可审核材料，不自动审核主张/规则。公开前使用 `v14_evaluate_knowledge.py` 的投影保留原始与公开输出哈希，移除原文、结构化表格、版权长文和私有路径。
