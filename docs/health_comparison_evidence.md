# 心率、SDNN 与睡眠：本次资料和 RAG 交付

本次在已有 SourceLibrary、TheoryLibrary、MetricResult、逐主张审核和混合检索上增量实施。真实公共知识库位于 `.local/knowledge`，健康输入始终来自独立本地事实层。没有把私人健康记录写入公开知识库，没有调用外部健康解释模型，没有全量重建向量。审阅为实现者 AI 辅助原文审阅，不是独立专家验证。

## 六阶段核对与资料结果

完整逐来源结果见 [19 项来源清单](../artifacts/health_comparison/source-inventory.json)，分别记录登记、全文收据、解析版本、主张审阅、指标绑定和本次实际检索使用。原文、审核包和 SQLite 备份保留 `.local/health-comparison-review` 及既有 `.local/knowledge/blobs`，未加入提交。

| 来源 | 获取和读取 | 本次审核/绑定 | 当前页面使用核对 |
| --- | --- | --- | --- |
| Quer 2020，10.1371/journal.pone.0227709 | 复用原有完整 JATS，未重下 | 新增个人参考和 Fitbit 日 RHR 算法边界主张，绑定 STATE-RHR | 真实本地检索及浏览器均返回一般测量说明及原文 |
| E7，10.1038/s41746-025-02238-1 | 复用已有完整 JATS 与现有方法审核；来源实际出版年保留 2026 | 原 Apple Watch 测量不确定性/睡眠边界继续使用，未升级为每日 RHR 算法验证 | 进入原检索与当前用途检查；不宣称校准个人误差 |
| R3b，10.3390/jfmk9020093 | 复用全文，重读方法和测量条件段落 | 新增 SDNN/RMSSD 区分及记录条件说明 | 真实 SDNN 检索及浏览器页面均返回 |
| R4，10.1007/s40279-022-01706-y | 复用全文，核对睡眠损失定义及研究协议 | 当前没有已验证 SourceClaim 或直接指标绑定，本次未新增；没有把研究筛选时长/组均效应转成用户阈值 | 未作为本次页面解释依据；全文存在不等于已获使用权限 |
| R2b | 已有完整 JATS；当前没有已验证 SourceClaim 或直接指标绑定 | 未为特定老年女性干预研究新增通用 HRV 解释权限 | 未作为本次页面解释依据 |
| NIH 睡眠 | 复用完整原文及原有睡眠主张/指标绑定 | 原许可和用途限制保留 | 实际检索可供原睡眠证据组使用；本次单独页面命中未验证 |
| M1 可靠性 | 只有已取得的元数据和摘要，没有全文 | 无已验证 SourceClaim/直接指标绑定；本次未追加获取 | 未作为本次页面解释依据 |
| M2 等效方法 | 已有全文和 8 项方法主张，没有直接指标绑定 | 保留既有独立方法用途，不授予新个人等效结论 | 不把实验等效界值当通用个人规则 |
| Apple 2024 心率白皮书 | 完整 PDF 已取，读取 p.12–13 | 保存逐用途阅读记录；未授予模型/公开索引使用 | 未入本次页面检索；官方 URL 保留于资料清单，下载不等于索引许可 |
| HealthKit restingHeartRate / SDNN 文档 | 取得官方 DocC JSON，原身份查重后分别复用 APPLE_RHR、R3a | 核实 RHR 区别于静坐普通 HR、当日/前日替换；SDNN 指标与单位 | 未入本次页面检索；官方原文保留，许可未自动升级 |
| Carter 2026，10.1152/ajpheart.00041.2026 | 完整 JATS，91 单元；读取 Recording Conditions、Table 2、Question 10 | 新增测量条件与用途有效性边界主张 | 已绑定 STATE-SDNN；真实浏览器与 R3b 一同命中，其他请求仍受既有 6 段预算约束 |
| Apple 2025 睡眠白皮书 | 完整 PDF，读取 p.3–4、9–11 | 核实 Core/Deep/REM、短事件输出、2024/2025 版本变化，保存阅读记录 | 未入本次页面检索；许可待核，不将分期变化自动视为质量改善 |
| Robbins 2024，10.3390/s24206532 | 完整 CC BY JATS，50 单元；方法/缺失/局限原文已读 | 新增时长/分期/覆盖边界，绑定 STATE-SLEEP-24H | 真实睡眠检索返回 |
| Plews 2014，10.1123/ijspp.2013-0455 | 官方摘要已取并读；既有合法流程未找到可用全文路线 | 摘要级，未批准全文主张 | 不将 lnRMSSD 研究的每周观察频率转成 Apple SDNN 规则 |
| Davis-Wilson 2025，10.2196/53645 | 完整 CC BY JATS，62 单元；修复 XML 注释解析错误后取得 | 新增 Garmin IBI 窗内缺口与整日缺失的区别，绑定 STATE-SDNN | 已进入增量索引/审核；选择仍受预算约束 |
| Bellenger 2016，10.1123/ijspp.2015-0495 | 官方摘要已读；全文未取得 | 正确题名是 *Contextualizing Parasympathetic Hyperactivity in Functionally Overreached Athletes With Perceptions of Training Tolerance*；最初误配的综述题名已按 DOI/官方元数据更正并留事件 | 摘要级，不假称全文验证，不把站立 RMSSD 结果套给 Apple SDNN |
| Alavi，10.1038/s41591-021-01593-2 | 完整 CC BY JATS，方法与讨论原文已读 | 新增夜间无步数 HR 聚合与 Apple 日 RHR 的区别；不采用报警算法 | 已绑定 RHR，保留研究人群和多情境边界 |
| AASM/SRS 成人共识，10.5664/jcsm.4758 | 取得并阅读完整 PMC HTML；OAI 权限不明、Europe PMC 失败均留回执 | 核实建议的人群为 18–60 岁，许可仍待复核，未开放个体数值建议 | 未知年龄/未成年人/范围外年龄不会默认套成人规则 |

[获取初次回执](../artifacts/health_comparison/source-acquisition.json)、[重试回执](../artifacts/health_comparison/source-acquisition-retry.json)、[Davis 修复收据](../artifacts/health_comparison/davis-repair.json)、[阅读范围与数值语义](../artifacts/health_comparison/reading-status.json) 保留失败和恢复过程。初次 Apple PDF 解析使用的系统 Python 缺 `pdfplumber`，随后用仓库 `.venv` 已成功解析；不是最终仍缺全文。Plews/Bellenger 的全文和 Apple/AASM 的索引许可缺口仍真实存在；复核既有 M1 时也确认其仍无全文，本次未新增获取或权限。

新增 [5 项审核](../artifacts/health_comparison/reviewed-bindings.json) 与 [Davis 审核](../artifacts/health_comparison/reviewed-davis-binding.json) 共 6 项窄范围主张。每项均有不可变来源版本、原文单元哈希、定位、人群、设备、指标、测量条件、比较、缺失处理、用途和不能推断的内容。它们只允许一般测量与比较说明，不批准诊断、个体因果或数值处方。新增冻结发布 [`health-comparison-reviewed-20261122`](../artifacts/health_comparison/knowledge-release.json)，旧冻结发布和原有版本/原文/主张/规则/关系行逐行保持原值；清单提供检查数量和零差异结果。

## 实际 RAG 改造

`knowledge.health_facts` 将现有 `MetricResult.comparison` 投影到可复核事实卡，不重新计算。每个值/差值绑定不可混用的 `fact_id`、单位、统计身份、完成日窗口、实际日期与覆盖。当前未结束日期不会被写成已完成的比较范围。原始记录 ID 保留本地，网络投影移除原始来源 ID。

`product.explain_metric` 新增 `deterministic_observations`、`measurement_explanations`、`local_next_steps`。测量说明必须来自已通过原权限/适用性/完整证据组检查的主张，并且主张明确审核 `explanation_purpose=measurement_context`；它不是绕过人群或协议门禁的新个体推断通道。旧严格 `source_explanation` 权限仍按原 profile 决定。撤销、冲突、旧发布缺少新成员时都不能显示这些新说明。

新比较的公共检索只增加有限的通用方法需求，例如缺日、不同协议、SDNN/RMSSD 区别；不包含私人值、日期、设备名称和自由文字。已冻结查询保持原表达。原混合检索、排序预算、证据组选择和范围检查继续使用。

`workflows.local_context` 保留实际观察日期、事实 ID、已知测量条件和明确年龄；未知保持未知。`context:{...}` 这样的产品分组身份不冒充真实协议，`真实协议;context:...` 只取已记录的真实协议部分。

AI 核验在原逐卡精确语义限制上增加事实 ID 的整体绑定，拒绝从另一个时段借值、改单位/方向/覆盖、把已记录日期说成缺失。未经验证的自由生成文本不能覆盖程序事实。`reason_code` 明确区分 `network_disabled`、`not_configured`、`TimeoutError`、`validation_failed`；无适用证据仍是独立检索状态。模型温度未修改。失败使用原本地回退，正确观察、记录建议和引用可以独立显示。

## 检索缓存与验证

页面和工作流的本地 lexical 检索新增 64 项、300 秒有界缓存，依赖知识根/数据库身份、真实来源与审阅修订、固定发布、指标/任务、声明适用条件、方法需求、查询/profile/算法版本、模式与预算。仅缓存公共证据，个人窗口/数值不进入缓存内容。改变日期但方法和适用条件相同可复用；知识撤销立即失效。缓存命中仍产生新的审计身份，返回和写入前复核依赖；未提交事务不使用缓存。远程 hybrid 路径保持原版本化向量缓存和权限先行流程，没有为缓存提前调用模型。

[真实公共库检索检查](../artifacts/health_comparison/public-retrieval-check.json) 显示 RHR、SDNN、睡眠均能返回适用的一般测量说明；未知人群/协议仍不获得个体解释权限。另已通过[真实 Chromium 页面](../artifacts/health_changes/final-browser/browser-results.json)：使用合成健康数据与实际公共知识备份，RHR 展示 Quer、SDNN 展示 Carter/R3b。睡眠来源本轮已核对实际检索，不能把它写成单独验证过的浏览器来源交互。

[独立合成 RAG 验收](../artifacts/health_comparison/rag-acceptance.json) 用附件示例之外的 9 月数据，在真实公共库运行：

- 事实/数值/方向/日期/覆盖检查 6/6，通过项内错误数 0；6 类恶意数值/单位/日期/覆盖/ID 变更全部被拒绝。
- 正确绑定回答被接受；具体观察、适用测量说明、下一步、原文入口、未知年龄边界 5/5。
- 30 次热缓存本地完整解释中位 19.50 ms、P95 20.34 ms；冷访问 1.235 s。这个测量不包含浏览器渲染，也不包含远程模型；页面计时见主交付报告。
- 外部模型调用 0，真实模型回答的准确率/超时耗时仍未验证，不能用上述结果宣称模型效果。

可重放：

```bash
PYTHONPATH=src .venv/bin/python tools/health_comparison_rag_acceptance.py
.venv/bin/pytest -q tests/knowledge tests/unit/test_ai_client.py tests/unit/test_knowledge.py tests/unit/test_v14_knowledge.py
```

本次知识/AI 相关回归 **380 通过，101.58 秒**（[JUnit](../artifacts/health_comparison/knowledge-tests.xml)）；另对最后协议传递修复的专项 **43 通过，50.02 秒**。两组有重叠，不相加。它们验证软件边界，不能替代真实页面、独立科学审阅或远程模型效果验证。
