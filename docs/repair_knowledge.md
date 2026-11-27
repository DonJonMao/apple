# 2026-11-27 RAG 修复与逐项证据

本轮在 `88de09a` 当前工作区继续修改，未回退、清库或修改既有审核身份。只对 `.local/knowledge` 的两个公共资料 SQLite 做 backup 到 `/tmp/healthzip-repair-knowledge-20261127` 后验收。没有读取私人健康库，没有调用个人生成模型，没有重复下载已有原件。本文只覆盖 F07/F08 和 T14–T18；整体验收以本轮总交付为准。

## 用户能看到的变化

身体指标和复盘问题的“依据与原文 → 查阅本题依据”现在同时保留可用的方法说明、来源及完整限制。某个机制主张冲突时，仅该主张和明确依赖它的行动受限，独立测量说明和独立行动继续显示。争议内容在“有分歧的说明与受限建议”中明确不用于确定建议，不采用多数票或最高检索分数裁决。

血氧原有测量说明之后，现在还可看到怎样记录读数日期、时间和实际症状以复核的 FDA 来源说明；指夹资料不能验证腕上测量、不设个人报警线的限制保留。W2 补回测量情境记录，W3 补回活动频次/时长与耐受复评，W4 补回目标及可比任务核对。没有用新增模型调用或医疗阈值填充内容。

## F07：冲突定位及当前有效性

- `knowledge/metric_retrieval.py::_metric_claims` 在既有 `conflicts_with` 和 `required_by` 关系上，按 claim ID/version 和完整依赖闭包查找相关冲突。即使前提没有直接绑定本题，其争议也会限制依赖行动。冻结版本范围、当前撤销、许可、人群和完整证据组门禁保留。
- `claim_conflicts` 只返回触及本主张或其明确前提的冲突。`knowledge/topics.py::question_sources` 输出 `items`、`restricted_items`、`conflicts`，不再整题清空。
- `knowledge/health_facts.py::measurement_explanations` 采用同样局部检查，避免健康详情中独立方法说明仍被整项冲突清掉。原有严格“整套个体解释”权限没有被放宽；一般测量说明不授予个体原因或数值处方。
- `ui/topic_sources.py` 展示每项完整限制和可展开的研究人群、设备、协议等范围；依赖争议的建议明确受限。

`tests/knowledge/test_repair_question_evidence.py` 使用真实 Source/Claim/审核/域/用途边和检索路径构建两个冲突机制、独立测量、依赖行动、独立行动。精确断言只剩独立测量和独立行动可用，三项受限；另测没有直接题目边的争议前提。

## F08：一次有界补检索及真实结果

原初检预算仍为 6 段。根据本题请求的用途与初检结果，只有本地已存在适用的完整审核组而该用途未返回时，才增加一次至多 6 段的本地词法补检索。补检索只从已审核的精确题目绑定补入缺失用途 anchor，完整依赖及限制一起选入；不拆证据组，不提高全局 top-k，不额外调用远程模型。调用者可以用 `required_purposes` 指定当前短回答实际需要的用途；无相应用途资料时不为凑标签重复查询。

这是产品检索预算，不是统计或医学阈值。主张审核 profile 身份和旧冻结资料不变；新检索回执增加 `bounded-topic-use-1` 身份。原初检、补检索、未覆盖用途、排除原因、预算及完整组缺口分别保留。

| 题目 | 修复前实际缺失 | 现补回的既有主张 | 全部独立原文段数 |
|---|---|---|---:|
| W2 | 行动/复评 | MASTER-HR-CONTEXT | 8 |
| W3 | 行动/复评 | MASTER-ACTIVITY-GRADUAL | 9 |
| W4 | 机制/例外、行动/复评 | MASTER-PROGRESSION-GOAL | 7 |
| 血氧 | 行动/复评 | MASTER-OXYGEN-FOLLOWUP | 8 |

66 题的四用途标签齐全从 15 题变为 29 题，**不代表 29 题六问内容充分，更不代表设备验证通过**。固定旧目标仍有 1 项（环境声旧目标）未命中，9/10 的失败分母未改。旧工具的 `topic-coverage-after.json` 沿用 `known_source_recall_at_six` 字段名，它实际上统计的是补检索后的结果，不能用它宣称单次 k=6 达标；应以 [完整新回执](../artifacts/repair_knowledge/retrieval-audit.json) 的 6+最多6 预算为准。

初检历史回执保留在 [before](../artifacts/repair_knowledge/topic-coverage-before.json)；完整回执包含逐题原初检和补检索、用途缺口、排除原因、引用和主张版本。工具 `tools/repair_knowledge_audit.py` 可重现，额外网络调用为零。

## 内容核对和六问矩阵

[396 行六问内容矩阵](../artifacts/repair_knowledge/six-question-content-matrix.csv) 将取得、阅读、审核、索引、检索、页面使用分别记录。用途标签只记录召回，不能直接升级为“已有并正确使用”。本轮实际重读了 Quer、Carter、SDNN 方法、Robbins、de Vet、HR 情境、FDA 血氧跟踪、HHS 渐进活动和 ACSM 目标的已绑定原文段落；人群、设备/协议/观察单位、能说明什么、不能推断什么、原文定位及原审核均在 [补核笔记](../artifacts/repair_knowledge/passage-reading-notes.json)。这是 AI 辅助段落复核，没有把未整篇重读记成全文阅读，也没有新增专家权限。

另完整核对已合法留存的 7 个 Apple DocC 原件的 abstract/content sections，记录在 [官方字段核读](../artifacts/repair_knowledge/official-field-reading-notes.json)：

- RHR 官方描述区分静息估计与运动后坐下的 sedentary HR，并可能替换当前/前一天估计；SDNN 明确是正常 RR 间期的标准差，不是 RMSSD。
- 腕温字段是绝对腕部温度的夜间聚合，健康 App 相对基线显示是另一层含义；不能当核心体温。
- 呼吸率和血氧字段页只提供类型/单位等有限定义，不能当设备精度或整夜覆盖验证。
- 保存的睡眠呼吸紊乱和睡眠呼吸暂停事件 DocC 只有符号声明，没有 abstract/Discussion；不能计为解释正文完成。

这些原件现有 `index_allowed=false`、`redistribution_allowed=false`/待条款审核状态保持。本轮没有把链接、类型声明或自行阅读偷偷升级为可检索主张；没有为无设备验证的字段伪造说明。

## 模型核验和失败状态

现有事实核验绑定同一 fact ID 的值、单位、日期、统计量、覆盖、窗口、算法和方向。本轮独立测试额外构造错误数值、错误日期、错误宣称“没有提供疲劳”以及混合正确/错误段落：错误事实退回本地；仅说明段错误时保留已核验段落；本地事实对象及图表输入不变。未配置、未授权、超时、HTTP 服务失败、无适用审核证据、输出核验失败分别在 `reason_code` 或 `evidence_context.status/limitations` 保留，并由现有 UI 分别说明。

发现 `submit_job` 可能把“Future 已正常返回、但内容是 Timeout 本地回退”当作成功缓存；`ui/health_explanation.py` 现允许同键的显式再次请求重新计算失败/降级结果，成功结果仍合并复用。没有自动增加模型请求，授权仍在真正发送前复核。

`question_sources(..., include_evidence=True)` 可为报告保存本次完整已选原文、定位、引用版本、直接/依赖主张审核；默认页面只取轻量显示内容。旧快照不重写；当前撤销影响下一次解释。

## 验证证据

- 独立新增测试与健康事实/生命周期/授权：`python -m pytest tests/knowledge/test_repair_question_evidence.py tests/knowledge/test_health_fact_bindings.py tests/knowledge/test_health_explanation_lifecycle.py tests/knowledge/test_async_explanation_consent.py -q --junitxml=artifacts/repair_knowledge/targeted-tests.xml`：45 passed。
- 所涉文件 Ruff 检查通过；完整知识测试 267 passed（61.64 秒），结果见 [knowledge-suite.xml](../artifacts/repair_knowledge/knowledge-suite.xml)，全仓最终受验身份以总交付记录为准。
- 真实应用浏览器命令：`PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu .venv/bin/python tools/repair_rag_browser.py --knowledge /tmp/healthzip-repair-knowledge-20261127`。
- [真实点击回执](../artifacts/repair_knowledge/browser/browser.json)：从身体页面选择血氧，打开依据、点击查询、核对新增行动及 FDA 原文链接、展开人群与范围；320/375/390/430/768/1440 无主页面横向溢出。浏览器网络仅允许本地页面；0 外部模型请求，0 页面错误。截图 [390](../artifacts/repair_knowledge/browser/oxygen-action-390.png)、[1440](../artifacts/repair_knowledge/browser/oxygen-action-1440.png) 已目视核对。

## 保留的未完成项

特定 Apple 型号/算法/测量协议的腕温、呼吸率、血氧、呼吸紊乱、设备事件纵向验证及许可明确的逐主张接入仍不足；仅有方法资料不会填满这些缺口。其余未逐项复核的六问明确标“尚待核验”，没有用拒答率或主张数量当充分性。

没有实体 iPhone/Safari/软键盘验收、独立专家审定、人体外部效度或目标私人远程模型质量结论。旧资料许可缺口、旧目标漏召回和已有历史失败结果均保留。报告和页面整体性能另由本轮固定规模验收记录；本节不以补检索命中数量冒充端到端性能或科学有效性。
