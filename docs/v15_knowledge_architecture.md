# v1.5 知识架构（开发中）

本轮在 SourceLibrary / TheoryLibrary 上增量扩展，不另建五个数据库。v1.4 的历史审核、正文版本、冻结发布及评测保持原身份。当前不是 v1.5 最终验收通过声明。

五领域为 physiology、strength、wearable、recovery、cardiometabolic。文件、主张、规则和指标之间采用版本绑定；文件级 provisional 标签只是初始路由，不表示章节或科学主张已经审核。

SourceLibrary 增加 retrieval_parent_section、retrieval_unit、retrieval_unit_domain_review、retrieval_vector、retrieval_model_dimension 和 metric_retrieval_audit；超长JATS表格另以retrieval_projection_set保存不可变行组输入定位/哈希。Child 引用已有 Span，Parent 引用来源版本及章节路径，不复制五份正文。逐片段领域审核另存追加记录，原 provisional 记录保留。矛盾的领域审核要求显式修订索引，不能静默覆盖。

TheoryLibrary 增加 knowledge_domain_assignment 和 knowledge_evidence_edge。关系种类包括 supports、defines、limits、applies_to、conflicts_with、supersedes、required_by。边保留来源版本、精确片段、文本哈希、适用条件、审核身份及理由。绑定到指标的边还需要明确的应用审核及证据类型；不能借用别的主张的片段。关系本身不授予数值候选权限。

77 项现有指标见 `src/healthzip/knowledge/data/metric_domains_v15.json`。固定功能映射与指标依赖分开。纯账目、单位和覆盖计算跳过 RAG。基础生理和测量证据可以作为跨领域依赖；某项关键类型、必要领域或适用信息缺失时，来源解释权限保持关闭。

统一入口是 `KnowledgeWorkbench.retrieve_for_metric`；`explain_metric` 接入原 AI Explanation Contract。分析页可按固定功能和现有 MetricResult 查看原文、定位、局限及审计。CLI 原命令保留，并新增指标检索、资料导入、领域审核、关系绑定、向量构建及索引冻结。

现有77指标没有独立VO₂max或女性周期指标。新增两个明确区分的来源观测扩展，复用health_sample修订账本及MetricResult合同，保存于快照 `observations`；原 `metrics` 仍77项。实际页面可选择心肺/周期观测并调用统一检索，生产审核绑定仍缺，证据不足时拒绝。旧P1输出保持兼容身份，不作为新计算输入。六功能的完整科学接入仍须逐项核对，不能因入口存在便宣布科学验收完成；见 [来源观测接入](v15_source_observations.md)。

来源治理、章节解析、主张审核、应用规则、独立检索评测和真人科学验证分别报告。教材导入不会批准新主张；检索、Embedding 或聊天精排也不能改变现有 ApplicationRule 服务的候选权限。

本轮已逐段核对并建立 17 项指标相关主张绑定（16 项新增、1 项复用旧审核），覆盖 29 个指标、24 个精确片段；另追加 1 项历史来源立场及其条件绑定。审核身份均明确为 AI 辅助，未获得独立专家验证。实际主张、文本哈希、范围和边的回执见 `artifacts/v15/knowledge/`。24 个指标为确定性计算而不调用 RAG；静态类型覆盖与运行时真正检索到完整证据是不同状态，不能据此宣布六功能全部具备来源解释权。
