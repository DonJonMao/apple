# v1.4 → v1.5 本地迁移（开发中）

1.5.7 不迁移私人 schema：S4 追加明确标记的作者预印本版本、6 个完整段落、2 项条件性主张及4 条指标边，新冻结发布为 `v15-rir-author-preprint-2`。初次失败的部分审核/发布保留，不用覆盖旧发布恢复。当前 S4 来源行仅 `updated_at` 因 `record_version` 更新，原 canonical manifest、旧版本、旧审核和此前工件不变；引用显示实际预印本身份。完整备份、失败恢复及复现条件见 [本轮迁移依据](v15_rir_preprint_evidence.md)。

实际修改前已经通过 SQLite backup API 备份两库至 `.local/v15/backups/pre-v15/`。旧公开知识工件和打包资源共 318 份，哈希保护清单保留于 `.local/v15/bootstrap/historical-protection.json`。备份包含已提交 WAL；没有改造私人健康或训练库。

新增领域、关系、索引、向量与审计表采用幂等 CREATE IF NOT EXISTS，不以 executescript 隐式提交调用者事务。写入使用 SAVEPOINT，调用者可整体 rollback。既有 Source、SourceVersion、Span、Theory、SourceClaim、ApplicationRule 和发布行保持原身份。新增文件的原始字节按 SHA256 去重保存到本地 blobs。

已有无标签记录不自动获得内容审核。文件级领域标签为 provisional；逐片段领域核对以追加表保存，不覆盖最初标签。不将旧自然语言问答的 answer_task 强加为新指标绑定的必要身份；新路径复用原 `_claim` 对精确证据、状态和审核身份的校验。

历史逻辑迁移追加了62个旧主张版本、97个规则版本、4个已审核主张来源版本及850个原文单元的 provisional 归属；重复运行对照见 `artifacts/v15/migration/`。随后7个研究来源解析版本增加369个 provisional 检索单元，实际阅读的片段再单独追加内容领域审核，没有整篇自动升权。

`tools/v15_apply_reviewed_bindings.py` 只重放已署名、已定日期、已固定精确文本哈希的本地审核包，不能替代科学阅读。工具在写主张前检查原文和索引注册，保存两库备份，保留旧主张及审核的不可变身份。首次因未注册研究片段中止的回执也保留；已添加的同一主张在重试时原样复用。回执不授数值候选权限。

机构首页不是不同手册的唯一 manifestation。新资料按实际文献/版次登记；Army 两份文献需要不同的文献身份。原有 HHS 来源复用 CORE-US-HHS-PAG-2，不复制其科学来源。

本轮早期同字节 PDF 解析记录遇到更严格的图注/第三方范围政策时，新增解析/范围版本并建立 parse_supersession，保留旧字节、片段和历史记录。只处理本轮新导入器的早期版本，不静默改写 v1.4 的原文或审核。

回滚应停止应用，先备份当前库，再将 pre-v15 备份恢复到新目录并验证，最后通过本地配置切换目录。不要覆盖正在使用的 SQLite，也不要删去新取得的原始 PDF。关闭新 UI 入口/切回已发布 v1.4 代码不会自动删除本地新增表。

可复现入口：

```bash
.venv/bin/python -m healthzip.knowledge metric-profiles
.venv/bin/python -m healthzip.knowledge import-corpus artifacts/v15/sources/source_manifest.json 资料 --parse-cache .local/v15/parses
.venv/bin/python -m healthzip.knowledge build-vectors --batch-size 16 --workers 4
.venv/bin/python -m healthzip.knowledge metric-retrieve .local/request.json --mode hybrid_rerank
.venv/bin/python -m healthzip.knowledge freeze-metric-index release-id
.venv/bin/pytest -q tests/knowledge
```

`request.json` 使用已计算的规范 MetricResult，不能让模型编造该结果。模型配置位于知识根目录 model-services.json，模板默认拒绝联网；实际运行还需用户已授权的本地配置。

可选的较长完整单元准入需要在 `embedding` 内成对配置 `tokenizer_endpoint` 和 `context_window_tokens`。本机实测为同源 `/tokenize` 及4096；必须以当前实际服务为准，不能从模型名称猜容量。配置只接受与Embedding相同scheme/host/port的 `/tokenize`，计数响应必须含完整token ID列表且容量与声明一致。它沿用资料联网授权，不处理私人记录；原始输入不截断。模板两字段均为null，保持原保守字节准入。

准入配置不属于向量数值变换，不改变既有模型缓存身份；显式续建只补获准的缺失完整单元，原向量和片段不覆盖。关闭时同时移除或置空两个字段；无需删除已生成的合法向量。后续本地向量补建不会改变既有冻结评测副本。

1.5.2在Source库追加 `retrieval_projection_set` 及父Span索引，表不存在时以幂等SAVEPOINT创建，私人库和Theory库不新增表。超限JATS表格可在同一 `build-vectors` 命令下生成 [结构行组投影](v15_structural_table_indexing.md)。原Span继续保留超限记录，投影完整性单独报告；不通过覆盖原文或删除排除项制造完整单元向量。所有子向量生成前，该父表不参与dense排名。回滚代码时旧版本忽略新表，原有向量和原文仍可读；需恢复数据时使用续建前两库备份到新目录，不能覆盖正在使用的库。

新冻结索引仅在存在投影时添加 `projection_set_ids` 字段；旧manifest及哈希不重写，读取缺省为空。既有冻结发布不会自动取得新投影。需要使用新结构索引时创建新的发布ID，保留旧ID及原评测目录。

心肺/周期的两个 [来源观测扩展](v15_source_observations.md) 直接复用私人health_sample修订账本，不迁移私人schema，不读取旧P1卡作为计算依据。新快照保留77项 `metrics`，另添2项 `observations`，分析算法/缓存版本更新为v1.5，历史快照不覆盖。默认指标和领域配置仍77项；CLI使用 `metric-profiles --include-observations` 明确查看扩展。新发布只有实际包含扩展绑定时才追加并核验 `observation_profile_sha256`，原配置文件和旧发布不改。

## 固定查询形式及观测审核导入

`metric-hybrid-1.5.4` 的固定表达登记与原77项领域配置分开，默认查询不变。新索引发布新增 `query_forms_sha256`，没有该字段的历史发布继续允许原组合查询，需检索的任务不能显式获得新增形式；新登记内容变化后，已冻结发布拒绝配置漂移。字段只存在新发布的manifest内，没有私人数据库迁移。成对评测须使用新的本地副本及输出目录，原Gold/评测副本不改。详见 [固定查询合同](v15_fixed_query_forms.md)。

`tools/v15_apply_reviewed_bindings.py` 可导入原77项或两个明确观测扩展的审核包，使用各自profile版本和必要证据类型；扩展不会被标成基础 `metric-domains`。新审核追加至原两库，保留旧逐行数据及备份。获准处理的原文、具体审核包和数据库备份留在本地，GitHub仅发布哈希、精确定位、审核身份与范围回执；未知许可、缺审核和缺条件仍不授权。

### 追加来源审核的本地变更

VO₂与周期各追加两项有限的AI辅助来源主张和既有观测扩展绑定，不迁移私人库，不改原77项配置，不新增数值候选规则。周期另行获取CC BY 4.0的AWHS 2023 JATS主文，登记50个Span、增量生成49项向量并复用1项；文件级领域仍provisional。原28张知识表的旧行按逐行哈希保护，每次应用审核包前另做SQLite备份。公开回执仅含元数据、定位、范围及哈希，正文、审核包和数据库留本地。详见 docs/v15_source_observations.md 及 artifacts/v15/sources/cycle-source-acquisition-review-1.json；历史冻结成员不自动获得新主张或查询表达。

## 限定指标依据的兼容范围（1.5.5）

`candidate_scope`是调用参数，不改变原77配置或私人schema；API默认all保持原查询身份。新索引manifest增加 `candidate_scope_version`，固定 `reviewed-metric-candidates-1.5.0`；历史manifest缺省只能使用原all范围，显式采用新范围必须创建新的发布ID。范围版本漂移时拒绝新冻结发布；不重写旧manifest。页面新增“依据范围”并默认已审核指标依据，仍可选择同领域阅读。此次不增加来源主张、应用规则或数值候选权限，来源和审核仍使用前一批已取得的数据；详见 [范围合同](v15_reviewed_metric_scope.md)。

本轮1.5.6不迁移私人库或重写旧rights JSON。来源用途在运行时由结构化许可推导，旧冻结发布也遵守当前NC限制；审计追加rights_usage_policy_version。已有S5/R5版本补接150个provisional单元，并在两库SQLite备份后使用既有审核工具追加4条主张及11条边，原E1内容和审核原样复用。当前发布为v15-method-boundaries-rights-1，旧发布不获得新单元/绑定。回滚/迁移、许可复现和失败记录见 [本轮说明](v15_method_evidence_and_rights.md)。

评测工具新增候选范围参数和Gold冻结回执的 `candidate_scopes` / `candidate_scope_version`，不需要数据库结构迁移；缺省仍all，旧回执不隐式获得新范围。新增来源Quer 2020在两库备份后追加公开来源版本和41个provisional单元/向量，没有审核主张或私人库变更。专用评测副本的 `v15-prospective-rhr-source-4` 发布固定当前成员、查询及范围；主知识库原发布身份仍保留。原文/向量只在本地，公开运行身份使用服务摘要和哈希，完整恢复身份留本地。详见 [本轮范围评测](v15_scoped_prospective_evaluation.md)。
