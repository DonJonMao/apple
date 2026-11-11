# Knowledge review of 912aefc

固定提交：`912aefc93b9bd9c1cebf297a10728c69c827e266`。仅阅读源码、规范、已提交工件；未联网、未更改仓库源码或原有数据。所有新脚本与结果位于本目录。先读了 AGENTS/CODEX_GOAL/DESIGN_SPEC/V1_3_GOAL。运行了单文件定向回归及独立合成反例，没有运行整套 pytest。

复现：在仓库目录执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python /workspace/scratch/a74a838d7f65/review912/knowledge/reproduce.py`。输出见 `results.json`。定向回归输出见 `targeted_regressions.txt`、`targeted_regressions.xml`。这些都是软件行为测试，不是运动效果验证。

## 原问题与报告状态

| 检查 | 结果 |
|---|---|
| R05 撤销 | 通过：原 review 内容保留；改 needs_review 后，当前查询及指定旧 release 均不再返回该卡。 |
| R05 修订取代 | 通过：新修订批准后仅返回 0.2.0，旧版有 superseded 事件。 |
| R06 原组件许可反例 | 通过：原 fixture 的 article/main/closed-table 不可索引，获许可 child 可索引；但嵌套文本仍有下述 K02。 |
| R15 普通抓取洗掉更正 | 通过：metadata/abstract/fulltext 成功入库均不清除 scientific_state；但同一更正重复拉取有下述 K03。 |
| 有引用但答非所问 | 原冒充支持问题已修：无已审目标绑定时返回 related_material_only、0 claims、0 citations，保留相关阅读。尚未实现自由问法的可靠语义作答；不应把诚实拒答本身写成算法造假。 |
| 0 approved / 14 fulltext | 已提交工件一致：09:15 重解析时为 11 approved；09:20 显式生命周期迁移后为 11 needs_review + 9 draft，即有效批准 0。16 次重解析覆盖 14 个不同来源，S5/S7 各有多个版本。32 fulltext versions 不是 32 篇论文。 |
| AI 7/10 | 用当前评分器重算冻结包，结果为 independent_ai_reviewed=10、pass=7、invalid_annotations=0、human=0，release_gate=failed_independent_review。NEW-02/05 未对具体问题解释否定理由，NEW-06 把直接支持误标 qualifies；报告如实保留三项失败。 |

以上真实材料计数来自提交工件，不声称读取了开发者本地数据库。来源版本、可检索段落与已审理论是不同计数。0 approved 及未做人群干预验证本身不列为 bug。

## 剩余明确问题（3 项）

### K01 — P1：检索预算会把已存在的同目标反证裁掉，改变结论

位置：`src/healthzip/knowledge/retrieval.py:115` 在判断支持关系前进行 `[:k]`；`:160` 仅把截断候选交给 `assess_support`。`src/healthzip/knowledge/support.py:56` 仅扫描这些候选，`:67` 只在其中同时出现 supports/refutes 时承认冲突。

复现：创建七张可用、已审合成卡，七张绑定同一问题、同一 target proposition 与 scope；前六张 supports，第七张 refutes。不改变任何证据，仅改预算：默认 `k=6` 返回 `evidence_supported` 和肯定结论；`k=7` 返回 `conflicting_evidence`。两个卡的 `k=1/2` 对照也重现。证据见 `results.json.remaining_K01`。

期望：显示条数或词面排名不能决定同一个目标是否“没有反证”。支持判定前应对已解析的目标和范围查全当前适用的已审关系（可使用独立目标关系索引）；top-k 仅控制展示/相关阅读。不能查全时应明确 conflict screen incomplete，不能声明完整证据支持。

修复验收：正例为单支持关系正常支持；反例为第 k+1 条存在反对关系时，k=1、6、7 均报告冲突或显式不完整；同范围 qualifies 不应被误当反对；不同人群/时间范围的反对不应制造假冲突。撤销或 supersede 的旧反证不得继续参与。

### K02 — P1：允许索引的父段落夹带受限子组件全文

位置：`src/healthzip/knowledge/acquisition.py:92` 对整段调用递归 `_text(node)`；`:117` 只按该段根节点赋权。`src/healthzip/knowledge/rights.py:21` 的 owner 只看节点及祖先，`:119` 返回单一 owner 的权限。因此一个 paragraph 含有嵌套 fig 时，子 fig 许可并不约束父 span 已抽取的子文本。

复现：article 为 CC BY，body/p 内嵌 fig；fig 明确 All rights reserved/Permission required，caption 包含 `RESTRICTED_FIGURE_MARKER`。独立 caption span 的 `index_allowed=false`，但 `/article/body/p` 把 marker 与版权说明整体递归抽出，按 article 权限得到 `eligible=true`。证据见 `results.json.remaining_K02`。这证明原 R06 扩权问题的另一条数据路径仍存在，并不声称实际十四篇材料均含该结构。

期望：每个可索引 span 的全部文本、结构化单元及 raw_xml 都受其对应组件许可覆盖。跨权限作用域须分割文本并保持定位，或让混合 span 待审；不能仅阻止子 span 而允许父 span 包含相同受限内容。

修复验收：正例为全篇及组件均许可时保留完整文本与定位；反例为 allowed p → restricted fig/table/supplement 时，受限标记在所有 eligible text/structured/raw_xml 中均不存在。反向“受限父 + 单独许可子”应仅放行子内容。授权范围不明时不得默认为父段可用。

### K03 — P2：重复收到同一更正通知会使已完成的版本复核永久反复失效

位置：`src/healthzip/knowledge/store.py:240` 每次非 acquired 更新无条件 `scientific_epoch + 1`；`:242` 随后把关联 approved 卡置 needs_review。`src/healthzip/knowledge/acquisition.py:240` 每次 PubMed 元数据含 ErratumIn 都调用该更新；Crossref 同类路径在 `:200`。

复现：离线 mock PubMed request，只返回同一字节串、同一更正 PMID 和同一 metadata version。第一次更正后对精确全文版本复核，创建并批准理论新修订；此时 epoch=1、eligible=true、回答 evidence_supported。再抓同一响应后 epoch=2、eligible=false(corrected_pending_review)、回答 insufficient_evidence。证据见 `results.json.remaining_K03`。

期望：notice identity/content 未变时应幂等更新 checked_at/抓取日志，保留该 notice 下的精确版本 clearance；新增或实质更改的更正才开启新 epoch。不得靠关闭更正检查修复，也不能自动恢复被撤回的来源。

修复验收：正例为同 PMID/关系/通知内容重抓不增加 epoch，不改变已审卡；反例为新更正 ID、既有更正内容更新或撤稿会使旧 clearance 失效。跨提供方同通知去重规则应保留来源与解析版本，避免用 fetched_at 充当科学变更。

## 教材与国家指南骨干迁移：对当前实现的具体建议

清单共 43 项：29 项期刊学术来源，其中 2 项为 ACSM position stand（S1/S2），其余 27 项为研究论文/综述/统计方法；另有 5 项 Apple 字段文档、8 项采集接口文档、1 项训记产品文档。没有 ACSM/NSCA 教材、NSCA 指导或美中政府运动指导条目。ACSM/NSCA 属专业协会，不是美国政府；Apple/PMC 的“官方”只是技术出处，不能充当运动建议依据。

现有 `sources.sqlite3` 与 `theories.sqlite3` 分离方向正确，无需另起一套重复库。建议按下列层次扩充内容和准入，而非要求每条普通建议都找一篇单独实验论文：

| 内容层次 | 当前承载与需增加字段 | 准入及功能边界 |
|---|---|---|
| 权威教材/学会指南/政府指导骨干 | `source.manifest_json` 增 `source_kind`、`authority_body`、`authority_kind=professional_association/government/publisher`、`jurisdiction`、`edition`、`isbn` 或正式文件号、`publication_date/effective_date/replaces`、目标人群与主题。 | ACSM/NSCA 教材和学会共识、美国 HHS 及中国有关主管部门的运动指导均可作为候选骨干；具体版本、发布主体、权限在下一轮核验。政府普通人群活动建议与力量训练专门教材各有适用范围，不只按权威排名覆盖一切问题。 |
| 稳定知识定位 | 延用 `version.sha256/parser_version/receipt_json` 与 `span.locator_json`；教材添加章、节、印刷页码、电子页码、图表/条款号及版本。`identity()` 当前只识别 DOI/PMID/PMCID/URL（store.py:85），宜增加 ISBN+edition+language 或政府文件号+版本的稳定身份。 | 有合法副本和明确适用的许可才索引；教材可经 `import_document` 读取用户合法提供的 PDF，但访问文件不等于复制/传播许可。文字章节与表格必须分别定位、保留单位/脚注。 |
| Theory 的共识主张 | 延用 `card_json.claim_type/domains/source_ids`，审阅写入 `review_json.claims/evidence_links/applicability/authority`；增加 `claim_basis=textbook_definition/consensus_guideline/research_finding/product_operationalization`、推荐强度/证据确定性（仅原文件实际提供时）、适用人群、训练经验、目标、禁用/需转介条件。 | 普通动作分类、训练变量定义、一般训练建议可以来自稳定教材/指南。论文补充测量误差、设备效度、最新争议与个体模型。动作/UX、平台字段、API 文档限定角色，不推导生理效应。 |
| 从知识到候选 | 保留目标、器械档位、数据可比性及明确科学条件；把共识原则、用户自选计划和实现规则分别注明来源。 | 指南原则不等于唯一最佳公斤数；器械下一档是可执行选项，不是疗效保证。先做规则含义、单位、适用域和实现一致性测试，再以真实记录评估使用表现；普通可选建议不必等待个人临床试验。 |

`store.review():316–318` 与 `workbench.reviewed_principles():144–147` 当前将候选能力绑定到字符串 `qualified_human_review`。这是项目采用的产品授权策略，不是运动科学要求“所有普通建议先做临床验证”的定律。应将来源权威性、内容核对状态、审阅者身份、实现测试和输出能力分别记录，给经过核验的教材/指南建立明确的普通共识建议路径；研究性个体效果预测/因果宣称另设验证标准。若决定调整该策略，要显式修订策略与测试，不能让 AI 填写虚假的 qualified_human 或伪造 review，也不应把普通自选训练建议与临床干预效果证实混为一谈。

迁移验收至少覆盖：教材各版身份不误合并、指南更新可追溯且旧版不是自动撤稿、原文许可按组件生效、每条候选可定位到条款与其适用条件、政府/学会/论文/技术文档角色能区分、论文结论与骨干建议冲突时保留明确范围及理由、未核实状态如实显示。
