# HealthZIP v1.4 实际设计

v1.4在以下基础上增加：schema v4的版本化目录/本地媒体；`AdviceContext`统一事实、目标、适用信息和候选冻结；SourceClaim与ApplicationRule分开并带能力策略；按结果负荷分层的描述序列；窗口索引与有界版本缓存。具体实现、迁移及限制见 [v1.4验收](docs/v14_delivery.md)、[科学合同](docs/v14_science.md)、[目录](docs/v14_catalog.md)、[知识](docs/v14_knowledge.md)。

完整需求见 [V1_3_GOAL.md](V1_3_GOAL.md) 与执行包；本文件描述本地实现。原MVP设计保存在 `docs/history/DESIGN_SPEC_v1.0.md`，旧固定建议规则不再适用。

## 数据和入口

`app.py` 使用 Streamlit，`healthzip.cli` 提供命令，根启动器协调网页和本地REST。`importers/` 保留ZIP流式解析、CSV及JSON/JSONL增量导入。XML禁用外部实体与网络，ZIP检查路径/大小/压缩比；来源、原始单位与时间均保留。

`Repository` 在同一SQLite上执行显式事务升级至schema v4，拒绝更高版本降级；`db/schema.sql` 为单一基表定义，`training/schema.py` 与 `db/temporal_schema.py` 增量扩展。升级不将历史未知负荷、器械、ROM或可见时间补成已知值。备份使用SQLite backup API包含已提交WAL，恢复只能写新路径。

## 训练领域

`training/service.py` 是动作目录、别名/收藏/自定义、器械、模板版本、会话、逐组实际、修改/删除/撤销、冲突、计时和建议反馈的统一服务，真实写入既有strength_session/set。原始动作名与稳定目录ID分别保存；条件快照包含动作版本、器械实例、设置、侧别、ROM、负荷口径及次数语义。

模板版本在开始时冻结。计划不是完成事实；组具有draft/in_progress/completed/aborted/skipped等状态。客户端事件ID幂等，真实相同组用不同UUID，乐观版本冲突保留双方修改。修订使分析缓存失效，历史事件可按当时可见性重放。

`ui/training_page.py` 为日常窄屏操作，`ui/offline_recorder.html` 为无需远程资产的本地浏览器记录器。后者用localStorage保存草稿/缓存/待发送事件，导入导出作为恢复入口；浏览器清理数据会失去尚未导出的本地资料。REST token鉴权，CORS仅允许同源及本地文件null origin，不是云同步系统。

## 时间与来源

事件发生时间和本机available_at分别约束截止时间。health_sample/workout/body_measurement/subjective_log通过source_revision保存修订快照；训练事件通过history_as_of重放。训练前分析排除未来事件和晚到修订。明确的回顾模式可展示未知历史可见性的资料，但不能冒充当时预测。

## 单一指标执行合同

`analytics/v13.py` 把Repository快照适配至 `science/engine.py`。全部77指标使用同一MetricResult，含半开窗口、截止时间、原始来源ID、算法/参数/校准版本、数值单位、计数域、覆盖、区间身份、假设、限制、数据状态及证据身份。UI、Markdown和AI消费该结果；周/月按本地日历边界生成，部分周期不与完整前期直接作总量比较。

`science/semantics.py` 复用训练负荷语义，未知不匹配。普通Epley与RIR修正式有独立版本及适用域；超域不裁剪次数。单边片重与两侧片重、每只哑铃与总重、助力方向、时长与次数分别处理。

`science/state.py` 只统计asleep，睡眠区间并集合并，不计inBed；来源/协议分开。组RPE不能冒充整场sRPE。能量区分设备报告、真实TEE、储能和相对/绝对摄入；没有可识别基线与参数依据则返回未知，不用7700或固定误差造答案。

`science/registry.py`、统计/预测/研究模块区分产品参数、计划、物理步长和模型参数。停滞需要预指定参考、实际时间、误差与实用等效范围；重复查看预算不能拯救无效单次区间。B0/B1使用同一前向分割；模拟产物不授予真人有效状态。

## 知识、解释与权限

`.local/knowledge` 中SourceLibrary与TheoryLibrary分别为SQLite，私人训练SQL和动作目录独立。43来源身份、原始字节哈希、许可、版本、更正/撤回、段落/表格/公式或PDF页码坐标可追溯；共享canonical source ID。六域路由先做权限/适用性过滤，再做可复核词法排序。

TheoryCard逐主张绑定真实span，种子与审核分开。数值候选要有匹配能力及明确审核，通用解释卡不能自动升级为候选权限。Source更新不能自动改变被冻结公式；候选保存当时数据、理论、任务、选择、执行及结果。

LLM只解释已计算结果。显式网络同意控制健康摘要外发；摘要/结构化事实/单位/窗口/限制/行动必须匹配已有证据，失败回退本地模板。来源中的文本不是指令，不能改变权限、读其他用户数据或写私人索引。

## 验证边界

178条规范验收有可执行夹具及逐例结果；另有真实Repository、Streamlit控件与Chromium离线断网/丢响应重试检查。软件通过不等于文献主张被独立专业审定。RAG开发集与固定留出分别报告实际分母和失败。科研模拟单独标simulation_only，真人时间外验证、正式专业审核及部分全文获取仍按清单显示未完成。
