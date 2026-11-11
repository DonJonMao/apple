# R05、R06、R15 与 RAG 回答支持修复记录

审查基线为 `0a943b49638247e16197cf7fa768cde33f5d0901`。本记录对应 2026-11-11 的实际执行，不把软件门控通过写成专业主张或个人效果已验证。基线使用独立临时知识库和合成文本，结果保存在 [knowledge_baseline.json](../artifacts/review/knowledge_baseline.json)。未访问私人健康数据库。

## 逐项复现与修复

| 项目 | 触发与实际旧结果 | 原因与改动 | 修复后检查 |
| --- | --- | --- | --- |
| R05 撤销 | 已审 0.1.0 再提交 `needs_review` 报 immutable；原主张仍返回 | `store.py` 将不可变审阅内容与当前状态分开；增加 append-only `theory_lifecycle`，API/CLI 提供停用、撤销、待审和受限恢复 | 错误单卡可独立撤销，不需撤回正确来源；原 `review_json` 不变；当前和指定历史 release 的检索均重新检查当前有效性 |
| R05 替代 | 新版 0.2.0 批准后，旧新版同时返回 | 新版明确 `revision.from_version`；审核通过时记录 `superseded_by` 并使旧版 superseded；未审草稿不替代旧版 | 只返回新版；被撤销/替代/待审内容不能经 `disabled → activate` 洗回有效；暂时停用的未变更批准须依赖仍有效才可恢复 |
| R06 许可范围 | 主文 All rights reserved，单图 CC BY；旧版把整篇 index/redistribution 置 true | 新 `rights.py` 按 article、sub-article、fig、table-wrap、supplementary-material 建范围；`parse_jats` 给每个 span 附独立范围，主文章身份只读主 front/article-meta | 受限正文/表保持不可用，合法子文章/组件可单独可用；冲突、未知位置和组件限定不扩大到文章 |
| R15 更正状态 | corrected_pending_review 下旧 span 被阻断，仅写入新 metadata 后变 acquired 并恢复 eligible | `store.py` 分离 acquisition_state、scientific_state、scientific_epoch；fetch 只更新获取状态 | metadata、abstract、fulltext 重试和普通 acquired 更新都不解除更正；withdrawn 不被较低级别更新覆盖；cached span 也查询当前状态 |

R05/R15 的操作入口是 `KnowledgeWorkbench`、`python -m healthzip.knowledge theory-state`、`review-source-state` 与既有 `review`/`revise-theory`。界面“来源获取与理论审核状态”显示待审理论、依赖阻断和有效批准数量。它们属于知识管理流程，不由训练记录页面模拟授权。

R06 明确覆盖 `Figure only`、`Figure 1 only`、`applies only to Table 2`、`solely for supplementary material` 的组件限定反例。有限语法识别是保守范围检查，不是一般自然语言法律判断。多项不兼容许可、保留全部权利与许可并存、文章 metadata 之外的模糊许可保持 pending。子文章不自动继承主文许可。授权导入和 publisher XML 同样使用 `jats-scoped-1.4.0` 解析版本，组件内限制不会被版本级外部声明直接覆盖。

R15 的显式清理必须指明审核者、理由和具体 source_version_ids，只适用于当前 scientific_epoch。审核一份元数据不能解除其他全文版本；新更正再次阻断旧清理；撤回不能通过普通版本清理恢复。来源被清理也不会自动重新批准其理论。release 现在逐个检查引用 span 的当前许可与精确版本清理，不用文章总许可或 source 总状态替代组件判断。

## RAG：检索相关性与答案支持分开

基线合成问题“次数进阶能否证明个人寿命增长？”得到次数方案主张，并被标记为 `evidence_supported`。原逻辑只要词法分数大于零并返回 claim 就视为回答支持。

新 `support.py` 要求逐主张审核中的 `answer_bindings` 明确问题、目标 proposition、人群/时间等 scope、`supports/refutes/qualifies` 关系及理由。目标来自显式结构化 target_claims 或已审问题的规范化精确匹配。词法排序仅用于查找阅读材料，没有新增相似度阈值，也没有用固定留出调参。

没有明确目标或匹配关系时返回 `related_material_only`，答案 claims/citations 为空；来源陈述列为 related_materials。目标范围不合、部分覆盖、限定性证据和互相冲突分别保留未知、partial 或 conflicting 状态。引用只含真正对应所输出 claim 的 spans。目标及关系进入 evidence_bundle_hash，生成校验拒绝修改它们。知识页面增加已审问题选择及目标/范围/关系展示，相关阅读展开项注明“不等于当前问题已获支持”。已有真实卡没有这类 binding，不能凭旧审核自动获得任意问答权限。

这是一个有意有限的问答合同：未审自由表达即使同义，也可能只返回相关阅读；精确 binding 本身仍可能标错关系。软件不能证明审阅内容正确，不能据此宣称一般 RAG 问答已验收。

## 新冻结案例的独立 AI 审阅：7/10，仍失败

冻结包 [rag_semantics_frozen.json](../artifacts/review/rag_semantics_frozen.json) 含 10 个新合成问题及精确输出、证据、目标、范围。文件 SHA256 为 `ccf673fb1ff6732d2c81983be89d5fd9b2fda5299273995ebded537b83fb6e93`；生成器拒绝覆盖既有包。独立子代理仅阅读问题、上下文和 review_packet，没有收到预期标签，也未阅读实现生成器或测试预期。

[独立标注](../artifacts/review/rag_semantics_independent_ai_annotations.json) 与 [校验结果](../artifacts/review/rag_semantics_independent_ai_results.json) 原样保留。每份标注绑定 case_id、question_sha256、output_sha256、evidence_bundle_hash，并分别判定“是否回答目标/范围是否正确/关系是否有据”与逐引用证据关系。10 份标注全部通过完整性校验：独立 AI 7 pass、3 fail；独立人工分母 **0**。

| 失败案例 | 独立审阅结论 |
| --- | --- |
| NEW-02 | 原文已明确没有测寿命；回答仅给相关阅读模板，避免了夸大但没有完成具体问答 |
| NEW-05 | 原文不能给明日个人体温结论；回答仍是泛化相关阅读模板，未充分回答目标 |
| NEW-06 | 同范围原文直接支持所问许可，binding 却标 qualifies，造成关系和完整性判断错误 |

结果 gate 为 `failed_independent_review`。没有修改冻结问题、binding、输出或标注来抹去失败。独立 AI 审阅不计入 `semantic_reviewed` 的独立人工分母，不等于独立人类、专业审阅或科学验证；审阅者身份/独立性为审计声明，程序不能认证专业资质。后续修复语义覆盖需要新的独立冻结案例，不能在此包上宣称盲评提升。

## 实际公开语料与旧审核的处理

在既有本地公开文献库中，对 **16 个已获取全文版本、14 个 distinct sources** 的原始字节核对 SHA256 并重解析；没有网络新增获取。来源为 E1、E6、E7、E8、R2b、R3b、R4、R5、R6、R8、S1、S5、S6、S7。全部有可用的新 scope spans；这不说明旧 14 篇全部存在违法扩大，也不构成专业或法律确认。详见 [source_scope_reparse.json](../artifacts/review/source_scope_reparse.json)。

新解析是新增版本，旧原文和旧解析保留。旧机器 JATS 许可没有 scope_policy_version 时标 `legacy_jats_scope_review_required`，不冒充新范围已复核。旧 11 张卡都依赖旧版本，因此通过 actor=`scope_policy_upgrade` 的 lifecycle 事件显式置 **needs_review**；原不可变 review 的哈希逐卡记录并核对，authority 仍是 **explanation_only**，没有自动绑定新 span、增添答案 binding 或升级数值候选权限。详见 [theory_scope_upgrade.json](../artifacts/review/theory_scope_upgrade.json)。

当前实际状态：43 来源身份、29 已获取科学材料来源、14 distinct 全文来源；105 metadata、52 abstract、32 fulltext 版本（其中 16 为新解析，不应写成 32 次独立全文获取）；共 189 版本、2164 spans，1007 当前可检索 spans。理论为 11 needs_review、9 draft，当前有效批准卡 **0**。需要逐卡复核新版本的 exact span/定位、原主张与适用范围后创建显式新修订；该人工工作没有伪造完成。

## 原可见集和固定留出重跑

使用实际当前语料重跑 30 个可见开发例及原 8 个固定留出，带已有明确 synthetic metric provider。没有改题目或 gold。留出 SHA256 仍为 `62b2e34ece6a655341aad0b6751b3d577f10955a85c9333f208615a2ef97ca62`。

| 当前评测 | schema | gold group recall | 已审可用 gold groups | 引用总数 | 路由匹配 | 独立人工语义 |
| --- | --- | --- | --- | --- | --- | --- |
| [visible30](../artifacts/knowledge/rag_eval_cases_latest_eval.json) | 30/30 | 0/67 | 0/67 | 0 | 23/30 | 0 分母 |
| [fixed8](../artifacts/knowledge/rag_holdout_latest_eval.json) | 8/8 | 0/8 | 0/8 | 0 | 3/8 | 0 分母 |

两者 gate 均为 `pending_corpus_and_semantic_review`。引用为零时引用质量率不可计算，不能写 100%。当前可用 gold 为零来自上述旧审核明确待复核，不是新重解析全文消失，也不能把停答当作语义准确率提升。旧 visible_eval/holdout_eval 保留为历史工件，不代表当前结果。

已运行 `tools/prepare_public_artifacts.py`：四个实际语料评测工件只公开引用ID、版本、文本哈希、定位与许可白名单，保留原 output hash 和独立公开 projection hash；新增 scope_policy_version、scope_id、scope_kind、inherited_from_scope，未加入含许可原文的 component_scopes。JUnit 的 hostname、本机 home/repo/pytest 临时用户路径一并脱敏，保留断言、测试结果与原始文件 hash。合成冻结包仍可公开其明确标记的合成证据文本。

## 验证与五维状态

实际运行：`PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_review_knowledge.py tests/unit/test_knowledge.py --junitxml=artifacts/verification/review-knowledge-fixed.xml`，**34 passed**。覆盖 lifecycle、历史 release、supersession、停用绕过、更正缓存/精确版本/新epoch、文章/组件许可、局部许可 release、重解析不重批、相关性/目标范围/冲突关系、真实 Streamlit AppTest 以及独立标注绑定拒绝。相关生产代码、测试、生成器和 publication 工具的 Ruff 通过。整仓验证另见总修复交付。

| 维度 | 当前证据与限制 |
| --- | --- |
| implementation | R05/R06/R15 状态与范围门控、问答支持合同、UI、标注/评测路径已实现 |
| software_verification | 本模块 34 项回归和 Ruff 通过；独立语义审阅失败不得计为软件单元测试通过后的自动验收 |
| corpus_acquisition | 14 distinct 全文来源，本轮16版本本地重解析；43来源中仍有未获取全文 |
| theory_review | 历史11卡的 explanation_only 审阅原样保留，当前11卡needs_review；无有效新批准和无真实数值权限升级 |
| scientific_validation | 独立 AI 7/10，三项失败保留；独立人工0，未认证专业支持关系，未验证个人预测或干预效果 |

主要改动：`knowledge/store.py`、`rights.py`、`acquisition.py`、`documents.py`、`support.py`、`retrieval.py`、`adjudication.py`、`evaluation.py`、`workbench.py`、`__main__.py`；`ui/knowledge_page.py`；`tests/unit/test_review_knowledge.py`、合成 scoped permissions 夹具、`tests/review_rag_freeze.py`；`tools/prepare_public_artifacts.py`。原 `tests/unit/test_knowledge.py` 的正向合成例补显式 answer binding，避免把相关性当作旧正向预期。
