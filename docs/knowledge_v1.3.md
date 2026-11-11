# HealthZIP v1.3：本地知识库、采集与评测

> 2026-11-11 v1.3.1修复状态：本文中的原获取/审阅统计是 `0a943b4` 的历史基线。新许可作用域解析后，11张旧卡已置为 `needs_review`，当前有效approved为0，另9张仍为草稿；未授予真实数值候选权限。当前生命周期、许可范围和RAG支持语义见 [知识修复记录](review_knowledge_repairs.md) 与 [逐项验收表](review_fixes_2026-11-11.md)。

知识功能默认只读取本地证据。公开文献采集与发送私人健康数据是不同操作：下面的采集命令只请求公开来源标识，不读取训练数据库，不调用模型。现有 AI 解释的联网授权不会因采集文献而自动开启。

## 存储与版本

默认目录 `.local/knowledge/` 包含独立的 `sources.sqlite3`、`theories.sqlite3` 和内容寻址的 `blobs/`。私有训练库没有连接到这些 SQLite 文件。动作目录另由训练服务维护。

SourceLibrary 保存来源规范身份、别名、原始字节 SHA256、HTTP 记录、材料类型、解析器版本、许可、原文片段、表格、公式及获取/生命周期事件。DOI、PMID、PMCID 用于身份核对，题名近似不合并来源。R2/R3/E5 等组名展开为真实 canonical source IDs。同源在不同功能路由之间共享原文。

TheoryLibrary 保存原始草稿、逐主张证据、适用条件、审阅身份与记录、解释或候选能力、冻结发布。采集成功不会自动批准理论或修改计算公式。批准仅覆盖审阅文件中的选定主张，原始卡片其他主张/公式不会随之全部激活；历史批准还须满足当前生命周期及证据范围要求。

`release` 保存当时理论审阅和其确切 SourceVersion；`query --release` 用该快照检索。撤稿、修正待复核或理论撤销仍会阻止当前使用旧引用，历史依赖保留。相同发布 ID 不可改写。

## 安装和命令

核心使用标准库、SQLite 和既有 lxml；JATS 解析不需要新增依赖。解析获授权 PDF 时安装可选依赖：

```bash
python -m pip install -e '.[knowledge-pdf]'
PYTHONPATH=src python -m healthzip.knowledge seed
PYTHONPATH=src python -m healthzip.knowledge status
PYTHONPATH=src python -m healthzip.knowledge --output artifacts/knowledge/acquisition_retry.json acquire --fulltext
PYTHONPATH=src python -m healthzip.knowledge acquire --source S5 --fulltext
PYTHONPATH=src python -m healthzip.knowledge query '次数进阶有哪些研究依据？' --route progression
PYTHONPATH=src python -m healthzip.knowledge verify
PYTHONPATH=src python -m healthzip.knowledge release my-reviewed-release
PYTHONPATH=src python -m healthzip.knowledge query '次数进阶' --route progression --release my-reviewed-release
```

`--root`、`--spec-dir`、`--output` 是主命令参数，放在子命令前。来源采集支持 `--contact` 提供真实联系邮箱、`--timeout`、`--no-smoke`。不要编造联系人。源文件随软件打包在 `healthzip/knowledge/data/`，首次 `seed` 只有发现目录与草稿，不声称已取得正文。

当前适配器使用 PMC 新 OAI-PMH、Crossref 和 PubMed E-utilities。PMC 请求串行且间隔不短于其默认限额；遵守 Retry-After，长等待记录为待重试。首次批次实测了四个官方 API，包括 Europe PMC 生产端点。不存在旧 `oa.fcgi` 抓取流水线。出版商 CC 许可与内容版本匹配时可尝试其官方 TDM 链接；403 记录原因，不绕过。仅免费可读、普通 TDM 政策链接、镜像 URL 都不构成许可。

本地语料的声明用途为**内部、非商业研究和检索**。CC-BY-NC-ND 原文及明确仅允许 text mining 的材料不允许由此推断改编/商业再分发权限；保留完整原始字节，公共审阅工件不复制这类原文。Apple 字段文档的公开可访问性也不等同于允许把全文提供到网络知识服务，具体状态见权限审阅记录。

## 获授权 PDF / XML

使用 `import-document declaration.json` 导入合法取得、已核对身份的本地副本。声明必须包含 `source_id`、`path`、`license_id`、`rights_evidence_url`、`authorized_by`、`identity_review`；后者必须含 `decision: matched`、`reviewer`、`rationale`。许可声明是可审计输入，不是程序因为能读取文件而推定的授权。

```bash
PYTHONPATH=src python -m healthzip.knowledge import-document declaration.json
```

JATS 保存 XPath、原生 ID、段落偏移、节路径及表格/公式原 XML；表格单元格保留坐标和脚注，数值解释仍待审阅。PDF 保存文件页序号、文本层行块 bounding box 和阅读顺序；纸面页码无法可靠识别时保留 null。PDF 表格的单元格坐标和抽取结果待人工核对，图片扫描页不会冒充已 OCR，缺解析器会明确返回安装命令。字段完整或解析成功不代表表格单位、研究人群或公式含义已经核实。

## 审阅与候选能力

```bash
PYTHONPATH=src python -m healthzip.knowledge review reviewed-claim.json
PYTHONPATH=src python -m healthzip.knowledge source-state S5 withdrawn --reason '实际撤稿通知及定位'
```

`reviewed-claim.json` 对应 `KnowledgeWorkbench.review_theory()` 参数：theory ID/version、真实 reviewer 和 reviewer_kind、rationale、适用条件、逐主张 claims、每条 claim 的具体 span IDs/support_rationale，以及 source ID/version 的 evidence_links。不存在、错版本、许可未清或撤稿引用不能批准。

已存在的审阅内容不可在相同 theory ID/version 下改写；完全相同的重试返回原审阅时间。修改主张或升级权限，先执行 `revise-theory revision.json`，其中包含 `theory_id`、`from_version`、`new_version`、`reviewer`、`rationale` 和可选 `card_patch`。新版本始终是未批准草稿，不继承旧权限；随后针对新版本执行 `review`。旧版本和已冻结发布的原审核内容保留。

历史源文阅读审阅由 AI 辅助完成，身份明确记录，**不冒充独立专家审核**，权限为 `explanation_only`；本次11张旧卡均须复核。`reviewed_principles(route, context)` 另外核对候选能力：只有与所选策略匹配的显式 `progression_candidate` 或 `trial_candidate`、`qualified_human_review`、实施验证引用、非空必要适用条件、当前实际可用证据全部满足时，才返回计算服务所需能力对象。该对象仅支持确定性、用户可选择的试验候选，不保证成功或最佳效果。解释卡、模拟通过和 citation 数量均不能自行升级权限。

## 检索、AI 与离线降级

六个路由是 strength、progression、plateau、recovery、energy、personalization；跨路由扩展保存匹配词和理由。先按权限、理论状态、材料深度及适用范围筛选，再做可复核词项检索。缺证据时返回 `insufficient_evidence` 和具体排除理由。只有摘要时不能请求正文表格；未知人群/协议不能当作匹配。此版本不使用向量服务、图数据库或模型计算训练重量。

`query()` 可接收调用方已经授权、已经计算的 MetricResult；知识服务不会读取私有 SQL，也不会补缺失 RIR 或自行计算个人数字。文字中的计算事实按完整数值、单位、窗口、截止时点及版本原样输出。可选生成结果只允许选择已有完整句与观测对象，新增数值、方向、时间窗、行动或因果语句被拒绝后保留本地模板。检索到的原文指令不会被执行。

独立的 `healthzip.ai.client` 在网络边界使用最小投影：canonical 指标只发送标量数值、计数、状态、窗口及登记限制；嵌套记录、原始备注和 source record IDs 留在本地。已经适配为卡片的 canonical 指标也受同一规则约束。外发摘要从投影重新构造，本地回退仍保留完整指标与所有限制。模型事实的数值、单位、窗口、方向和算法版本必须同时匹配同一条已知事实，不能从多个时间窗拼接。

## 真实状态与评测

本次已对清单 **43 项**来源执行获取尝试，**29 项**科学来源已取得身份元数据；取得 **14 项不同来源**的获许可/明确允许内部使用的全文。原始字节和全部事件留在 `.local/knowledge/`。二次获取和解析版本修订可能使 version 数大于来源数，不能把它们当成更多独立论文。

**20 张**种子卡的历史审计中，**11 张**仅其明确定位的选定主张完成 AI 辅助阅读审阅，**9 张**为草稿。v1.3.1作用域迁移后，这11张旧卡均为 `needs_review`，当前有效批准为0；原审阅保留，见 `artifacts/review/theory_scope_upgrade.json`。历史每卡理由、可取得来源与未激活内容见 `artifacts/knowledge/theory_audit.json`；每来源获取、许可、版本、失败原因与重试命令见 `source_audit.json`。S3/S4 等主文权限、E2/E3/E4 等 free-to-read 非 OA 全文、N1/N2/N3 原文，以及 Apple 文档的具体网络再用权限均未伪造完成。M2 有版本匹配 CC-BY 线索，但官方全文接口实际返回 403。

```bash
PYTHONPATH=src python -m healthzip.knowledge --output artifacts/knowledge/rag_eval_cases_latest_eval.json evaluate src/healthzip/knowledge/data/rag_eval_cases.json --split visible_development --with-synthetic-metrics
PYTHONPATH=src python -m healthzip.knowledge --output artifacts/knowledge/rag_holdout_latest_eval.json evaluate src/healthzip/knowledge/data/rag_holdout.json --split source_family_holdout
python tools/prepare_public_artifacts.py
PYTHONPATH=src pytest -q tests/unit/test_knowledge.py
ruff check src/healthzip/knowledge tests/unit/test_knowledge.py
```

30 个公开开发案例与 8 个单独编写并冻结的来源家族留出案例分开报告。留出集 SHA256：`62b2e34ece6a655341aad0b6751b3d577f10955a85c9333f208615a2ef97ca62`。留出来源家族与开发集不重合；作者仍是实现代理，因此不称作外部盲测。语料扩充后可重跑相同锁定集，不能用其结果调参再声称独立。

评测报告分开列：结构字段、引用可定位、gold evidence groups 的实际召回与语料覆盖、有证据应答、正例拒答和人工语义裁决。引用都可定位也不证明其回答了当前问题；无引用时引用质量分母为零。当前开发集/固定留出gold召回为0/67、0/8；新冻结10例的独立AI审阅为7通过、3失败，独立人工分母0，语义验收未通过。旧卡待审导致的拒答不代表准确性提升。数值案例通过科学计算器的明确合成 fixture 生成，不在 RAG 中硬编码答案。RAG 软件测试不验证个人干预有效性。评测结果公开前须运行上面的公开投影命令，移除受限原文与本机路径；不公开本地数据库和blobs。

本次可重复验证包括知识契约测试、真实官方 API 获取、来源哈希检查和使用可选 pdfplumber 的合成 PDF 文本/页码/坐标验证。实际工件在 `artifacts/knowledge/`，状态字段分别表示 implementation、software_verification、corpus_acquisition、theory_review 和 scientific_validation，不能互相替代。

## 备份与恢复

停止知识库写操作后，完整备份 `.local/knowledge/`（两个数据库和 blobs 一起）及所采用的 release manifest。恢复至同一 `--root` 后执行 `verify`；单独恢复数据库而缺少 blobs 会报告缺原文。公共审计工件不是原始语料的替代；Git 中不包含私人健康数据库，受限材料也不应为方便交接而上传。

来源不可用时保留失败记录，之后用 `source_audit.json` 的逐来源命令重试。新抓取版本不会自动更新冻结理论/公式。要回到旧索引，使用已冻结的 `--release`；若来源已撤稿或审阅被撤销，旧 release 也不能绕过当前使用限制。
