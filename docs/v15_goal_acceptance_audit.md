# v1.5 完整目标验收核对

2026-11-17。以用户《HealthZIP v1.5：五领域知识体系与高准确度 RAG 架构升级》及既有 v1.4 合同为准。代码已接入、软件测试通过、检索质量通过和科学有效性是不同结论。本清单用于持续执行；整体目标尚未完成。

|工作包|已有可核对结果|尚未满足的验收|
|---|---|---|
|WP-A 架构及资料|[改动前架构审计](v15_knowledge_architecture_audit.md)、13文件清单、12实际来源身份/许可/解析报告、77指标配置；实际目录是仓库内 `资料/`。|复杂PDF结构、公式及第三方组件仍有未核对项；四本付费教材目标正文未取得，不虚称已导入。|
|WP-B 五领域模型|保留Source/Theory两库；领域归属、七种版本化证据边、主张/规则/指标关系、追加领域审核、冻结成员和历史行保护。|文件级 provisional 不代表全文逐领域核对；跨领域科学依赖仅限已记录边，尚非全部指标都有充分证据。|
|WP-C 接入及索引|12来源4114页、69183原文片段、216表格单元；父章节定位及精确页码坐标；44403项文档向量缓存增量复用。|21个完整结构单元超过模型输入预算，仍无向量；不允许固定字符裁切、截断或覆盖旧片段以消除缺项。|
|WP-D 混合检索|lexical/dense/RRF/chat listwise精排、当前资格/权利/条件、精确证据、冲突和拒绝审计。1.5.1修复精排候选丢失，增加相同K预算内的完整主张/显式依赖选择；126次开发回放证明已知题覆盖改善。|静态证据类型缺口不能由排序补足；聊天精排未证明相对融合的额外改善；没有自动原文矛盾识别。|
|WP-E 六功能接入|统一 `retrieve_for_metric` / `explain_metric`、CLI和分析页；longitudinal/recovery/metabolic/strength已有现行指标映射。|cardiorespiratory和cycle的现行77指标映射数均为0。页面显示缺MetricResult不等于完成这两功能的调用链验收，不能声称六功能均已接通。|
|WP-F 评测回归|原开发/家族留出及失败记录保持；Gold-2冻结21例，原A–E/词项126次实跑和另126次1.5.1开发回放分别保留；新回放各领域E召回/主张覆盖均高于同过滤词项。|Gold已暴露，开发改善不能替代独立验收；9个预期可答案例仍拒绝。独立新测试、分别运行的中文/英文/同义表达及独立答案语义裁决尚未完成。|
|WP-G 文档交付|五份要求文档、使用手册、设计/决策/状态已存在；[当前交付](v15_delivery.md)公开真实失败与限制。|本清单开放项清除且新证据齐备后才能形成最终验收；不能以推送一次替代完整目标。|

## 六功能调用链审计

实际路径为 `analysis_page.render_analysis` → `metric_evidence.render_metric_evidence` → `KnowledgeWorkbench.explain_metric` → `retrieve_for_metric`。统一入口要求已计算、同身份、经过合同校验的MetricResult。配置含六个功能，但各功能对应的现行指标数为：心肺0、长期18、恢复16、代谢11、周期0、力量34；指标可多功能复用，这些数不能相加作为77项覆盖率。

旧 `analytics.core.vo2_analysis` 返回设备估计点和Evidence Card，`cycle_analysis` 返回出血事件回顾和Evidence Card，两者未成为当前77项的规范MetricResult。后续需沿实际观测、来源、窗口和限制补齐受约束的适配/入口，清楚区分扩展合同与原77项；不能将旧P1输出改名冒充现行合同，也不能发明VO2真值、周期阶段或HRV到恢复的个人推断。此缺口不依赖四本付费教材，可以继续实施。

## 最终12项交付物

|要求|证据位置/实际状态|
|---|---|
|修改文件清单|每次Git提交和 `artifacts/v15/verification/`；后续修复单独提交，不改旧提交。|
|数据库迁移|[迁移说明](v15_migration.md)、`artifacts/v15/migration/` 及旧行保护回执；私人库未迁移。|
|新增资料完整清单|`artifacts/v15/sources/source_manifest.json`、`source_acquisition_report.json`。|
|权利审计|`artifacts/v15/sources/rights_audit.json`；未知组件待审、NC仅本地非商业。|
|五领域覆盖|[语料目录](v15_corpus_catalog.md)、`artifacts/v15/knowledge/`；来源数量不是科学覆盖率。|
|77项指标映射|`src/healthzip/knowledge/data/metric_domains_v15.json`；24项跳过RAG，29项有部分或完整静态绑定，运行时仍核对完整性。|
|Embedding身份|qwen3-embedding-8b，实测4096维；权重revision未核验，部署epoch承担缓存失效。|
|精排身份|deepseek-v4-flash，chat_listwise；不是已核验cross-encoder。|
|检索评测|[评测报告](v15_evaluation.md)、冻结Gold与原始126次评分；新增开发回放另存。|
|新旧性能|既有本地烟测/耗时回执及逐次查询耗时；不将并发单次观测宣称P95或用户设备加速。|
|未解决问题|本表及[交付限制](v15_delivery.md)。|
|复现命令|[迁移及运行](v15_migration.md)、`tools/v15_run_retrieval_benchmark.py --help`；原文/向量/凭据仅本地。|

## 保留的 v1.4 未完成要求

R01–R15、F01–F13、CAT/KB/E2E和77指标的软件证据继续引用 [v1.4验收](v14_delivery.md)、[知识验收](v14_knowledge.md)、[科学合同](v14_science.md) 与既有逐项矩阵。旧独立AI审核失败分母不重写，已知题通过不新增独立分母。四本目标版次教材正文、部分中文来源重用许可、独立专业审定、个人方法校准和真人时间外/因果验证仍按原状态保留。用户已说明暂时没有付费教材授权副本；先完成其余工作，不再重复索取。

最终验收仍须证明：具体指标能找到足够且适用的原始证据；跨领域结论具有完整显式依赖；证据不足、来源不适用或模型不可用时能够正确拒绝。WP-F的“没有优于lexical或领域明显退化时不能仅凭接入宣布完成”继续有效。
