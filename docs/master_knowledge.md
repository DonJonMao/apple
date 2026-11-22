# 2026-11-22 本轮知识与 RAG 实施证据

本文件对应附件第10–11、14.3节及附录B/C。它记录软件、取得原文、阅读、主张审核、实际检索与页面使用的不同状态，**不表示知识六问已全量完成，也不表示独立科学专家审核通过**。

本次复用了 SourceLibrary/TheoryLibrary、现有来源身份、逐主张审核、用途边、权限过滤及冻结发布。K0–K7是原库上的问题目录，不是八套数据库。57个身体字段和W1–W8/E共66个公开问题已逐一调用真实本地库；其中66题返回已审核一般说明，56题有版本固定的Apple字段原文链接。官方定义链接仅说明字段身份；通用比较主张不等于特定仪器的测量验证。

实际执行器是 `tools/master_source_inventory.py`、`master_official_fields.py`、`master_apply_source_reviews.py`、`master_finalize_source_inventory.py`、`master_rag_coverage.py`。可复核资料分别在 [来源最终审计](../artifacts/master_redesign/knowledge/source-final-audit.json)、[逐条审阅和用途回执](../artifacts/master_redesign/knowledge/reviewed-uses.json)、[66题检索及六问明细](../artifacts/master_redesign/knowledge/topic-coverage-final.json)。本地原始字节保存在 `.local/master-knowledge/fetched` 及 `.local/knowledge/blobs`，不进入公开交付；公开回执仅含来源元数据、hash、定位与合成评测结果。

## 本轮新增的受限用途

`tools/master_source_reviews.json` 保存每一段原文字节SHA、XPath、段落SHA、来源版本、许可、研究范围、禁止推断和目标用途。应用时重新比对原文，不只按标题登记。AI辅助审阅的 `independent_expert_validation` 明确为 false。没有新增个人医学阈值、训练数字规则或模型候选权限。

| 主张 | 原文与读过的位置 | 允许说明 | 保留边界 |
|---|---|---|---|
| MASTER-DE-VET | de Vet2006，Interpretation/applicability | 可检测变化与有意义变化需要不同依据 | 原文主要是健康问卷，不移植误差数字到Watch/力量/体重 |
| MASTER-HRV-IDENTITY | Quigley2024 PMC作者接受稿，§5.2.3/§5.3.1 | SDNN/RMSSD定义、记录长度 | ECG方法学不能冒充手表准确度，不把SDNN当纯迷走活动 |
| MASTER-HR-CONTEXT | 同上，§8.2/8.2.1 | 先按活动/姿势分层，再关联实际记录；补记情境 | 不猜压力、疲劳、病因，不提供HRR阈值或恢复协议 |
| MASTER-OXYGEN / FOLLOWUP | FDA Pulse Oximeter Basics，准确度、产品类别、家庭复核 | 读数、症状和设备用途；必要时联系医疗人员 | 指夹条件不直接移用腕部，稀疏点不代表整夜 |
| MASTER-NOISE / FOLLOWUP | NIOSH Understand Noise Exposure，测量与环境改变 | 声级、时长、剂量不同；减少来源暴露后复查 | 职业限值不是人人通用报警线，未借此建立声能公式权限 |
| MASTER-BIA-CONDITIONS | Campa2021，Introduction/§5 | BIA同设备、姿势、运动和饮食条件复测 | 运动员叙述综述，不提供当前秤具的MDC或误差 |
| MASTER-FFM-NOT-MUSCLE | 同上，Introduction/§6 | 去脂体重包含体水分/骨矿物等；依赖水合假设 | 不计算肌肉增长或水分变化量 |
| MASTER-CYCLE-PERFORMANCE | McNulty2020，纳入条件/讨论 | 异质性、个体反复观察，不按统一阶段配训练 | 规律月经、未用激素避孕成年女性研究，不推断日历相位 |
| MASTER-ACTIVITY-OPPORTUNITY | 既有WHO2020术语表完整定位 | 活动机会与体适能不同 | 不是步态设备验证或个人功能诊断 |
| MASTER-SLEEP-ORDER | 既有R4急性睡眠损失综述，分层结果/讨论 | 训练前睡眠与训练后睡眠分开核对 | 实验均值不用于算个人减量比例 |

本轮累计21条受限主张（14个新原件片段包、7个既有span的新用途）；随后追加了FDA设备情境/事件回应、NIH睡眠日志、ACSM目标进阶、HHS逐步活动，以及FDA排卵试剂、HHS黏液/疼痛和NIOSH声能方法。原文、具体限制与用途逐条保存在同一审阅包。新取得H1和Campa相关段落核对了原文CC BY 4.0许可；第三方图表不在本次授权段落内。FDA/CDC仅引用机构正文。核读Apple网站条款后，其个人非商业使用还含“不复制到联网计算机/不修改”等限制，不能直接当作云端RAG许可；Apple定义、白皮书及其余权利未核清原件保留为参考，不因下载成功获得索引或科学主张权限。Bellenger机构原稿确为作者接受稿，保留非商业私人研究条款，不能称已取得正式出版版。

## 检索与生成验收

公开问题通过 `knowledge/topics.py` 调用原 `_retrieve_for_metric` 的 `reviewed_metric` 范围，沿用领域、用途、条件、完整证据组、撤销与冲突检查；预算仍为6段。不足部分继续显示可用主张和字段入口。曾测试按用途标签数量优先的分配方案，但实测挤掉W3的VO₂特定来源，因此已撤回该方案，保留原有排名；没有更换模型或无限扩大top-k。排卵试剂/黏液/疼痛消费者信息也修订为仅绑定各自字段，不挤占W8训练表现证据，修订历史见use-scope-corrections.json。页面按需点击“依据与原文→查阅本题依据”；进入页面不会在线查文献或重建全库。字段引用必须匹配原版本/hash且未被替代；冻结查询不偷加当前实时链接。

| 验收维度 | 本轮证据 | 实际结论 |
|---|---|---|
| 已知来源召回 | topic-coverage-final.json | 固定10题/6段，最终9命中；环境声未返回旧目标MASTER-NOISE，返回更具体的NIOSH声能方法及复评来源。保留这个未命中，不改预期凑10/10；非专家独立gold |
| 真实公开模型 | public-model-before-index.json / incremental-index.json / public-model.json | 首次RHR向量缺3/8；定向补25段并复用35后，词法/向量/融合/精排均8候选，无降级；DeepSeek精排实测9.744秒 |
| 新增公开段落 | incremental-index-final.json | 第一轮补12段成功；随后所有21条受限主张按需要增量补向量，最终公开问题实跑见public-method-model-final.json；未发送私人数据 |
| 独立日期/数值 | independent-rag-final.json | 9月合成数据产生61.5 bpm等真实计算；6项统计核对0错误，6种事实篡改全部拒绝，5项有用性检查通过 |
| 来源与下一步 | 同上及 tests/knowledge/test_health_fact_bindings.py | 真实Quer原文进入测量说明；输出具体观察、核对项及原文；年龄未知不默认成人 |
| 部分/缺项/撤销/失败 | final-fact-question-tests.xml；knowledge-tests-final.xml | 公开问题、事实绑定、撤销、未授权、未配置、超时与校验失败受测试；合成fixture验证软件边界，不充当真实文献效果评测 |
| 浏览器 | [browser-final](../artifacts/master_redesign/knowledge/browser-final/browser.json)、1440/390截图 | 实际页面点击后显示NIOSH声能/复评说明和Apple原文字段入口；1440/390已目视核对。未对66题逐题做截图或人工质量评审 |
| 私人回答模型 | public-model.json | `answer_model_configured=false`、`private_explanation_consent=false`；生成采用本地fallback，远程私人答案质量未验证 |

独立RHR本地路径另测30次热调用：冷1.221秒、热P50 0.01944秒/P95 0.01978秒，包含公共检索与确定性解释，不包含页面、完整周期报告或远程模型。完整报告性能必须引用总交付的对应规模报告，不能用此数字代替。

## 逐来源核对与尚缺资料

下表的“审核/命中”来自当前库实际关系和检索，不是下载数量。首次获取、合法替代路径和后续重试均在 `source-final-audit.json` 保留。表中“阅读”只指列出的相关段落，不表示整本/整篇每项主张已审核。M5获取深度更正及读过段落的锚点/文本hash见[fpp3-reading-correction.json](../artifacts/master_redesign/knowledge/fpp3-reading-correction.json)。

| ID | 当前原件登记 | 已审核主张ID/实际命中题数 | 相关阅读与缺口 |
|---|---|---|---|
| M1 | reference_page, toc | 0 / 0 | 出版社/目录；第5/7/8章正文未取得，不能称已阅读目标章节。 |
| M2 | fulltext | 0 / 0 | 作者PDF已取得；核读个体内/间方差、观察者差异；未审核仪器特异应用/索引许可。 |
| M3 | fulltext | 1 / 31 | 出版社全文替代PMC失败路由；相关解释段落已审阅并绑定。 |
| M4 | fulltext | 0 / 0 | 第4/5章HTML已取得；核读缺失假设不可由数据验证、理由记录与敏感性；尚未逐主张绑定。 |
| M5 | chapter_entry（历史）, fulltext | 0 / 0 | 当前OTexts Quarto的第2/7/10/13章HTML包含整章正文；核读时序图/ACF、趋势导致缓慢衰减相关、残差ACF、滞后预测量、短序列、缺失/离群段落。短序列没有通用30点门槛，应考虑噪声和参数量；不能移作个人推断充分性验证。正文许可未核清，版权页404，GitHub是配套数据包。追加fulltext解析版本并保留旧chapter_entry，不开放索引。 |
| M6 | preview | 0 / 0 | 出版社预览已取得；第4/5章目标正文未取得。 |
| J1 | reference_page | 0 / 0 | 作者入口已取得；指定2026-08-19 PDF重定向TLS失败，替代入口亦失败，本轮没有核读该版目标章节。 |
| J2 | fulltext | 0 / 0 | 作者PDF已取得；核读个人内与群体间效应区分；未核清复用许可/逐主张应用。 |
| J3 | fulltext | 0 / 0 | AHRQ原报告镜像已取得；核读携带效应/washout及使用条款；第4章完整应用审核仍待补。 |
| H1 | fulltext | 2 / 6 | PMC作者接受稿全文，CC BY4.0；§5.2.3/5.3.1/8.2/8.2.1已审核绑定；不冒称正式出版字节。 |
| H2 | fulltext, metadata | 1 / 1 | 复用既有Carter全文与窄范围HRV用途，CV不作个人通用界线。 |
| H3 | 无原件版本 | 0 / 0 | 官方节选403；目标第3/4/7章及附录A未取得。 |
| H4 | 无原件版本 | 0 / 0 | DOI403；合法开放位置未找到，不能采用附件方案自述的“已读副本”作为本轮证据。 |
| H5 | fulltext | 0 / 0 | 复用Apple2024 PDF；字段参照保留，仍无本轮已审核科学主张。 |
| H6 | fulltext | 2 / 1 | FDA正文及权利页；准确度、类别、症状和后续核对已审核。 |
| S1 | fulltext | 0 / 0 | AHA2025 PMC正文已取得并解析；有明确限制再分发条款，未扩大索引/科学用途。 |
| S2 | fulltext | 0 / 0 | Fischer2021 PMC全文；核读Methods/whole-signal与每日值、全天状态要求和Fig7。OpenAlex标other-OA但无明确复用许可，继续保留参考；日志行动以NIH可用原文补足。 |
| S3 | fulltext | 0 / 0 | Carney2012 PMC全文，核读Core Diary九字段；公开位置未标许可，不能因开放阅读放宽。NIH日志原文已补可用行动，但不能冒称Carney逐主张入库。 |
| S4 | fulltext | 0 / 0 | AASM2018 PMC正文取得/解析；不能把临床编码记录时长转成消费设备门槛，逐主张审核待补。 |
| S5 | fulltext | 0 / 0 | Walsh2021合法PDF取得；未把全文自动升级为审核或个人减量规则。 |
| T1 | reference_page | 0 / 0 | NSCA5出版社/目录；第13/14/18/22/24章目标正文未取得。 |
| T2 | abstract, fulltext, metadata | 18 / 0 | 复用S1的现有版本与主张；不能仅凭现有主张数声称2026立场声明整篇审核完毕。 |
| T3 | fulltext | 0 / 0 | Bourdon2017原文PDF，明确©Human Kinetics2017；已核读外部负荷/内部反应定义，未发现可索引许可。训练目标/进阶与负荷比较用既有ACSM/S5已许可原文补用。 |
| T4 | abstract, fulltext, metadata | 2 / 0 | 复用S4；预印本和正式版保持独立，现有直接RIR有限用途不得扩为全部RPE记录。 |
| T5 | fulltext | 0 / 0 | Reynolds2006作者大学PDF取得；未把卧推/腿举RM公式扩到任意动作/非力竭组。 |
| B4-1 | fulltext | 1 / 18 | 复用WHO2020；核读术语表并追加活动机会vs能力用途。 |
| B4-2 | fulltext | 1 / 1 | McNulty2020出版社全文，CC BY4.0；纳入人群、异质性及个体观察已审核。 |
| U1 | fulltext | 0 / 0 | ATS原文PDF19页，明确©ERS2014；核读pp1428–1429学习效应、鼓励/供氧/路线/助行器一致性和人群。未发现可索引许可，临床30m不移用于Watch。 |
| U2 | fulltext | 0 / 0 | Apple2021 PDF，核读pp.3–5/8–9；4周支持/通常周更/500m上限仅适用该算法版本，不建立MDC。 |
| U3 | fulltext | 0 / 0 | AppleiPhone步态2022 PDF；核读携带位置、实验任务与队列，未把iPhone测量当手表测量。 |
| C1-1 | abstract, fulltext, metadata | 1 / 1 | 复用Quer2020完整JATS及个人参考用途。 |
| C1-2 | abstract, fulltext, metadata | 4 / 6 | 复用Apple准确性综述及设备误差范围限制。 |
| C1-3 | abstract, fulltext, metadata | 4 / 2 | 复用HRV训练综述；不自动移用到Apple短时SDNN。 |
| C1-4 | abstract, fulltext, metadata | 1 / 1 | 复用睡眠损失综述；追加训练前后实际顺序用途。 |
| C1-5 | abstract, metadata, reference_page | 0 / 0 | Plews2014仍摘要级；未找到合法开放全文，不以摘要设个体采样阈值。 |
| C1-6 | abstract, fulltext, metadata, reference_page | 0 / 0 | 新取得机构作者接受稿26页；核读摘要/人群及许可：15名男性跑者/铁三、RMSSD；未赋予SDNN或个人诊断权限。 |
| C1-7 | fulltext, metadata | 1 / 0 | 复用Davis-Wilson2025全文和既有缺失用途。 |
| C1-8 | fulltext, metadata | 0 / 0 | 复用成人睡眠共识全文；年龄未知不默认成年，无本轮新主张。 |
| C1-9 | fulltext | 0 / 0 | 青少年睡眠共识页面取得；不能把年龄分层数值用于未知年龄。 |
| C2-1 | official_definition, reference_page | 0 / 0 | 官方DocC类型目录以及逐字段JSON；接口定义不是设备验证。 |
| C2-2-1 | fulltext | 0 / 0 | 复用官方RHR字段原文，和普通HR分开。 |
| C2-2-2 | fulltext | 0 / 0 | 复用官方SDNN字段原文；RMSSD不是同义词。 |
| C2-3 | fulltext, reference_page | 0 / 0 | 官方1分钟HRR定义JSON；具体来源运动恢复协议尚需进一步核对。 |
| C2-4 | fulltext | 0 / 0 | Apple VO2max白皮书取得，相关科学说明复用既有已审核来源。 |
| C2-5 | fulltext | 0 / 0 | 复用Apple2025睡眠PDF；分期与真实PSG界限保留。 |
| C2-6 | 无原件版本 | 0 / 0 | Apple支持页429；合法取得腕温DocC字段定义，非核心体温。 |
| C2-7 | fulltext | 0 / 0 | Apple2024睡眠呼吸通知PDF，核读pp3–4每夜值/30天通知/非AHI。字段特异算法尚无科学主张，事件一般情境与回应已有FDA2023受限用途。 |
| C2-8 | fulltext, reference_page | 0 / 0 | 六分钟步行字段定义取得；与U2版本/支持窗口并列核对。 |
| C2-9 | fulltext | 0 / 0 | 与U3相同字节hash，复用原件，不重复授予用途。 |
| C2-10 | fulltext, reference_page | 0 / 0 | 官方呼吸率定义；稀疏点不能代表整夜。 |
| C2-11 | fulltext, reference_page | 0 / 0 | 官方环境声音等效连续A计权定义；不是普通算术dB平均。 |
| C2-12 | fulltext | 2 / 4 | CDC/NIOSH正文及许可；测量、暴露变化后复查已审核绑定。 |
| C3-BIA | reference_page | 0 / 0 | Kyle2004只取得期刊入口；未取得目标全文，补以Campa2021一般方法，不能替代具体秤具重复性。 |
| C3-DXA | reference_page | 0 / 0 | ISCD官方立场页取得；尚无当前设备重复性/最小变化验证或新用途。 |
| C3-ENERGY | abstract, fulltext, metadata | 1 / 0 | 复用E8设备能量误差证据，不估精确个人热量缺口。 |
| C3-DAYLIGHT | fulltext, reference_page | 0 / 0 | 官方日照DocC；记录时长不是眼部光剂量。 |
| C3-NOISE | reference_page | 0 / 0 | 首次NIOSH旧入口失败；后从CDC Stacks取得NIOSH98-126完整126页。相关数学关系与时长积分见补充来源，不用CFR定义冒充完整规范。 |
| C3-BIA-CAMPA | fulltext, reference_page | 2 / 3 | Campa2021完整HTML/JATS，CC BY4.0；正文条件与组成概念已审核，仪器纵向重复性仍缺。 |
| SUPP-MSTR-FDA-OVULATION | fulltext | 1 / 1 | FDA家用尿液排卵试剂正文；LH/E3G、定性身份、按试剂说明复测已审阅。仅字段用途，不把此证据替代W8训练关联。 |
| SUPP-MSTR-OWH-CYCLE | fulltext | 1 / 1 | HHS/OWH本人周期记录及黏液变化正文；定性观察/真实日期用途已审核，不能推断相位。 |
| SUPP-MSTR-OWH-PERIOD | fulltext | 1 / 2 | HHS/OWH月经疼痛正文；条件性症状日志与影响日常活动时求评估，腹部痉挛不自动当月经病因。 |
| SUPP-MSTR-NIOSH-NOISE-1998 | fulltext | 1 / 2 | 官方CDC存档126页原文；核读并视觉核对印刷p26、pp29–30，绑定声能/时长物理说明；排除ANSI/Ostergaard直接引文和职业风险阈值。 |
| SUPP-V15-FDA-DHT-2023 | fulltext | 3 / 7 | 复用既有已许可FDA2023数字健康原文，核读设备佩戴/维护/症状背景与异常回应完整条目；新增一般情境及事件回应用途，不验证某Watch算法。 |
| SUPP-V15-NIH-SLEEP-2011 | fulltext | 2 / 2 | 复用NIH公众睡眠指南已许可原文，核读睡眠日志及次日困倦对应；新增日志复评，未移用手册固定阈值。 |
| SUPP-CORE-US-HHS-PAG-2 | fulltext | 13 / 7 | 复用HHS2018原文第7章，核读跨年龄一般渐进原则；新增活动逐步调整用途，不给个体加量百分比。 |

## 57字段与W1–W8/E六问覆盖

已直接核对 `body_catalog.METRIC_CATALOG` 与公开问题目录：57字段集合相等，没有遗漏字段。下表“有”只代表六段真实检索中有该用途的受限主张；定义栏“入口”不代表已完成设备验证。“适用”指随主张展示限制，尚未独立评审完整性。尤其仅命中de Vet/WHO等通用方法时，不能宣称该具体设备或字段六问齐全。逐题确切claim/source/version/locator见[机器可读矩阵](../artifacts/master_redesign/knowledge/field-six-question-matrix.csv)与topic-coverage-final.json。

| 字段/工作流 | 是什么 | 怎样测 | 怎样比较 | 为何变化/例外 | 能做什么 | 适用范围 |
|---|---|---|---|---|---|---|
| 普通心率 · BODY-OBS-heart_rate_bpm | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 运动心率 · BODY-OBS-workout_heart_rate_bpm | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 日静息心率 · BODY-OBS-resting_heart_rate_bpm | 官方入口 | 缺 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 步行平均心率 · BODY-OBS-walking_heart_rate_bpm | 官方入口 | 缺 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 一分钟心率恢复 · BODY-OBS-heart_rate_recovery_1m | 官方入口 | 缺 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 心率变异性 SDNN · BODY-OBS-hrv_sdnn_ms | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 来源报告 VO₂max · BODY-OBS-vo2_max_ml_kg_min | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| 睡眠事件、时长与分期 · BODY-OBS-sleep_stage | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 睡眠腕温 · BODY-OBS-sleeping_wrist_temperature_c | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 呼吸率 · BODY-OBS-respiratory_rate_bpm | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 血氧饱和度 · BODY-OBS-oxygen_saturation_fraction | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| 睡眠呼吸紊乱 · BODY-OBS-sleep_breathing_disturbances | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 步数 · BODY-OBS-steps | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 步行和跑步距离 · BODY-OBS-distance_walking_running_m | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 骑行距离 · BODY-OBS-distance_cycling_m | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 运动分钟 · BODY-OBS-exercise_minutes | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 站立小时 · BODY-OBS-stand_hour | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 站立分钟 · BODY-OBS-stand_minutes | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 爬楼层数 · BODY-OBS-flights_climbed | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 活动强度 MET · BODY-OBS-physical_effort_met | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 六分钟步行距离 · BODY-OBS-six_minute_walk_m | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 步行速度 · BODY-OBS-walking_speed_m_s | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 步长 · BODY-OBS-walking_step_length_m | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 双支撑时间比例 · BODY-OBS-walking_double_support_fraction | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 步态不对称比例 · BODY-OBS-walking_asymmetry_fraction | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 步行稳定性 · BODY-OBS-walking_steadiness_fraction | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 上楼速度 · BODY-OBS-stair_ascent_m_s | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 下楼速度 · BODY-OBS-stair_descent_m_s | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 身高 · BODY-OBS-height_cm | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 体重 · BODY-OBS-body_mass_kg | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 体脂比例 · BODY-OBS-body_fat_fraction | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 瘦体重 · BODY-OBS-lean_body_mass_kg | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 活动能量 · BODY-OBS-active_energy_kcal | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| 静息能量 · BODY-OBS-basal_energy_kcal | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| 已记录饮食能量 · BODY-OBS-dietary_energy_kcal | 官方入口 | 缺 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| 已记录碳水化合物 · BODY-OBS-dietary_carbohydrates_g | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 已记录蛋白质 · BODY-OBS-dietary_protein_g | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 已记录脂肪 · BODY-OBS-dietary_fat_g | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 已记录饮水 · BODY-OBS-dietary_water_ml | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 已记录咖啡因 · BODY-OBS-dietary_caffeine_mg | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 日照时长 · BODY-OBS-daylight_minutes | 官方入口 | 缺 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| 环境声音暴露 · BODY-OBS-environmental_audio_dba | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 耳机声音暴露 · BODY-OBS-headphone_audio_dba | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 经期流量日志 · BODY-OBS-menstrual_flow | 官方入口 | 有受限用途 | 缺 | 有受限用途 | 缺 | 随主张限制 |
| 经间出血记录 · BODY-OBS-intermenstrual_bleeding | 官方入口 | 有受限用途 | 缺 | 有受限用途 | 缺 | 随主张限制 |
| 宫颈黏液记录 · BODY-OBS-cervical_mucus_quality | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 排卵测试记录 · BODY-OBS-ovulation_test_result | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| 腹痛或腹部痉挛日志 · BODY-OBS-abdominal_cramps | 官方入口 | 有受限用途 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 经期腹痛日志（既有来源字段） · BODY-OBS-menstrual_cramps | 未取得/非字段 | 有受限用途 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 睡眠呼吸暂停通知 · BODY-OBS-sleep_apnea_event | 官方入口 | 缺 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 高心率通知 · BODY-OBS-high_hr_event | 官方入口 | 缺 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 低心率通知 · BODY-OBS-low_hr_event | 官方入口 | 缺 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 心律不齐通知 · BODY-OBS-irregular_rhythm_event | 官方入口 | 缺 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 步行稳定性通知 · BODY-OBS-walking_steadiness_event | 官方入口 | 缺 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| 环境声音通知 · BODY-OBS-environmental_audio_event | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 耳机声音通知 · BODY-OBS-headphone_audio_event | 官方入口 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| 已记录跌倒次数 · BODY-OBS-number_of_times_fallen | 官方入口 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| W1 · W1 | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| W2 · W2 | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| W3 · W3 | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 缺 | 随主张限制 |
| W4 · W4 | 未取得/非字段 | 有受限用途 | 有受限用途 | 缺 | 缺 | 随主张限制 |
| W5 · W5 | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| W6 · W6 | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |
| W7 · W7 | 未取得/非字段 | 有受限用途 | 有受限用途 | 缺 | 有受限用途 | 随主张限制 |
| W8 · W8 | 未取得/非字段 | 有受限用途 | 缺 | 有受限用途 | 有受限用途 | 随主张限制 |
| E · E | 未取得/非字段 | 有受限用途 | 有受限用途 | 有受限用途 | 有受限用途 | 随主张限制 |

## 尚未验证或未完成

- 66题均已有受限说明，但只有15题在六段实取中覆盖测量、比较、机制/反例、行动四类用途标签；这不等于15题已完成独立六问充分性评审。字段定义链接、一般方法与特定设备测量验证分别计数。
- 事件及夜间部分字段现在可返回FDA设备情境和异常回应原则；它们没有验证Apple具体告警阈值、跌倒漏报、睡眠呼吸算法或适用年龄。腹部痉挛保留非月经特异身份，旧未知痉挛没有被强行认定为官方字段。
- 身高、部分营养与日照仍多是定义入口或通用比较；当前特定仪器纵向误差、明确机制及适用行动没有被de Vet等通用主张补齐。每个缺少的用途在上表/CSV明确列出。
- W2、W3、W4及血氧已绑定适用的行动/复评组，但在本次六段真实检索中仍未返回；这是召回/上下文预算缺口，不再写成资料完全不存在。W6日志复评、W7渐进活动及E事件回应已实际返回。W7机制/反例仍不足。
- 固定10题旧目标召回9/10，环境声旧目标主张未返回；已实取新的NIOSH声能方法和复评。未更换预期目标以得到满分，亦不因存在替代来源抹掉该计数。
- 65项来源的全文/目标章节、许可、阅读、逐主张审核和用途不是同一进度。M1/M6后续章、J1指定版本、H3目标章节、H4、T1目标章节、Plews全文、Kyle全文及具体BIA/DXA重复性仍缺。M5教材、S2/S3、T3和U1还存在明确的许可未核清或应用审阅缺项；已用许可明确的NIH/HHS/FDA/既有ACSM资料补可回答部分，不冒称这些目标原文已全部接入。
- NIOSH完整原文及自身声能推导/时长积分建议现已取得并审核；页面Leq离散时长加权是基于物理定义的推导，不是原文提供了某设备的个体听损预测。职业风险阈值和第三方引用没有开放。
- 私人远程生成未配置且无网络同意；不报告远程个体答案质量通过。公开embedding/reranker实跑不能替代私人生成验收。
- 阅读和受限主张均为AI辅助审核；未完成独立专家复核、实体人群外部有效性验证或全题人工建议具体性/完整度gold评审。各字段真实ZIP可得性不能由官方API定义或合成XML替代。
- 当前不存在整库正文/权利一键放宽。未经核清部分不进入RAG；收窄用途采用新主张版本及旧版撤销回执，保留历史版本、原文和冻结身份。

## 本轮命令和回归边界

`python -m pytest tests/knowledge -q --junitxml=artifacts/master_redesign/knowledge/knowledge-tests-final.xml` 首次结果为250通过、2失败。失败来自设置分区迁移后旧测试未进入“模型与资料库”即查找授权开关；保留原撤销/重新授权断言，补真实设置radio导航，重跑3例通过。最终公开问题及授权导航6例通过，见 `public-question-final-tests.xml`。新增公开来源+事实绑定27例通过；这些集合有重叠，不能相加宣称总数。最终完整冻结代码回归以总交付报告为准。

`ruff check src/healthzip/knowledge src/healthzip/ui/topic_sources.py tests/knowledge/test_public_question_sources.py tests/knowledge/test_async_explanation_consent.py tools/master_apply_source_reviews.py tools/master_finalize_source_inventory.py tools/master_rag_coverage.py tools/master_rag_browser.py tools/master_public_model_check.py` 通过。

公开模型最新实跑见 `public-method-model-final.json`：8个真实请求均收到响应；其中3次DeepSeek精排为3.768/7.079/12.132秒。增量生成10段、复用41段，无失败或降级。排卵试剂、E事件、环境声三题的词法/向量/融合/精排候选分别为3/3/3/3、3/5/5/5、10/11/11/11，全部返回实际原文绑定的有限说明。每次输出保持6段预算，未发送个人数值、日期或私人上下文。

浏览器最后执行使用本机可用的Chromium 158，命令：`PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu .venv/bin/python tools/master_rag_browser.py --output artifacts/master_redesign/knowledge/browser-final`。默认缓存缺版本、缺共享库，以及旧脚本未打开主题popover的早期失败未产出成功证据；最后回执来自真实当前页面点击。曾发现单点环境声图的微秒级刻度，现已修复并重跑浏览器；最后回执实际轴标签为分析时区的 `2026-11-20 02:20`，1440截图与390声能段落截图均已目视核对。
