# v1.5 检索评测：实跑完成，整体质量未获验收

后续已暴露案例的1.5.1开发回放见 [独立保留的开发报告](v15_development_replay_1_5_1.md)。以下保留原软件基线、原始盲标身份和分数，不用新结果回写历史成绩。

更新：2026-11-17。软件基线 `94568c56f32dc2de26508fbb34e60a8d3a04a069`；A–E及相同过滤策略的A_filtered共6组、每组21例，126次查询全部完成。

15个排名盲标AI案例中，生产E的证据Recall@6为35.33%，同过滤词项参考A_filtered为23.44%；主张覆盖分别为14.44%和16.67%。排名指标的部分改善没有带来完整主张覆盖的整体改善，不能宣称混合精排整体质量已通过。

生产E共21例：1例达到配置中的最小来源证据类型/领域要求，19例证据不足，1例确定性计算跳过RAG。Gold预期可答14例，其中13例仍拒绝；7例预期拒绝/跳过均保持该状态。这些是本轮AI有限标注池的判定，不是独立专家或自然语言完整答案验收。

## 软件与索引条件

最终整仓1499 passed in 486.10s，Ruff通过，运行期间274份输入无变化。之后仅删除测试fixture文件末尾一行空行，知识53项再次通过、Ruff再次通过；运行源码、工具和配置未变。两次输入回执分别为 `regression-page-protocol-final-3.json` 和 `regression-inputs-at-publication-2.json`。核心依赖隔离wheel安装通过，131份源码/资源逐字节匹配；没有把安装成功当作准确率。

预算内索引续建生成37523个不同内容向量，待补建0、失败0；同模型文档缓存44403项与冻结副本逐字节匹配。21个超预算结构单元、1个空单元和1674个不符合当前来源准入的单元分别排除。冻结语料68728片段还包含既有研究资料；向量项数与片段数不是同一分母。E中19例因6–17个候选结构单元缺向量而明确降级，未把这些运行标成完整无降级混合检索。

首次64片段真实服务烟测的精排因预算失败，实际精排0项；修复后第二次实际精排7项，仍为局部索引。原失败 `service-smoke-initial.json`、早期索引中断和所有不稳定回归回执均保留，未覆盖为成功。

## 冻结Gold与执行身份

Gold为 `benchmark-gold-2.json`，SHA256 `4c2f93fa5b2648bd42c4a5fae25c516a8ee69273a9c449aaddbc671c84ec0311`。共21例、14指标：15例排名盲标AI案例、1例已暴露的指标开发诊断、5例确定性权限探针。初版18例Gold及其哈希保持不变；扩展版在A–E运行前冻结。旧visible development、固定source-family holdout及七批独立AI原结果均未重写。

标注者为deepseek-v4-flash，与聊天精排器相同，权重revision未核验；资料包由实现者选择，且只标注有限原文池。排名不可见不等于独立专家验证。未标注材料不能直接认定无关；新结果不增加旧评测的独立分母。此次只评固定指标任务，未验收任意中英文自由提问或生成答案的全部语义。

Embedding实际为qwen3-embedding-8b、4096维；精排实际为deepseek-v4-flash的chat_listwise，不能称独立cross-encoder。A–D只消融语义适用性，始终保留来源权利、当前生命周期及商业/非商业范围；E使用生产过滤。A_filtered与E采用相同适用性策略，作为更公平的排序参考。

A/A_filtered在冻结语料上先完成；文档缓存核对后，B/C/D/E按变体在四个隔离进程中计算，13条固定查询向量预热。精排参数未改：K=6、RRF=60、融合候选20、输入预算24000 UTF-8字节，完整结构单元不截断。实际顺序见 `benchmark-execution-phases-3.json`。评分runner的循环说明不代表这些预计算的实际顺序；所有延迟均为单次观测，不作P95、延迟提升或统计显著性结论。

## 15例排名盲标AI案例的宏平均

|变体|Recall@6|Precision（返回数≤6）|MRR|nDCG@6|主张覆盖|拒绝判定一致率|
|---|---:|---:|---:|---:|---:|---:|
|A|0.2344|0.1111|0.2000|0.1423|0.1667|0.2000|
|B|0.2667|0.1000|0.1967|0.2025|0.1667|0.2667|
|C|0.3367|0.1333|0.3211|0.2743|0.2389|0.2667|
|D|0.3667|0.1333|0.4000|0.3607|0.1444|0.2667|
|E|0.3533|0.1222|0.4333|0.3670|0.1444|0.2667|
|A_filtered|0.2344|0.1111|0.2000|0.1423|0.1667|0.2000|

A=词项，B=语义，C=RRF融合，D=融合/聊天精排，E=生产过滤后的融合/精排；A_filtered=生产过滤后的词项。此表六指标分母均为15例，数值为0–1。其余开发诊断和权限探针分别保存在 `filtered-lexical-and-latency.json` 的split结果中，不混入该表。

冻结评分器的Precision分母是实际返回数（最多6）；空输出且空Gold的案例记为1。这类权限探针不进入上表。无Gold的Recall/MRR/nDCG以及无必需主张的Coverage为null，完整JSON保留每项真实分母。

## 五领域及跨领域（生产E，15例盲标池）

|领域|案例数|Recall@6（分母）|主张覆盖（分母）|
|---|---:|---:|---:|
|physiology|4|0.0000（4）|0.0000（4）|
|strength|4|0.3750（4）|0.1250（4）|
|wearable|8|0.4125（8）|0.2083（8）|
|recovery|6|0.5500（6）|0.2778（6）|
|cardiometabolic|5|0.1000（5）|0.0000（5）|
|cross_domain|8|0.4125（8）|0.2083（8）|

同一案例可属于多个领域，这些行不能求和作新分母。原完整21例的逐领域结果仍在 `evaluation.json`；本表的盲标投影另存 `ranking-blind-domain-projection.json`。

## 定位、准入和冲突的分母

全21例生产E的固定领域映射一致率为21/21；这是配置映射检查，不是自然语言路由准确率。精确source/version/span定位宏平均为0.3316，分母19个有Gold定位的案例。已标注不适用片段和禁用片段的错误准入率均为0，分母21例；未标注片段的科学适用性并未因此获得证明。显式冲突检测1/1，仅覆盖一条事先审核的历史静态规则冲突，没有实现任意正文矛盾识别。

## 逐例输出与失败分析

|案例|Gold片段命中|生产状态|Gold预期拒绝/跳过|
|---|---:|---|---|
|absolute-intake-boundary|0/2|insufficient_evidence|否|
|bodyweight-dynamic|1/2|insufficient_evidence|否|
|energy-device-total|0/3|insufficient_evidence|否|
|estimated-vs-observed|0/3|insufficient_evidence|否|
|individual-error-transfer|1/1|insufficient_evidence|是|
|repetitions-comparison|0/2|insufficient_evidence|否|
|rir-boundary|1/2|insufficient_evidence|否|
|robust-reference-scope|2/4|insufficient_evidence|否|
|sdnn-protocol|4/5|evidence_context_supported|否|
|session-rpe-au|0/3|insufficient_evidence|否|
|session-rpe|0/2|insufficient_evidence|否|
|sleep-observed-duration|1/1|insufficient_evidence|是|
|sleep-stage-estimate|1/1|insufficient_evidence|否|
|session-missing-scale|0/1|insufficient_evidence|是|
|session-population-outside-review|1/1|insufficient_evidence|是|
|arithmetic-no-rag|0/0|not_required_deterministic_computation|是|
|other-user-refusal|0/0|insufficient_evidence|是|
|commercial-excludes-nc-original|0/3|insufficient_evidence|否|
|historical-static-dynamic-conflict|0/1|insufficient_evidence|是|
|consumer-excludes-historical-static-rule|0/1|insufficient_evidence|否|
|army-estimate-formula-scope|0/2|insufficient_evidence|否|

生产21例中，15例至少漏掉一个Gold片段，17个有必需主张的案例均未覆盖其全部Gold主张；SDNN虽然满足最小配置合同，也不能称完整Gold答案通过。BODY-MASS-TREND、STR-12和STR-10的静态审核绑定已缺少定义或方法类型，单纯改排序不能补齐。另一个有同样静态缺口的other-user探针在检索前就已被拒绝，不能把它当作排序失败。

其余失败还包括多片段主张的证据未成组进入前6、精排只处理完整片段预算内的前缀，以及候选中的超预算单元缺向量。15例盲标池中，融合C的主张覆盖0.2389，精排D/E下降至0.1444；当前实跑提示精排可能丢失成组主张覆盖，不能只看首条相关证据或MRR宣布改善。逐例确切缺少的span/claim、当前限制、退化理由和静态缺项见 `failure-analysis.json`，原全文响应留本地。

本轮没有据此放宽完整性、适用性、撤回、更正或权利过滤，没有添加相似度阈值掩盖支持关系，也没有用Gold重新调权或改写标签。Source explanation始终只表示当前最小合同允许的一般来源解释；数值candidate仍由既有ApplicationRule服务决定，21例均未授予candidate权限。

## 后续验收边界

这轮实跑和失败分析已经完成；整体检索/答案质量仍未获完整验收。后续需要补齐原文审核与逐指标绑定、完整主张证据组织、结构预算覆盖和独立答案语义裁决。当前Gold已因结果阅读而成为后续开发可见材料，任何后续已知题回放均须另记开发结果；新的泛化验收需要另一份排名不可见Gold，旧固定来源家族留出继续不参与调参。

四本教材的目标版次授权正文、部分中文资料重用许可、独立专家审核和真人校准/干预验证继续保留缺口。软件实现、软件验证、语料覆盖、专业审阅与科学验证分别报告，不能相互替代。
