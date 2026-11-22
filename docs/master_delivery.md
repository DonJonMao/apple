# HealthZIP 全面改造交付与验收索引

本轮以 `HealthZIP_Codex_Master_Redesign_Prompt_20261122.md` 为完整实施要求，在 `feat/healthzip-product-redesign`、`150e15d` 及既有未提交改动上继续实施。开始时核对远端，分支比 `origin/main` 多4个提交；没有回退代码、清库、合并或部署。开始时已有33个已修改跟踪文件及未跟踪PDF/代码/证据；原工作区差异另保存在 `/tmp/hz-master-before-1122/initial-tracked.patch`。本次结果与原交付的2194项测试、725ms及96秒声明分别记录。

最终软件回归为 **2302通过、0失败/错误/跳过**，受验源码在运行前后没有变化；Ruff、Node事件/语法、依赖锁和差异检查均通过，见[最终交付审计](../artifacts/master_redesign/validation/delivery-audit.json)。五个一级入口、57个健康字段、W1–W8/E事实问题与行动复评已接通。性能冷路径、资料六问完整性及独立专家/真机验证仍有明确缺口，不能将软件通过写成全部科学和产品验收通过。

## 使用入口

在仓库目录运行 `.venv/bin/python -m streamlit run app.py`，打开终端给出的本地地址。新环境按`uv.lock`安装`ui`、`research`和`knowledge-pdf`可选依赖，以获得本轮验收的界面、正式模型和PDF解析能力。已有工作区继续使用；开始导入/迁移前的备份与回滚说明见下文。

- **总览**：本周/月的真实事实、实际日期、当前目标、单一主趋势、继续训练、当前行动和最近训练。实际观测日期与导入时间分开。
- **训练**：本次训练直接开始，单选动作后回到同一场；录入重量/次数/时长/距离及可选RIR，完成本组。再次添加、返回首页、恢复、结束及历史更正沿用原事件服务。动作进展与Apple运动记录分别在子入口。
- **身体**：通过顶部“切换主题或指标”进入心率、心肺、睡眠、夜间生理、活动/行动能力、体组成、环境及设备事件。周期按有实际记录或设置主动开启显示。长期范围默认365天，可修改；这是显示选择，不是科学最低样本数。
- **复盘**：先显示本地周期事实。生成完整复盘后可切页，返回查看真实进度、保存结果和下载。问题分析提供W1–W8/E；选择行动保存当时观察，之后记录执行情况，并查看同来源、同持续长度的后续观察。
- **设置**：基础资料、导入/同步、模型/资料库和数据诊断。身高体重保留实际测量日期/来源；年龄空白保持未知。私人模型解释仍遵守已有明确授权状态。

旧 `?workspace=heart/sleep/weight/cardio/workouts/strength/progress` 链接仍可进入对应页面。返回保留范围、身体指标及子入口；来源和睡眠口径另按工作区原子保存。训练滚动和输入由原组件保存；不承诺所有浏览器重启后恢复任意主页面滚动位置。

## 逐项证据

| 交付内容 | 文档与可复核证据 |
|---|---|
| 附件所有条款、U01–U13、D01–D25及字段 | [需求覆盖矩阵](master_coverage.md) |
| 方法、观察单位、时态、缺失、正式模型、独立模拟 | [科学验收](master_science.md) |
| 逐来源取得/阅读/许可/审核/检索；六问与RAG边界 | [知识与RAG](master_knowledge.md) |
| 添加→输入→再添加→返回→结束→历史；冲突、离线、六档宽度 | [训练验收](master_training.md) |
| 10万/100万、30热次、全报告和逐阶段瓶颈 | [性能验收](master_performance.md) |
| 本轮Python、Ruff、前端、失败修复与代码身份 | [验证记录](master_validation.md) |

真实页面工件均为合成数据；浏览器使用真实Streamlit与SQLite，没有静态稿替代功能验收。

- 同日期同尺度[改造前](../artifacts/master_redesign/pages/before/)与[最终页面](../artifacts/master_redesign/pages/after-final/)，含总览、心率、睡眠的1440/390宽度。
- [真实交互回执](../artifacts/master_redesign/pages/acceptance/browser.json)：64/59事实、正式长期趋势、稀疏范围局部回退、正式条件关联、行动选择/执行/冻结基线、报告生成后切页返回及保存。
- [长期趋势手机页](../artifacts/master_redesign/pages/acceptance/long-term-390.png)、[联合分析](../artifacts/master_redesign/pages/acceptance/joint-association-1440.png)、[已生成复盘](../artifacts/master_redesign/pages/acceptance/completed-report-390.png)、[基础资料](../artifacts/master_redesign/pages/acceptance/basic-profile-390.png)。六种宽度320/375/390/430/768/1440的主区域几何量保存在回执。
- [W4／W8／E及低频估计专项](../artifacts/master_redesign/pages/workflow-completion/browser.json)：实际目标与行动执行、修改反馈后即时刷新、10→12同条件组与未知条件负例、打开原训练、症状、估计支持窗口与版本上限。核对真实页面传输的Arrow表格及训练输入值，含1440/390截图。
- [训练交互与录屏](../artifacts/master_redesign/training/)、[实际公开原文进入页面](../artifacts/master_redesign/knowledge/browser-final/)。

视觉复用中性深色与青绿体系，本轮重新查看缓存的Lift/Liftosaur官方截图，补充调查记录见[原设计调研](product_redesign/design_research.md)。新的GitHub图片请求曾连接失败，未把失败请求当成功下载。主视觉参考Lift，训练交互参考Liftosaur；未复制其AGPL代码或图片进产品。

## 数据迁移与回滚

继续使用原Repository、MetricResult、Source/Claim/Rule、训练事件与冻结报告；没有另建一套健康事实库。基础schema仍为5，Repository迁移修订升至5，与schema版本不是同一个编号。

本轮新增行动与执行反馈表，及既有 `workout_statistic/workout_event/activity_summary/nutrition_day/cycle_event` 的追加修订账本。新增列、索引与触发器在原迁移事务内执行，重复打开不重复迁移。旧行首次迁移的历史可见时点明确标为未知，不猜测原始导入日期；后续改类型/日期/删除保留修订，不查活旧版本。新的报告与分析有新算法身份，旧冻结JSON、markdown及来源审核身份不被重算覆盖。

无需删除数据库重新开始。新增类型若原ZIP仍在且有使用授权，可显式重新导入同一原ZIP回补；导入与回补保留幂等及原始值。原文件不存在时无法补出历史样本，现有事实继续可用。

使用已有备份工具或SQLite backup API备份数据库，包含已提交WAL；不要只复制一个正在写入的SQLite主文件。也保存工作区的 `.healthzip-views`（来源/睡眠视图选择）及原知识库。回滚到旧代码时应使用迁移前备份恢复到**新路径**，保留已迁移库和迁移后新增训练/行动记录；旧代码不认识新功能，不能靠手工删表降级。原公开来源版本与审核撤销记录也不得覆盖成较早版本。真实个人库回滚演练未进行，迁移兼容验证仅用合成库。

## 必须保留的验收边界

公开原文的取得、AI辅助用途审阅、软件验证与独立专家/真人验证是不同事项。可取得且允许使用的资料继续接入；受版权、访问或目标协议限制的项目逐项保留在知识表，不能靠论文数量声称六问全部完成。

未验证实体iPhone/Safari、真实软键盘/输入法、安全区与移动网络；手机宽度截图和浏览器事件测试不能替代这些结果。私人回答模型目前未配置且无相应授权，本轮实际公共embedding/reranker调用不等于私人生成答案质量通过。模拟趋势/关联不能证明人体预测或因果效果；没有仪器特异重复测量证据时不自动生成MDC或临床重要变化界线。

最终性能表逐项标明达标与未达标，特别保留首次新进程及完整报告慢路径；后台任务可切页不等于计算时间达标。所有失败、重跑和未执行项以验证记录及各专项表为准，不由本交付索引宣称全部验收通过。
