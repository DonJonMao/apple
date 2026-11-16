# 检索1.5.1开发回放

2026-11-17。代码提交 [`49fc54a`](https://github.com/DonJonMao/apple/commit/49fc54adeba96982d3349b9c65e9f2cfed032999)。本次完整运行A–E及A_filtered，6组×21例，共126次查询。Gold已经公开并用于定位实现缺陷，因此全部结果都是开发回放，新增独立案例数为0。原始盲标AI结果及失败记录保留于 [原评测报告](v15_evaluation.md)，不回写为本次成绩。

## 冻结条件和改动

沿用Gold-2，SHA256 `4c2f93fa5b2648bd42c4a5fae25c516a8ee69273a9c449aaddbc671c84ec0311`；语料仍是冻结副本 `v15-benchmark-corpus-2`，没有因本地后续向量补建改变本次评测。模型、固定指标查询、来源审核绑定、K=6、RRF=60和融合候选20保持原配置。

改动为：完整单元的重叠精排窗口保留全部融合候选；在相同K预算内聚合已审核的完整主张；沿显式required_by关系核对必要依赖。所有六组均采用相同聚合规则，没有硬编码Gold的片段或答案。原始阶段名次和证据组选择分别审计。模型身份、领域配置、评分器和知识实现文件哈希保存在运行身份中，代码变化后不能混用输出续跑。

## 原15例子集的前后对照

此处保留原15例子集便于比较，但它们在本次全部属于已暴露开发案例。指标为逐案例宏平均；Recall、Precision、MRR、nDCG、主张覆盖及拒绝判定一致率的分母均为15。Precision以实际返回数为分母，最多6项。

|变体|Recall@6|Precision|MRR|nDCG@6|主张覆盖|拒绝一致率|
|---|---:|---:|---:|---:|---:|---:|
|A 词项|0.5644|0.2111|0.6667|0.5381|0.4944|0.3333|
|B 语义|0.4556|0.1778|0.5667|0.4808|0.3667|0.2667|
|C 融合|0.8867|0.3111|0.9000|0.8015|0.7889|0.5333|
|D 融合精排|0.8867|0.3111|0.8333|0.7636|0.7889|0.5333|
|E 生产过滤精排|0.8533|0.3000|0.8722|0.7855|0.7222|0.5333|
|A_filtered 生产过滤词项|0.5311|0.2000|0.6167|0.4891|0.4278|0.3333|

原E的Recall/主张覆盖为0.3533/0.1444，本次为0.8533/0.7222；相同过滤词项参考也从0.2344/0.1667提高到0.5311/0.4278。因此改善包含证据聚合本身的作用，不能全部归因于Embedding或精排。D与C的Recall及主张覆盖相同，D的MRR和nDCG更低，本次没有证明聊天精排相对融合额外改善。

## 全21例的领域对照

以下比较本次E与采用相同生产过滤及聚合规则的A_filtered。同一例可属于多个领域，不能把领域行相加作新分母。

|领域|案例数|Recall分母|E Recall|词项Recall|主张覆盖分母|E主张覆盖|词项主张覆盖|
|---|---:|---:|---:|---:|---:|---:|---:|
|physiology|5|5|0.7333|0.0000|5|0.6000|0.1000|
|strength|6|5|0.6000|0.5667|5|0.4333|0.3667|
|wearable|9|9|0.8296|0.4222|9|0.7222|0.3889|
|recovery|8|8|0.9333|0.8917|6|0.8611|0.7222|
|cardiometabolic|6|6|0.7778|0.0000|6|0.6667|0.0833|
|cross_domain|9|9|0.8296|0.4222|9|0.7222|0.3889|

本次E的全21例Recall宏平均为0.7965（19个有Gold片段案例），主张覆盖为0.6667（17个有必需主张案例）；A_filtered分别为0.5246和0.3922。已标注不适用/禁用证据准入率仍为0，预设显式冲突检出1/1；这些分母只覆盖有限AI标注，不代表未标注材料已经科学审定。

## 支持状态与保留失败

E有5例达到最小来源证据合同、15例证据不足、1例确定性跳过。Gold预期可答14例中5例达到合同，9例仍拒绝；7个预期拒绝/跳过全部保持正确状态。满足最小合同不表示全部Gold主张或完整自然语言答案都正确。全部126次结果的数值candidate权限均为false。

剩余失败包括：absolute-intake、bodyweight和历史能量案例缺定义绑定；设备总能量未召回完整定义与可识别性依据；同负荷次数及RIR仍缺定义/方法绑定；个人参考缺完整测量不确定性主张；sRPE-AU未聚合采集时点依据。具体缺少的片段、主张、证据组选择、适用条件和退化原因见 `failure-analysis.json`，不能用排名改善替代这些审核缺口。

D/E分别尝试50/49个精排窗口，5次查询发生严格排列无效或传输/JSON错误，均保留窗口审计并退回融合顺序：D的estimated-vs-observed、session-rpe-au、session-rpe，以及E的sleep-stage-estimate、army-estimate-formula-scope。所有成功窗口的候选覆盖核对通过，返回原文、来源和版本与真实原始片段逐字一致，没有截断或身份替换。冻结副本仍有21个被字节预算排除的结构单元，E的19个实际检索案例均明确降级。

运行采用四个隔离进程执行六组，已有查询向量为热缓存；耗时仅为并发单次观测，不作P95、统计显著性或加速结论。多窗口增加模型请求量，也没有在本次证明额外质量收益。

## 工件与复现

公开结果位于 `artifacts/v15/retrieval/development-run-4/`：`evaluation.json`、`filtered-lexical-and-latency.json`、`development-comparison.json`、`failure-analysis.json`、`execution.json`、`run-integrity.json`。原文、完整响应及向量留本地。曾中止的57次开发尝试另存中断回执，没有混入最终分母。

```bash
.venv/bin/python tools/v15_run_retrieval_benchmark.py \
  --root .local/v15/benchmark-snapshot-2 \
  --gold artifacts/v15/retrieval/benchmark-gold-2.json \
  --services-config .local/knowledge/model-services.json \
  --release-id v15-benchmark-corpus-2 \
  --private-output .local/v15/new-development-replay \
  --public-output artifacts/v15/retrieval/new-development-replay \
  --evaluation-purpose development_replay
```

顺序复现使用同一冻结输入，但聊天模型权重revision未核验，不能保证产生逐字相同的排列。当前五领域的已知题覆盖得到改善，完整v1.5验收仍须补齐剩余审核、心肺/周期调用链、超限单元及新的语言分层盲评，见 [完整目标清单](v15_goal_acceptance_audit.md)。
