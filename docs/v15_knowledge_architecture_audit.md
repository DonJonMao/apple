# v1.5 知识架构实施前审查

审查日期：2026-11-16（Asia/Shanghai）；基线 `41ed29a3d4783206bf1911a39c59296b8865f80f`。本文件在新增产品代码前生成。此前1446项整仓通过属于v1.4，不能算v1.5验收。

## 实际架构和调用链

`KnowledgeWorkbench`持有`Libraries`，公共来源在sources.sqlite3，理论在theories.sqlite3；私人训练Repository另库。来源已有source/alias/version/span/acquisition_log/source_review/source_version_clearance/scientific_notice/parse_supersession/index_release/chapter_coverage。理论已有theory/theory_review/theory_release/theory_lifecycle/source_claim/application_rule/core_lifecycle/core_release。当前本机行数：`{"source": 50, "version": 210, "span": 3992, "theory": 20, "source_claim": 62, "application_rule": 97, "core_release": 15}`。

现有`query`→`route_question`六个旧主题→`resolve_named_sources`→`retrieve`→当前/冻结理论成员→来源状态、精确span许可和适用性筛查→规范化主张任务→词项TF/IDF样式排序→展示。`assess_support`在全部符合条件的主张上检查冲突，不能先截top-k。旧六个route（strength/progression/plateau/recovery/energy/personalization）并非本次五个知识领域，保留兼容。当前`lexical-1.4.2`没有dense/向量缓存/精排。逐主张回答与精确证据链接、原文与规则权限分开，不能用相似性替代支持关系。

`science/engine.py`执行77项MetricResult，`analytics/v13.py`适配真实Repository；`ai/client.py`只解释已经计算的合同，网络需要显式同意。新检索入口应只向模型发送固定指标/任务说明和经过许可核验的公共证据，不传私人指标值、日期、记录ID或上下文备注。

## 历史评测与保护

既有开发集和来源家族留出分别报告，旧语料评估曾记录14/67充分证据组、0/8来源家族留出；不同版本结果不合并。第七批独立AI16题为7通过/5部分/4失败、32/52支持点；随后已知题开发16/16、52/52以及k12任务状态修复均不增加独立分母。它们证明开放问答的边界，不能充当本轮指标检索提升。原始来源包、问法、输出、裁决不改写。

本轮已冻结318份既有知识源码数据/评测工件的哈希，私有保护清单位于`.local/v15/bootstrap/historical-protection.json`。两库SQLite完整备份位于`.local/v15/backups/pre-v15/`，未改私人训练数据库。

## 实际资料与身份风险

`/资料/`和用户主目录`资料/`不存在；实际可访问目录为仓库`资料/`，共13份PDF、4120页。12份资料加1份ChatGPT推荐清单；推荐清单不是科学来源。文件字节清单和前10页解析在本地。实际Anatomy & Physiology 2e是Oregon State University 2025、Biga等改编版、CC BY-SA 4.0，不能冒充清单中OpenStax/Rice 2022版。WHO 9789240116696的PDF元数据错误写为助听服务，封面及版权页实际是2025可穿戴活动测量会议报告；以正文核对并保留冲突。

Lanphere第3版（2025）、MacIntosh Version1.0（2025）及WHO资料包含NC条款；仅允许经声明的非商业本地使用，不授予商业重用或公开全文/向量。Army/NIH/FDA等须记录美国政府正文及第三方内容范围，公开发布不限量不自动给所有插图授权。FM7-22带2025年Change2，ATP7-22.01带2022年Change2，旧版及新版本状态须分开。只有目录、下载清单不能证明正文完整或主张审核。

## 服务实测

用户提供的Embedding服务实际响应`qwen3-embedding-8b`，4096维；聊天服务响应`deepseek-v4-flash`，严格JSON排序烟测通过。后者是聊天式列表重排，不能称为已验证独立cross-encoder。服务没有提供可验证权重revision，必须标注版本未核验并让缓存身份包含配置版本/部署指纹。访问令牌仅存本地忽略目录；端点/模型可作为默认值。只授权公共证据网络调用，私人健康网络授权保持关闭。

## 实施差距与模块

新增五域配置、77指标/六功能固定映射；以版本化对象关联表/证据边补充原两库，不复制来源或主张。新增结构化PDF章节/父子块与解析质量、公开元数据审计；复用SourceVersion/Span和原资格判定。大PDF超过旧20MB导入限制，新导入器须逐页处理并明确产品文件预算，不改写原解析版本。

新增EmbeddingProvider/RerankerProvider、身份严格的增量向量缓存、词项+dense RRF与有界精排；任何当前来源撤回、审核撤销或适用性失配先于排序生效。新API`retrieve_for_metric`为服务/页面提供统一Evidence Context；原query默认保持原行为和历史评估。提供CLI及配置模板、模型失败降级、无知识需求的算术跳过、跨域缺项与冲突审计。

评测必须新建独立固定Gold，覆盖五域/跨域/中英/结构化证据/拒绝条件，对照A–E五组和11项指标；作者构造软件例子和真实模型烟测不等于独立检索效度。不能反复用旧留出调参。未获独立Gold或未证明提升时保留未完成状态。

保留：77指标数学合同、原始来源/审核/冻结发布/旧评测/私有数据、现有CLI/页面、候选权限与LLM解释限制。修改：新入口的懒加载迁移及模型配置；可选依赖保持小型。剩余v1.4器械档位入口与候选/反馈规模路径仍需实际复现，本轮继承不丢弃。

## 迁移与兼容风险

两库的附加表按savepoint创建，重复打开幂等；既有行内容/审核/成员不改，失败回滚新表。领域标签初始标注provisional及真实AI作者身份，不自动批准主张。新的领域/metric绑定必须指向确切对象版本和真实证据；来源更新时依据span/version链接反查受影响对象。模型或输入哈希变化产生新索引身份，禁止混维度或混部署缓存。没有已核验正文/许可/主张时明确缺项，并继续其他可独立完成阶段。最终迁移验收须比对备份行值及历史保护哈希。
