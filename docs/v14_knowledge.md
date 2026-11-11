# v1.4 知识、应用规则与问答验收

首次修复以 `912aefc93b9bd9c1cebf297a10728c69c827e266` 为基线；`dd8e2e1` 后继续逐项补齐可完成的来源与规则合同。公开工件位于
`artifacts/v14/knowledge/`。真实正文、版权证明缓存、未投影检索输出和独立评审阅读包均留在 `.local/`。

## 真实完成范围

已登记 8 个核心来源、21 个规则主题；当前实际核对 **17 个 SourceClaim，发布17个有明确能力范围的 ApplicationRule**。
当前发布 ID 为 `core-personal-trial-1.4.3`。其中4项候选仍是双进阶、同负荷增加次数试验、较重负荷/较少次数试验、策略复盘中的试验选择；另有8项来源解释/讨论和5项记录描述/执行反馈/报告合同。
剩余4项统计推断规则仍缺原始方法材料及相应任务校准。活动规则保留具体剩余科学子主题缺口，不把17项活动合同等同21主题全部科学完备。
首次6主张/4规则的`1.4.1`发布和中间`1.4.2`发布均保留；目标范围改进通过新的不可变版本完成。
`source_rule_feature_matrix.csv` 逐项区分相关解释主张、尚缺的主题和应用核对。

旧版 11 张 TheoryCard 继续为 `needs_review`；没有改写其历史审核、冒充专家，或把旧解释权限提升成候选权限。
新增 SourceClaim 只授权相应解释；产品如何把一般原则变成一次可选择任务，另由 ApplicationRule 保存版本、来源、数值来源、退出条件与后续观察。
规则审阅者真实记录为 `ai_assisted`，独立人工/专家审定数量为 0。软件通过不证明个人效果。

| 核心来源 | 本轮真实材料与状态 |
| --- | --- |
| ACSM 2026 抗阻训练立场，S1 | 复用既有规范身份与原始全文；实际进一步精读段11、24–26、59–76，覆盖初始获益/持续进展、特异性、负荷次数、不同目标、努力及证据局限。当前14个主张引用S1，其中1个同时引用HHS；CC-BY-NC-ND仅按已声明本地非商业用途使用。|
| HHS《Physical Activity Guidelines for Americans》第 2 版 | 官方完整 PDF 118 页已取得；解析第4、7章共18页，实际读取正文页56–63、88–93。只使用联邦正文，排除照片/图示；当前4个主张引用HHS，其中1个跨来源。公共频次明确绑定第4章18–64岁成人范围。|
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
QAL-09因此分别报告12/16个有活动的有限来源合同与5/5个记录合同，不能将后者计成科学证据覆盖。

SourceClaim、已审规则和发布清单不可原地改正文；替换需新版本。
撤回、待复核或来源更正会阻断当前使用，包括指定旧 release 时的重新查询。旧发布内容及旧建议快照保持原样。
这同时保留“当时用了什么”与“现在还能否使用”的区别。

新增和升级的来源范围：力量休息声明`CORE-CLAIM-REST:1.4.3`明确`goal=strength`，肌肥大休息另有`CORE-CLAIM-REST-HYPERTROPHY:1.4.2`说明证据不足；
`CORE-CLAIM-FREQUENCY-VOLUME:1.4.3`明确`applicable_goals=[strength,hypertrophy]`，与HHS公共健康频次不互相替代。
旧6个通用范围声明及中间频次声明留存原文与审核，当前置`needs_review`，新版本接替；候选4规则新版仍只获原来的三种动作权限。
核心书目已登记带版次的完整`query_names`；裸ACSM/NSCA不暗定某本书或版次。

## 21规则的补齐与剩余缺口

逐项机器审计见`core_coverage_audit_21.json`，来源—规则—功能映射见`source_rule_feature_matrix.csv`。

| 类别 | 已完成合同 | 仍需区分的证据边界 |
| --- | --- | --- |
| 4个候选 | 双进阶、次数试验、负荷/次数试验、策略复盘 | 用户计划和器械提供数字；不宣称个人成功/最优或因果验证 |
| 8个解释/讨论 | 目标范围、努力、组量、休息、频次、状态背景、观察机会、解释假设 | EFFORT仍缺S3/S4原始RIR误差验证；STATE缺特定睡眠/HRV机制；OPPORTUNITY不能估计潜在能力；HYPOTHESES不构成个体生理因果解释 |
| 5个记录合同 | 可比记录分组、计划核对、执行反馈、描述趋势、周月报告 | 可比记录键由数据合同定义；关节动作/具体生物力学仍需NSCA/Neumann合法章节，不能由名称相似推出 |
| 4个方法主题 | 保留条件性软件计算与明确缺项，未激活知识推断权限 | 重测误差需M1正文与同任务误差数据；实用等效需M2与有依据界值；重复查看需N2与预设协议；平台期还组合上述条件。S1/HHS或一本教材都不能替代真实任务校准 |

因此先前17项草稿并非都因付费教材受阻：13项已通过现有合法正文或明确记录合同补齐有限能力。
具体教材章节、中文重用许可和方法/校准缺口分别记账，不笼统列为一个“缺教材”。
本轮来源审核仍为真实AI辅助，无新增真人/专家审核或个人校准。
N1正文已取得且完成上述方法范围阅读，不能再把N1列为正文缺失；其入库并未填补M1/M2/N2及任务校准缺口。
源包冻结在`.local/v14-knowledge-independent-round2/source_packet.json`，含17当前主张、23实际引用片段、2来源族；SHA256为
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

## 重现

```bash
PYTHONPATH=src .venv/bin/python tools/v14_build_core_knowledge.py
PYTHONPATH=src .venv/bin/python tools/v14_build_core_knowledge.py --fetch
PYTHONPATH=src .venv/bin/python tools/v14_evaluate_knowledge.py
PYTHONPATH=src .venv/bin/python tools/v14_build_quality_audit.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_v14_knowledge.py tests/unit/test_knowledge.py tests/unit/test_review_knowledge.py tests/science/test_quality_acceptance.py
PYTHONPATH=src .venv/bin/python -m healthzip.knowledge --root .local/knowledge import-chapter authorized-chapter.json
```

默认构建复用本地合法缓存；`--fetch` 仅重试官方公开来源，不绕过访问限制。
章节声明需提供 source_id/path/edition_id/chapter_id/page_indices/expected_page_indices/license_id/rights_evidence_url/authorized_by/identity_review。
导入成功只建立可审核材料，不自动审核主张/规则。公开前使用 `v14_evaluate_knowledge.py` 的投影保留原始与公开输出哈希，移除原文、结构化表格、版权长文和私有路径。
