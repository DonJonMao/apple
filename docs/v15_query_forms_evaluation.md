# 三种固定查询形式的前瞻任务实跑

2026-11-17。三种形式、8案例、6方法的144次检索入口调用全部完成，其中包括确定性跳过和权限拒绝，不能当作144次外部模型请求。当前实现为 `metric-hybrid-1.5.4`，本轮没有据结果调整RRF、候选预算、K、查询表达或Gold。正式混合检索质量验收仍未通过。

五个前瞻任务中，生产E的中文、英文、中文同义形式Recall@6分别为25%、25%、37.5%（各分母4）；同过滤词项分别为0%、25%、0%。中文两形式在这个有限资料池有召回改善，英文召回持平；中文和英文的纯dense召回均为37.5%，RRF反而漏掉部分证据，聊天精排没有增加召回或主张覆盖。三种形式的两个预期可解释任务均仍拒绝，不能仅凭部分排名改善宣布整体质量通过。

Gold-3中有5个此前Gold-2没有的指标任务，以及3个已知政策探针；同一8案例分别执行中文、英文、中文同义表达，形成24个相关查询实例，不是24个独立知识案例。只可称为前瞻排名盲测的有限任务集，新增独立来源家族为0。`independent_test`是运行用途标记，不能消除实现者选池、同模型标注/精排和历史来源家族重叠。

固定Gold SHA256为 `4e8ab9049171a87aef3932105041761a7a9fe4adacb777f9b4f02abef4ec4267`，查询登记为 `46043e74accffca96ed8c5fea574bb67a1e1fa1ed41c209e4ebabc9f2ed97702`。语料发布 `v15-query-forms-corpus-1` 的哈希为 `a01804d8afe1a5e3a68bf95ce8aae7e7ee7eeb07c97b53d9a0b32fccb5cdf9e7`；副本包含68728个Span、44736项文档向量，复制在新VO₂/周期审核之前。原历史留出、Gold-2及其冻结副本没有参与本轮调参。

Embedding为qwen3-embedding-8b（4096维），精排和盲标均为deepseek-v4-flash chat_listwise，服务权重版本未核验。K=6、RRF常数60、融合候选20、精排窗口24000 UTF-8字节，完整结构单元不截断。A–D仅消融语义适用性，权利/生命周期始终生效；E与A_filtered采用同一生产过滤及聚合合同。

## 五个前瞻指标任务

括号是对应指标的实际案例分母，数值为0–1。无Gold或无必需主张记null，不强填为成功。Precision以实际返回数为分母；无Gold且空输出的案例记1，不能把它解释为找到正确证据。

|形式|方法|Recall@6|Precision|MRR|nDCG@6|主张覆盖|拒绝判定一致率|
|---|---|---:|---:|---:|---:|---:|---:|
|zh|A|0.0000（4）|0.2000（5）|0.0000（4）|0.0000（4）|0.0000（3）|0.6000（5）|
|zh|B|0.3750（4）|0.1000（5）|0.3125（4）|0.3160（4）|0.4167（3）|0.6000（5）|
|zh|C|0.2500（4）|0.0667（5）|0.2500（4）|0.2500（4）|0.4167（3）|0.6000（5）|
|zh|D|0.2500（4）|0.0667（5）|0.2500（4）|0.2500（4）|0.4167（3）|0.6000（5）|
|zh|E|0.2500（4）|0.0667（5）|0.2500（4）|0.2500（4）|0.4167（3）|0.6000（5）|
|zh|A_filtered|0.0000（4）|0.2000（5）|0.0000（4）|0.0000（4）|0.0000（3）|0.6000（5）|
|en|A|0.2500（4）|0.0333（5）|0.2500（4）|0.2500（4）|0.1667（3）|0.6000（5）|
|en|B|0.3750（4）|0.0667（5）|0.5000（4）|0.4468（4）|0.3333（3）|0.6000（5）|
|en|C|0.2500（4）|0.0333（5）|0.2500（4）|0.2500（4）|0.2500（3）|0.6000（5）|
|en|D|0.2500（4）|0.0333（5）|0.2500（4）|0.2500（4）|0.2500（3）|0.6000（5）|
|en|E|0.2500（4）|0.0333（5）|0.2500（4）|0.2500（4）|0.2500（3）|0.6000（5）|
|en|A_filtered|0.2500（4）|0.0333（5）|0.2500（4）|0.2500（4）|0.1667（3）|0.6000（5）|
|zh_synonym|A|0.0000（4）|0.2000（5）|0.0000（4）|0.0000（4）|0.0000（3）|0.6000（5）|
|zh_synonym|B|0.3750（4）|0.0667（5）|0.5000（4）|0.4468（4）|0.2500（3）|0.6000（5）|
|zh_synonym|C|0.3750（4）|0.0667（5）|0.5000（4）|0.4468（4）|0.2500（3）|0.6000（5）|
|zh_synonym|D|0.3750（4）|0.0667（5）|0.5000（4）|0.4468（4）|0.2500（3）|0.6000（5）|
|zh_synonym|E|0.3750（4）|0.0667（5）|0.5000（4）|0.4468（4）|0.2500（3）|0.6000（5）|
|zh_synonym|A_filtered|0.0000（4）|0.2000（5）|0.0000（4）|0.0000（4）|0.0000（3）|0.6000（5）|

## 生产E按形式及领域

同一任务可涉及多个领域，领域行不能相加增加独立分母。仅投影上面的5个前瞻任务；包含政策探针的原矩阵和其他方法完整领域结果另保存在JSON。

|形式|领域|案例数|Recall@6|主张覆盖|
|---|---|---:|---:|---:|
|zh|cardiometabolic|1|0.0000（1）|0.2500（1）|
|zh|cross_domain|4|0.0000（3）|0.1250（2）|
|zh|physiology|2|0.0000（1）|0.2500（1）|
|zh|recovery|2|0.0000（2）|0.0000（1）|
|zh|strength|2|1.0000（1）|1.0000（1）|
|zh|wearable|3|0.0000（3）|0.1250（2）|
|en|cardiometabolic|1|0.0000（1）|0.2500（1）|
|en|cross_domain|4|0.3333（3）|0.3750（2）|
|en|physiology|2|0.0000（1）|0.2500（1）|
|en|recovery|2|0.5000（2）|0.5000（1）|
|en|strength|2|0.0000（1）|0.0000（1）|
|en|wearable|3|0.3333（3）|0.3750（2）|
|zh_synonym|cardiometabolic|1|0.5000（1）|0.2500（1）|
|zh_synonym|cross_domain|4|0.5000（3）|0.3750（2）|
|zh_synonym|physiology|2|0.5000（1）|0.2500（1）|
|zh_synonym|recovery|2|0.5000（2）|0.5000（1）|
|zh_synonym|strength|2|0.0000（1）|0.0000（1）|
|zh_synonym|wearable|3|0.5000（3）|0.3750（2）|

## 语言汇总和政策探针

语言汇总的中文包含中文原表达和同义表达，两次观察相关；英文仅一个形式。完整语言×方法×分层分母见结果JSON，不能用这类实例均值声明跨语言统计显著性。

|语言|方法|前瞻查询实例|Recall@6|主张覆盖|
|---|---|---:|---:|---:|
|en|E|5|0.2500（4）|0.2500（3）|
|zh|E|10|0.3125（8）|0.3333（6）|
|en|A_filtered|5|0.2500（4）|0.1667（3）|
|zh|A_filtered|10|0.0000（8）|0.0000（6）|

已知政策探针分别检验确定性算术跳过、跨用户拒绝和商业用途排除NC证据。商业案例Gold仍预期可由获准证据解释，因此其证据不足属于未达可答预期，不能与前两项一起宣称全部拒绝正确。已标注不适用/禁用片段准入、精确定位和路由分母在逐例JSON中保留；没有Gold冲突例时冲突召回为null/0，不称已通过冲突检出。路由得分只检查固定配置。

## 实际状态与失败

|形式|案例|命中Gold/总数|状态|Gold预期拒绝|
|---|---|---:|---|---|
|zh|new-active-energy|0/2|insufficient_evidence|否|
|zh|new-agonist-anatomy|0/0|insufficient_evidence|是|
|zh|new-load-comparison|2/2|insufficient_evidence|是|
|zh|new-resting-heart-rate|0/2|insufficient_evidence|是|
|zh|new-sleep-clock|0/1|insufficient_evidence|否|
|zh|known-policy-arithmetic|0/0|not_required_deterministic_computation|是|
|zh|known-policy-other-user|0/0|insufficient_evidence|是|
|zh|known-policy-commercial-energy|0/2|insufficient_evidence|否|
|en|new-active-energy|0/2|insufficient_evidence|否|
|en|new-agonist-anatomy|0/0|insufficient_evidence|是|
|en|new-load-comparison|0/2|insufficient_evidence|是|
|en|new-resting-heart-rate|0/2|insufficient_evidence|是|
|en|new-sleep-clock|1/1|insufficient_evidence|否|
|en|known-policy-arithmetic|0/0|not_required_deterministic_computation|是|
|en|known-policy-other-user|0/0|insufficient_evidence|是|
|en|known-policy-commercial-energy|0/2|insufficient_evidence|否|
|zh_synonym|new-active-energy|1/2|insufficient_evidence|否|
|zh_synonym|new-agonist-anatomy|0/0|insufficient_evidence|是|
|zh_synonym|new-load-comparison|0/2|insufficient_evidence|是|
|zh_synonym|new-resting-heart-rate|0/2|insufficient_evidence|是|
|zh_synonym|new-sleep-clock|1/1|insufficient_evidence|否|
|zh_synonym|known-policy-arithmetic|0/0|not_required_deterministic_computation|是|
|zh_synonym|known-policy-other-user|0/0|insufficient_evidence|是|
|zh_synonym|known-policy-commercial-energy|1/2|insufficient_evidence|否|

上述任务的未命中、缺失主张、领域/类型缺项和降级状态逐例保存在 [结果与失败投影](../artifacts/v15/retrieval/query-forms-outcomes-1.json)。未标注文本不能自动视为无关，本轮缺少完整生成答案的独立语义裁决；没有新增过时来源、冲突或复杂公式案例分母。原文池和所有模型原始答复留本地。RHR最初两次标注漏掉完整ID，失败保留，第三次只澄清完整ID格式后取得有效标签，没有手填等级。

这批结果未建立Hybrid相对相同过滤词项的整体泛化优势，也未证明精排相对融合增加整体覆盖。审核绑定不完整和完整证据组被背景候选挤出是不同问题；不能以放宽审核/完整性或把已读结果重新命名为独立测试来解决。当前Gold在运行后成为开发可见材料，后续回放必须另报开发结果。

同期VO₂和周期的来源接入采用另一生产库和新发布，未进入本次冻结Gold/语料。周期的最小记录解释烟测通过、VO₂仍不足，详见 [来源观测说明](v15_source_observations.md)，不能回填为本次独立评测成功。整仓1554项和Ruff通过只证明软件回归；242份输入与本次运行实现一致，不是专业或真人验证。

完整原始评分见 [成对形式矩阵](../artifacts/v15/retrieval/query-forms-run-1/query-forms-evaluation.json)，各形式子目录保留A–E/词项评分和单次耗时；单次观测不作P95或速度改善结论。复现命令见 [固定查询合同](v15_fixed_query_forms.md)。
