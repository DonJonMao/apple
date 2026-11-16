# v1.4 → v1.5 本地迁移（开发中）

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

可选的较长完整单元准入需要在 `embedding` 内成对配置 `tokenizer_endpoint` 和 `context_window_tokens`。本机实测为同源 `http://111.19.156.74:8001/tokenize` 及4096；必须以当前实际服务为准，不能从模型名称猜容量。配置只接受与Embedding相同scheme/host/port的 `/tokenize`，计数响应必须含完整token ID列表且容量与声明一致。它沿用资料联网授权，不处理私人记录；原始输入不截断。模板两字段均为null，保持原保守字节准入。

准入配置不属于向量数值变换，不改变既有模型缓存身份；显式续建只补获准的缺失完整单元，原向量和片段不覆盖。关闭时同时移除或置空两个字段；无需删除已生成的合法向量。后续本地向量补建不会改变既有冻结评测副本。

1.5.2在Source库追加 `retrieval_projection_set` 及父Span索引，表不存在时以幂等SAVEPOINT创建，私人库和Theory库不新增表。超限JATS表格可在同一 `build-vectors` 命令下生成 [结构行组投影](v15_structural_table_indexing.md)。原Span继续保留超限记录，投影完整性单独报告；不通过覆盖原文或删除排除项制造完整单元向量。所有子向量生成前，该父表不参与dense排名。回滚代码时旧版本忽略新表，原有向量和原文仍可读；需恢复数据时使用续建前两库备份到新目录，不能覆盖正在使用的库。

新冻结索引仅在存在投影时添加 `projection_set_ids` 字段；旧manifest及哈希不重写，读取缺省为空。既有冻结发布不会自动取得新投影。需要使用新结构索引时创建新的发布ID，保留旧ID及原评测目录。
