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
