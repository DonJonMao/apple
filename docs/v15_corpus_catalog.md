# v1.5 教材接入目录（开发中）

最新增量把已在v1.4取得的S5、R5两个JATS版本注册到v1.5（70+80个单元）；没有新来源身份或新下载。文件级归属保持provisional，仅逐段审核项追加content_checked。实际新增149项文档向量，当前缓存44934；原44785、44736和44403分别保留各自时点/冻结身份。最新静态矩阵为 `artifacts/v15/knowledge/evidence-coverage-matrix-3.json`：原77项中24项无需RAG、33项有绑定、26项类型/领域静态齐备，均不是准确率或科学有效性。详见 [方法依据及权限](v15_method_evidence_and_rights.md)。

后续另外取得 Li 等的 [2023 年 Apple Women's Health Study 论文](https://doi.org/10.1038/s41746-023-00848-1)（PMID 37248288、PMCID PMC10226714）。这是独立于下文13份用户文件的新研究来源，不回写原PDF清单的数量。实际取得的是PMC JATS主文，50个原文Span；没有取得PDF、补充材料正文或2022年AWHS方法论文。

Crossref、PubMed及正文身份均匹配，实际嵌入许可为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，第三方组件仍逐范围核验；本次查询未发现更正标记不代表保证永无更正。登记50个结构单元，生成49项不同内容向量、复用1项，失败0；当前本地文档向量缓存44785项，不能与原冻结评测副本的数量混用。文件级physiology/wearable标签仍为provisional；仅6个完整原文段落追加AI辅助内容和应用核对，用于来源记录含义和漏记限制，不批准论文中的周期识别算法、阈值或个体推断。详见 [获取、定位、权利及旧行保护回执](../artifacts/v15/sources/cycle-source-acquisition-review-1.json) 和 [逐主张审核回执](../artifacts/v15/knowledge/reviewed-cycle-bindings-1.json)。

可访问目录实际为仓库下 `资料/`；不是系统根 `/资料/`。13 个 PDF 包含 12 份来源和 1 份 ChatGPT 推荐清单。逐文件 SHA256、字节数、版本、官方定位、领域及许可见 `artifacts/v15/sources/source_manifest.json`。原始文件、正文、解析缓存、向量和密钥都在忽略目录中，不能随代码发布。

|实际资料|版次/年份|本轮使用范围|
|---|---|---|
|FDA Digital Health Technologies guidance|2023 final|联邦作者正文；第三方组件另审|
|WHO activity and sedentary guidelines|2020|CC BY-NC-SA 3.0 IGO，本地非商业|
|WHO wearable measurement meeting report|2025|CC BY-NC-SA 3.0 IGO，本地非商业|
|Army FM 7-22|2020，含 2025 Change 2|联邦作者正文；第三方组件另审|
|Army ATP 7-22.01|2020，含 2022 Change 2|联邦作者正文；第三方组件另审|
|OSU/Biga 等 Anatomy & Physiology 2e|2025 adaptation|CC BY-SA 4.0；不冒称 OpenStax/Rice 2022|
|WHO wearable population monitoring report|2026，会议 2025|CC BY-NC-SA 3.0 IGO，本地非商业|
|MacIntosh Open Textbook of Exercise Physiology|2025 Version 1.0|CC BY-NC 4.0，本地非商业；部分章节明确未写完|
|HHS Physical Activity Guidelines|2018 第 2 版|复用原 CORE-US-HHS-PAG-2 身份；政府正文|
|Lanphere The Physiology of Exercise|2025 第 3 版|CC BY-NC 4.0，本地非商业|
|NIH Your Guide to Healthy Sleep|2011 修订|历史睡眠背景；现行话题须另外核对|
|NIH Physical Activity and Your Heart|2006|历史一般背景；不默认优先于新指南|

WHO 2025 文件的 PDF metadata 错写 hearing aid services，身份以实际封面与版权页为准。FM 内页也出现不同的前言日期，保留冲突说明；不能仅看元数据或文件名合并版次。

官方 URL 是来源定位，不是本次原始文件的下载回执；缺少精确原始下载 URL 时明确为未核验，不伪造下载经历。此次没有替用户重新下载教材。政府正文身份、嵌入的 CC 许可及官方权利政策分别记录；不把免费阅读等同商业全文授权。

12 份来源已完成本地导入，共 4114 文件页。当前解析器为 `pdf-structure-1.5.1`，组件范围策略为 `document-component-scope-1.5.2`；生成 69183 个片段，其中 67509 个通过本地索引权限检查，另有 216 个表格单元。这些数量不代表解析准确率或科学审核通过。获取、解析和权利报告均已保存在 `artifacts/v15/sources/`，早期解析记录保留并明确 supersede。

本次全注册语料的预算内向量续建已完成：生成37523个不同内容向量，待补建0、失败0。文档向量缓存共44403项，覆盖新增资料和既有研究资料并按内容复用；它不是片段数量。1674个当前来源不符合准入、21个结构单元超过模型预算、1个空单元分别排除，旧解析另外按版本预筛。冻结评测语料有68728片段；评测副本的同模型文档向量与原库逐字节匹配，差异0。超预算单元仍可能使查询标记 `dense_index_incomplete`，没有把预算内完成冒称全部结构单元均有向量。见 `artifacts/v15/retrieval/full-index-run-3.json` 和 `benchmark-complete-vector-cache-2.json`。

后续同源分词能力实测区分了字节资源上限与模型token容量：上述21个单元中18个完整原文不超过4096 tokens，已增量补建，当前本地缓存44421项；不重新嵌入旧内容。3个表格分别为5407、5045、4456 tokens，仍不能完整输入该模型，继续保留原文并报告缺项。该补建未改原始片段、权利或审核，未改既有冻结评测副本。能力及真实请求的完整输入哈希/回执见 `artifacts/v15/retrieval/model-input-capacity-1.json` 和 `whole-unit-token-indexing-1.json`。

部分图片绕排的完整句子仍跨两个片段，复杂布局、印刷页码、无边框/多页表格、公式符号和图像文字仍需逐项核对。NIH 睡眠文件第10页的绕排句已绑定两个精确片段并核对原页图像；没有据此宣称全书布局完全正确。没有执行 OCR 或自动批准表格数字。

NIH 2006 心脏健康手册印刷页7确实使用静态热量换算及一年减重预测。该具体说法只保留为显式历史比较材料，与 Hall 动态能量平衡批评建立来源立场冲突；不把整份 NIH 资料误标为撤回，也不让这些旧数字进入普通个人解释。证据见 `artifacts/v15/knowledge/historical-static-dynamic-conflict-1.json`。

全书正文存在不代表每个主题都有内容。章节解析、来源权利、主张审核、数值应用和科学验证继续分别报告；后续逐片段审核不会回写导入时的零主张批准快照。
