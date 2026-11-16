# 心肺与周期的来源观测接入

原始77项指标及其默认注册表、领域配置和计算路径保持独立。新增两个明确登记的观测扩展，使用原 `MetricResult` 合同，保存到分析快照的 `observations`，不混入原 `metrics` 的77项，不将旧P1 Evidence Card改名或补造生理指标。

|扩展|已有输入|结果及限制|检索功能/领域|
|---|---|---|---|
|`OBS-VO2-REPORTED`|原health_sample中的VO₂max来源记录|按来源/设备/来源版本/声明协议保留原始观察点和数值转换依据；测量方法未经核验，字段存在不能证明为气体分析实测或准确生理真值；不计算因果趋势。|cardiorespiratory；wearable + cardiometabolic，physiology为辅助。|
|`OBS-CYCLE-RECORDS`|已获用户导入的menstrual_flow类别记录|逐条保留原类别，包括无出血、未指定或未知枚举；不把条数当作出血天数或周期数，不推断阶段、排卵、避孕、诊断或训练处方。|cycle；physiology + wearable。|

相同来源分组并不证明协议可比，结果明确标为 `not_verified_by_source_grouping`。没有可用记录时 `value=null`、数据不足；0条导入记录不是生理现象为0。观测证据身份为 `observed`，不能授予科学验证状态。未估计个人误差区间，不增加任何生理权重或个人候选规则。

## 窗口、修订和来源

实际链路为 `analytics.v13.analyze` → `analytics.observations.for_repository` → 原 `samples_as_of/current_source_rows` 修订查询 → `science.observations.evaluate` → 规范结果。原始VO₂和周期数据在Apple导入时已写入health_sample；适配器直接使用其修订账本，不读取缺少可见时间语义的旧cycle_event回顾卡。

沿用原有事件终点、半开窗口、时区及可见截止规则。先解决当时可见修订，再过滤窗口；已知的删除、移到未来或窗外修订不能复活旧值。显式回顾模式仍标记非前瞻；缺失可见时间不能冒充当时已知。

VO₂数值通过现有 `quantity_value` 适配原始数值/单位，未知单位、非有限值和非正值不作为可用观察点，原始数据库值不改。周期类别只保持原值，不用模型或记忆解释未知枚举。来源ID、原始起止、可见时间、有效/总数、单位、缺项及限制均随结果保留。

私人数据库不增加表或列，原77项查询输入不因新增观测而扩大。两种新类型使用单独的有界来源查询。分析快照算法和缓存命名更新到v1.5，观测输入参与快照哈希，已有来源修订版本使缓存失效；历史analysis_run仍可读取，不覆盖旧结果。

## 页面、服务与解释

分析页显示两个来源观测面板，继续消费同一快照；「指标的原始依据与解释」的心肺和周期选项现在可以选择上述结果，调用 `KnowledgeWorkbench.explain_metric` → `retrieve_for_metric`。原77项与扩展的名称和身份在代码注册表中明确区分。

来源解释仍需要精确审核的主张—扩展关系、全部必要领域/证据类型和已知适用条件。生产库没有为这两项新增主张、审核或规则，不能因为入口可用就宣称来源解释充分。证据不足时正常返回 `insufficient_evidence`，确定性的记录回顾仍保留于本地；数值候选权限始终为false。

公共资料模型只接收固定观测任务和有权处理的公共资料，不接收这些私人观察点、类别、来源设备或备注。个人结果解释继续受独立联网授权及原投影约束；结构化原始观察点保持本地，周期详情沿用敏感资料过滤。

## 配置及冻结

观测定义版本为 `source-observations-1.5.0`，领域/应用绑定版本为 `observation-domains-1.5.0`。原 `definitions()` 和 `domains.configuration()` 默认仍只有77项；显式 `include_observations=True` 才包含两个扩展。原领域配置文件及其哈希不变。

```bash
.venv/bin/python -m healthzip.knowledge metric-profiles
.venv/bin/python -m healthzip.knowledge metric-profiles --include-observations
.venv/bin/pytest -q tests/science/test_source_observations.py tests/knowledge/test_v15_source_observation_entry.py
```

原 `metric-retrieve` CLI可使用这两个扩展的完整已计算MetricResult；不能让模型生成该合同。新冻结发布仅在含有扩展绑定时追加 `observation_profile_sha256`，读取时核验。旧发布的配置、成员和审核不变，后加绑定不能进入旧发布；扩展配置变更不能静默改写已冻结的解释依据。

## 验收范围

合成测试覆盖原77项隔离、规范JSON合同、原单位纠正、设备/版本分离、无记录和未知类别、修订/可见性/窗口边界、删除失效、实际Repository及Streamlit分析页、统一解释服务、权限撤销、旧冻结成员和新配置哈希，以及网络投影不包含观察点/类别/设备。

实际集成以合成来源记录经Repository适配，再调用真实公共Embedding和chat_listwise服务，共2次查询Embedding、9次精排请求。心肺/周期均未降级，均因缺生产审核绑定而正确返回证据不足；个人结果解释保持本地。请求投影没有出现合成观察值、周期类别、设备或私人记录ID标记，既有28张知识表原有行保持不变，原77项定义和领域配置逐字节未改。见 [真实集成回执](../artifacts/v15/retrieval/source-observation-integration-1.json)。这是软件调用链与权限边界验证，新增独立评测分母为0。

本批整仓1549项测试通过、Ruff通过，240份验证输入全程未变，真实服务调用实现及扩展配置与回归输入哈希匹配；318份历史工件和原冻结评测目录保持原样。见 [回归回执](../artifacts/v15/verification/regression-source-observations-1.json) 及 [历史保护](../artifacts/v15/verification/historical-protection-source-observations-1.json)。

软件调用链可运行不代表观测的生理真实性、科学解释或六功能的全部知识充分性通过。两项扩展尚无生产审核绑定，新的独立检索与答案语义验收仍待完成；四本付费教材缺正文及原有科学验证缺口继续保留。

## 后续：VO₂来源审核与仍未解决的检索遗漏

原集成回执中的“无生产审核绑定”仍是当时事实。后续追加两项明确标记为AI辅助的来源内容/应用审核：MacIntosh教材文件页索引26两个完整段落提供最大/峰值与测量方法、测试方式依赖；E7三个完整段落提供其单项VO₂比较研究、多传感器估计与用途/人群依赖的解释边界。这里只授予有限来源解释，不证明当前设备/用户准确性，不提供个人校正、风险、诊断或训练处方。五段正文和改写审核包只保存在本地，公开 [哈希及定位回执](../artifacts/v15/knowledge/reviewed-vo2-bindings-1.json)。原28张知识表的旧行、原77项配置和44736项文档缓存保留；`OBS-CYCLE-RECORDS` 仍无生产绑定。

真实合成观测→新冻结发布→公共Embedding/精排调用仍返回 `insufficient_evidence`，没有检索降级，不能将审核存在称为入口已能充分解释。只读取已有向量的 [开发诊断](../artifacts/v15/retrieval/vo2-anchor-diagnostic-1.json) 证实两组审核在全体合格候选中都完整可用，但都没有锚点进入融合前20名：E7的直接VO₂比较原文dense排名1，经RRF后为36；教材方法段落的最好融合名次为140。没有改动RRF、预算或为这两个ID放行。当前选出的6段是一般设备能量验证阅读背景，不能代替这两组指标审核。

[实际调用和边界回执](../artifacts/v15/retrieval/vo2-source-evidence-integration-1.json) 保留这次失败；5次公共模型请求未出现合成私人观测值/设备/记录ID标记，个人解释关闭联网。未知适用信息、商业用途和旧发布都没有获得新增权限；新生产发布 `v15-vo2-source-observation-1` 同时固定观测配置和查询形式哈希。此开发烟测的新增独立案例数为0。后续需要在保持科学绑定和资源预算的前提下解决指标证据组被宽泛阅读候选挤出的路径，再以新盲标案例验收。

## 后续：周期日志的来源审核

另行取得Li等2023年AWHS论文的PMC JATS主文，新增来源 `V15-AWHS-CYCLE-VARIATION-2023`，正文实际许可CC BY 4.0。该来源独立于原13文件/12科学PDF清单；未取得补充材料正文或2022年方法论文。文件级领域标签仍为provisional，不能称为全文科学审核通过。

两项追加主张均明确为AI辅助审核：`V15-CLAIM-MENSTRUAL-DIARY-MEASUREMENT-SCOPE`核对研究人群、Health及第三方应用日志获取和独立的研究周期构成流程；`V15-CLAIM-MENSTRUAL-LOGGING-UNCERTAINTY`核对自报、漏记、追踪准确性敏感性分析和有限生育意识测量的限制。分别绑定观测合同既有的记录测量含义和解释限制类型，不改合同或补造类型。6段完整原文的精确定位、内容哈希及审核身份见 [审核回执](../artifacts/v15/knowledge/reviewed-cycle-bindings-1.json)，来源及许可见 [来源回执](../artifacts/v15/sources/cycle-source-acquisition-review-1.json)。

研究中的连续记录天数、无记录间隔、周期长度和伪差识别阈值均未进入产品算法；不把来源条目当作出血天数、完成周期数或追踪完整性，不推断阶段、排卵、避孕效果、疾病、个人恢复或训练处方。研究参与者确认的追踪准确性不是当前用户验证，群体关联不变成个人风险或因果结论。原77项配置、私人schema及候选权限保持原合同；新增审核存在与实际检索充分性分别验收。

合成来源记录→实际Repository→统一解释服务→公共Embedding/精排的调用命中上述两组共6段完整证据，返回 `evidence_context_supported`，未降级；仅表示最小记录解释合同满足。4次公共模型请求未包含合成私人观察值、类别、设备或记录ID，个人解释仍本地。缺少必要上下文时拒绝授权；商业用途可以使用这份CC BY证据，选出证据中没有NC组件；旧冻结发布没有获得新周期主张。见 [实际调用回执](../artifacts/v15/retrieval/cycle-source-evidence-integration-1.json)。这是开发集成检查，新增独立质量案例数为0，不能据此宣称周期预测或真人有效性通过。
