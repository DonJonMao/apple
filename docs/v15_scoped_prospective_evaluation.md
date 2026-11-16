# 评测范围冻结与新增来源前瞻任务

本轮修正离线评测工具与页面默认范围之间的差异。`metric-hybrid-1.5.6` 的生产计算、77项领域配置、私人数据库和既有审核不变；评测工具新增显式 `candidate_scope`，允许在同一Gold、来源发布、模型和预算下比较 `all` 与页面使用的 `reviewed_metric`。旧Gold和历史成绩保留。

## 范围与身份

API及评测CLI省略参数时仍使用 `all`。选用 `reviewed_metric` 时，Gold冻结回执必须预先声明允许的范围和 `reviewed-metric-candidates-1.5.0`，索引发布也必须固定这一语义版本。没有范围字段的旧Gold只允许原 `all`；不能因本轮只有确定性指标、空候选或无网络请求而跳过评测身份核对。

```json
{
  "candidate_scopes": ["all", "reviewed_metric"],
  "candidate_scope_version": "reviewed-metric-candidates-1.5.0"
}
```

每种范围中的A–E及同适用性词项参考 `A_filtered` 使用同一范围；三种固定表达也转发同一选择。范围和Gold冻结文件哈希写入运行身份，恢复运行时更换范围或冻结内容会被拒绝。成对报告核对来源发布及范围身份，不把不同资料或权限下的运行拼在一起。

`reviewed_metric` 预先使用既有审核绑定，因此其结果只衡量已审核指标依据中的排序与聚合，不能当成整个语料库的发现能力。两种范围是显式实验因素；同范围的词项与混合方法才构成相应的公平比较。

公开报告只保存脱敏的服务身份、模型版本及服务身份哈希；端点、分词端点、密钥和请求头不进入新公开运行身份。原始服务身份仍只在本地，用于缓存和恢复核验，没有改变缓存键或重写历史工件。脱敏保留私有运行身份的哈希，使不同服务位置不会变成同一实验身份。

## 新来源与标注边界

新取得 Quer G、Gouda P、Galarnyk M、Topol EJ、Steinhubl SR（2020）的完整JATS主文：*Inter- and intraindividual variability in daily resting heart rate and its associations with age, sex, sleep, BMI, and time of year: Retrospective, longitudinal cohort study of 92,457 adults*，[论文 DOI](https://doi.org/10.1371/journal.pone.0227709)，PMC7001906，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。Crossref、PubMed及JATS身份相符；此次未取得PDF、补充材料或参与者数据。来源回执见 `quer-rhr-prospective-acquisition-1.json`，不修改原13文件/12科学PDF清单。

按DOI、PMC编号和标题短语检查来源登记、当前受跟踪资料/评测及Git历史，未找到已有该家族的记录。检查范围及文件清单哈希见 `prospective-rhr-exposure-audit-1.json`。这不证明外部模型的训练语料未包含论文，也不能排除只以未登记别名出现的材料。

一个已知指标 `STATE-RHR` 对应一个新增来源任务：查找日静息心率的方法及必要限制，并核对Fitbit专有日值能否直接提供Apple Health协议和恢复解释。来源由实现者AI选择，但标注池包含主文全部41个单元，未按检索名次或正确片段筛选。任务、完整原文哈希/定位、三表达、范围及六项答案语义标准先记录于 `prospective-rhr-task-plan-1.json`。

同一 `deepseek-v4-flash` 服务在没有排名及生产绑定标签的条件下标注全部41单元，给出11个直接方法或必要限制单元，并判定没有充分的Apple协议及恢复依据。Gold-4及其冻结回执在本任务首次排名前建立。它是新增来源的有限前瞻任务；指标和查询表达已在开发中使用，标注与精排同模型，实现者选来源、无专家，不能称为全新的指标留出或完整独立验收。

11个Gold单元下，K=6的精确片段Recall理论上最多为6/11，即54.55%。其他来源未穷尽标注，报告中的Precision只是该来源Gold命中比例；不能把其他合法来源一律认定为科学错误。没有从自动标注生成主张，Claim Coverage的分母为0、结果为null。

新41单元只登记为provisional，增量生成41项文档向量，当前文档缓存44975项；索引不赋予科学审核、来源解释或数值候选权限。来源中Fitbit专有公式、纳入标准、插值、异常事件定义和组间关联均未成为产品协议或个人阈值。

## 复现

原文、向量、合成完整结果、模型原始答复和服务配置保留在本地；公开工件只提供身份、定位、哈希、评分及边界。拥有同一本地快照和服务身份时，每种范围使用独立输出目录运行：

```bash
.venv/bin/python tools/v15_run_retrieval_benchmark.py \
  --root .local/v15/scope-benchmark-1/snapshot \
  --gold artifacts/v15/retrieval/benchmark-gold-4.json \
  --services-config .local/knowledge/model-services.json \
  --release-id v15-prospective-rhr-source-4 \
  --private-output .local/v15/scope-benchmark-1/reproduction/reviewed_metric \
  --public-output .local/v15/scope-benchmark-1/reproduction-public/reviewed_metric \
  --evaluation-purpose independent_test \
  --candidate-scope reviewed_metric \
  --query-forms zh en zh_synonym
```

切换为 `all` 并更换两个输出目录即可形成同Gold对照。`independent_test` 是用途字段；真实独立性以本报告和冻结来源记录为准。已发布结果目录不可覆盖。

WP-F的五领域整体改善、跨领域答案充分性、复杂表格/公式和严格独立专业验收仍开放；本轮不据单篇论文或软件通过宣称整体完成。

## 本轮全部资料范围结果

以下是同一个新来源任务的精确片段Recall@6；每格任务分母都是1，Gold分母11，不构成人群准确率或独立语言题数。

|方法|中文|英文|中文同义|
|---|---:|---:|---:|
|A 词项，适用性消融|0/11|0/11|0/11|
|B Dense，适用性消融|3/11|3/11|3/11|
|C 词项+Dense RRF，适用性消融|0/11|0/11|3/11|
|D 加聊天精排，适用性消融|0/11|1/11|3/11|
|E 完整生产流程|0/11|1/11|3/11|
|A_filtered 同过滤词项|0/11|0/11|0/11|

中文同义表达保留了Dense的召回，英文精排从融合的0/11提高至1/11；中文及英文完整流程仍低于Dense的3/11。不能据此宣称混合流程整体优于Dense；相对同过滤词项的有限改善也没有建立五领域整体优势。此题现已暴露，后续如果用于改进只能计为开发材料，不能重算独立分母。

`all` 每次有22639个当前合格领域候选；返回的其他来源片段没有穷尽相关性标签。完整流程三表达均保留一个既有有限不确定性主张，但协议/恢复缺口不消失。每次仍为 `insufficient_evidence`，未授来源解释或数值候选权限；新来源只被找到，不因排名升权。

页面默认的 `reviewed_metric` 范围每次只保留既有完整绑定中的两段E7依据；新来源尚无审核绑定，全部方法/表达对新来源的Recall均为0/11。这个零命中既显示新来源尚不能参与指标解释，也符合该范围的权限边界，不能记作发现能力成功。

两范围×三表达×六方法共36次真实检索入口调用，全部未降级，并均保持本题预期的证据不足状态。实际发生3次查询Embedding请求和28次精排窗口请求，全部完成；请求哈希及合成私人标记检查保留于 `prospective-rhr-scope-comparison-1.json`。同题的36次状态一致不能变成36道独立拒绝题。先运行all再运行reviewed_metric，后者复用查询向量；耗时只报告逐次观测，不作为P95、纯范围因果比较或用户设备性能结论。

Recall、Precision、MRR、nDCG、精确Source/Span命中及领域分层记录在 `prospective-rhr-run-1/`。本题只涉及wearable/recovery及其交集，不能填补strength/physiology/cardiometabolic的独立评测分母。领域路由1/1只是固定配置一致性；Claim Coverage和Conflict Recall为null。五个本篇被标注为不适用的单元没有入选，但未穷尽语料的适用性；本题没有新的无效许可反例，报告中的0错误不能作为全面权利准确率。

## 软件与历史保护

整仓1600项测试通过（499.40秒），Ruff通过，289份输入全程及最终核验一致。最初新增定点夹具漏掉显式协议和合成环境，出现1失败/13通过；只补齐该夹具设置后14项通过，没有放松生产审核或修改原测试期望。系统Python缺Ruff的调用随后使用仓库虚拟环境完成。

28张知识表的原有行、689份此前已提交工件及原77项配置保持原哈希。新增来源和向量采用追加方式；两个知识库及原文/向量有本地备份，私人健康库未打开，旧Gold和冻结副本未回写。完整回执见 `regression-scoped-benchmark-1.json` 及 `prospective-rhr-final-integrity-1.json`。

## 实际最终答复的有限语义核对

通过真正的 `explain_metric` 入口，向两种范围各传入同一份已经计算的非空合成日心率结果，英文固定查询、完整混合检索及本地解释。两次均无降级，保持 `insufficient_evidence`，来源解释及candidate权限均为false；返回文本明确保留“知识证据不足，当前只解释确定性计算结果”。两次文本/限制/状态/权限投影相同，只对一个唯一答复提交一次语义评审，不能计成两个独立答案。

同一deepseek服务在看不到检索排名或范围标签的条件下，读取冻结的六项标准、实际最终答复、预先计算的合成MetricResult和新文章全部正文单元。六项均判pass，未指出过度推断；这仍是同模型AI核对，无专家，只覆盖一个证据不足任务，没有证明充分证据下的正面答案质量。评审前已冻结标准，没有按答复改写判据。

两次产品检索共6次精排窗口请求，均未包含合成私人标记或数值；个人解释联网仍关闭。单独的语义评审明确使用完全合成的结果/答复及公共论文，不包含真实健康数据。原始答复与评审请求仅本地，公开回执只保留六项判定、身份及哈希，见 `prospective-rhr-product-answer-1.json`。
