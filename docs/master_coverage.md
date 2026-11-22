# 2026-11-22 附件需求覆盖与证据索引

范围：`HealthZIP_Codex_Master_Redesign_Prompt_20261122.md`全文。状态分为已实现/已验证、部分验证、未完成或未验证；来源取得、科学适用性和软件通过分别记录。**本表不是“全部完成”声明**。最终页面、科学和性能专项报告应给实际验收结论；未达标和未验证项不自动改成通过。

字段完整清单及六问缺项见 [知识交付](master_knowledge.md) 与 [逐字段CSV](../artifacts/master_redesign/knowledge/field-six-question-matrix.csv)。该清单实测核对当前 `body_catalog` 57字段和W1–W8/E共66题，包含腹部痉挛和跌倒次数新增身份以及旧未知痉挛身份。

| 附件条款 | 当前实现/复用 | 数据/资料及验证入口 | 状态与未验证项 |
|---|---|---|---|
| 0 完整范围与五方面交付 | 本矩阵、专项交付和 artifacts/master_redesign | 本轮源码、合成夹具及收据 | 全文覆盖跟踪；存在下列明确缺口 |
| 1 最新仓库/保护成果 | 现有分支工作区；复用RHR/SDNN/睡眠事实绑定、Source/Theory、冻结与训练服务 | AGENTS/CODEX_GOAL/DESIGN_SPEC；git差异 | 不回退/清库；旧证据与本轮证据分开 |
| 2.1 五入口与子导航 | app.py、ui/navigation.py | 本轮导航回归、真实浏览器 | 五入口回归及六宽度真实页面通过；总览/复盘手选本月后30次真实返回保持；实体设备未验证 |
| 2.2 总览 | ui/overview.py、analytics/workspace_summary.py | 合成窗口与期间统计 | pages/after-final同尺度事实/趋势/操作检查通过 |
| 2.3 身体主题/独立详情/范围身份 | ui/body_workspace.py、body_pages.py、health_comparison.py | 57字段目录、事实/来源/窗口 | 每字段数据与资料六问分开，不能由页面可达判科学齐全 |
| 2.4 复盘/联合/异步解释 | ui/review_page.py、joint_health.py、report_jobs.py | 周期运行、生成后报告、任务恢复 | acceptance/browser.json已验证进度、离页返回、完整结果下载与仅保存1份报告 |
| 2.5 基础资料/旧测量日期 | ui/basic_profile.py、settings_page.py | 已导入值/测量日期/缺失夹具 | 不把旧体重当今天；用户真实导入值未作为公开测试 |
| 3 视觉/参考/布局 | theme.css、theme.py、导航与组件布局 | 同尺度桌面手机截图、几何检查 | 真机软键盘/Safari与移动网络不以模拟截图替代 |
| 4.1 训练闭环 | training_workbench/bridge/service | training-browser-results.json、training-edge-results.json | 最终逐场景结果见U01–U13 |
| 4.2 输入/0值/重量语义 | strength_component、training/current.py | 输入32.5×8/RIR0、单边总重夹具 | 不以草稿复制实际完成 |
| 4.3 草稿/并发/手机长训练 | 本地草稿、事件UUID、乐观修订 | training-edge/search/browser-results.json | 实体手机焦点/键盘未验证 |
| 5 全指标导入→事实→页面→解释 | normalize、importers、science/body_catalog、analytics/body_metrics | science/field-census.json；知识字段集合核对 | 官方API存在不等于每版ZIP实际导出可得 |
| 6 合同/修订/冻结 | MetricResult、Repository、source_revision | schema/时态/冻结与迁移回归 | 不复写未知条件；迁移/回滚见最终总交付 |
| 7.1 描述统计 | body_metrics、health_comparison、calendar_trend | 观察单位/覆盖/长期日期夹具 | 不把缺日填零或图形插值当观测 |
| 7.2 连续日趋势 | science/calendar_trend.py | science/simulation.json及真实长期页面D23 | 模拟覆盖/误报不等于人体有效性 |
| 7.3 三种变化含义 | science/contracts、health_fact_comparisons | D25测试、de Vet受限用途 | 缺测量误差/重要尺度时保留差值、拒绝升级 |
| 7.4 各类型专门处理 | sleep_regularity、body_metrics、state、normalize | D06–D13、57字段目录 | 具体算法证据和来源缺项在科学/知识文档分列 |
| 8 个人内联合/方向/共同趋势 | analytics/body_questions.py、health_context.py | D16–D18/D23–D24、联合真实页面 | 关联不能称因果；反例/模型诊断须看专项证据 |
| 9 W1–W8/E | workflows/service、evidence、actions、ui/question_page | question-census.json；本表工作流逐项 | 事实闭环与资料完整度独立判定 |
| 10 K0–K7统一库/六问 | knowledge/topics.py、domains、既有两库 | 66题实际检索与逐字段六问表 | 66有受限说明/56有官方字段链接；不是六问全通过 |
| 10.1 原文/阅读/审核/用途 | 65项来源最终审计；21条本轮受限主张（含既有span新用途） | master_source_reviews.json、reviewed-uses.json | AI辅助审核；未完成独立专家复核；未全局放宽许可 |
| 10.2 附录B/C与定向补齐 | 原来源复用、合法公开路径与重试 | source-final-audit.json、source-reading-notes.json | 指定章节/部分全文/仪器重复性/噪声规范仍缺，逐项列出 |
| 11.1 混合检索/预算/缺项 | 原关键词+dense/RRF/reranker；reviewed_metric | public-model.json、incremental-index-final.json | 实际公开模型通过受限实跑；六段预算仍有行动组未召回 |
| 11.2 有用生成/局部回退 | health_facts、product、AI client、页面本地事实 | independent-rag-final.json、事实绑定tests | 本地具体变化/说明/下一步可用；私人远程生成未配置/未授权 |
| 11.3 数字/来源/撤销 | fact_id/范围/单位/覆盖/引用及候选数值来源校验 | final-fact-question-tests、知识生命周期回归 | 非全文自然语言逻辑证明；当前撤销不能改旧冻结身份 |
| 11.4 授权/失败 | 公开查询静态、私人授权隔离、失败状态 | public-model.json、test_async_explanation_consent | 远程私人答案质量没有验收；本地浏览/保存仍可用 |
| 12.1 按依赖读取/降采样 | db/repository、analytics/cache、workspace_summary | pages-100000.json；各规模页面基准 | 显示降采样不改变统计；完整结果以性能专项报告为准 |
| 12.2 缓存/失效/并发 | 修订身份、容量边界、同请求合并、过期保护 | 缓存及来源撤销/清空在途任务回归 | 不能用单进程计数代跨进程修订 |
| 12.3 完整报告慢路径 | 批量上下文/检索复用/异步报告任务 | report-before、report-small-batched、report-100k-delivery/1m-delivery.json | 后台不等于总耗时达标；逐阶段与全部规模由性能报告确认 |
| 12.4 固定规模/30热次/P95 | 页面/训练/报告真实基准工具 | artifacts/master_redesign/performance、training/scale.json | 两档各30次热访问及新进程已测；冷报告和百万热报告未达预算，真机网络未测 |
| 13 沿用框架与组织 | Python/SQLite/Streamlit/既有训练组件 | 原服务、依赖与源码 | 未进行全栈迁移 |
| 14.1 页面与训练 | U01–U13逐项表 | 真实浏览器/截图/测试 | 见下表；不由测试总数代替页面证据 |
| 14.2 数据与科学 | D01–D25逐项表 | 合成夹具、数值模拟、真实长期/联合页面 | simulation_only与专家/真人验证分开 |
| 14.3 RAG正确/有用/实际模型 | master_knowledge.md、独立9月合成数据 | 6统计0错、6篡改全拒、5有用性全过；公开原文/真实公共模型 | 充分/部分/缺项/冲突的独立人工gold仍待补；私人远程生成未验证 |
| 14.4 缓存与性能 | 规模基准和并发回归 | 性能专项报告 | 健康详情两档热P95<1秒；报告10万热P95 2.650秒通过、百万3.394秒未通过，冷报告均未达15秒；两档冷复盘首屏未达3秒，完整阶段见master_performance |
| 14.5 真实浏览器/测试边界 | Playwright+真实SQLite/Streamlit+截图几何 | master_redesign下browser receipts | 无实体iPhone/Safari/真实移动网络结论 |
| 15 九类交付 | 本矩阵、科学/知识/性能/操作/迁移与证据 | 最终总交付索引 | 逐项缺口保留；历史回执不计本次通过 |
| 附录A | 57字段完整目录与逐字段六问CSV | body_catalog、science field-census、知识集合断言 | 字段计算/页面可达/文献六问三种覆盖独立 |
| 附录B | M1–M6/J1–J3/H1–H6/S1–S5/T1–T5/U1–U3/B4 | master_knowledge来源表及原文hash | 明确目标章节未取得和已取得未审核项 |
| 附录C | 既有C1、设备C2、BIA/DXA/能量/日照/噪声 | 65来源逐项表；56实际字段链接 | Bellenger已获接受稿；Plews仍摘要；特定仪器纵向验证未完成 |

## 页面与科学逐场景

以下按附件原编号记录本轮实际证据；合成科学验证、浏览器交互与实体设备结论分别标明。

| 编号 | 原验收场景 | 要求（原文） | 实际证据/结论 |
|---|---|---|---|
| U01 | 桌面/手机导航 | 无侧栏及占位，顶部入口可达，体重/有氧独立，新增指标不挤一级导航 | 通过：五入口导航回归、pages/after-final与acceptance几何；手机顶部菜单，旧深链接可达。实体设备未验证。 |
| U02 | 总览与详情 | 首屏具体变化和数值优先，无巨幅hero、数据目录或长技术说明 | 通过：同日期1440/390前后截图，首屏事实与数值；总览事实可进对应主题。见master_delivery。 |
| U03 | 切本周/月/近30天/来源 | 卡、图、明细、解释、引用同身份；部分日及参考期明确 | 通过：workspace范围/来源/睡眠选择与缓存回归；实际浏览器本周/月/长期及返回保留。时区与半开边界明确。 |
| U04 | 开始训练 | 无强制名称、计划、模板步骤 | 通过：training-browser-results.json A09_direct_start，无名称/计划前置。 |
| U05 | 选动作 | 单击成功自动回同一训练；取消不新增，双击不重复 | 通过：真实单选、取消、重复请求；Node事件3项与训练浏览器。 |
| U06 | 填32.5×8、RIR=0后再添加 | 单边/总重及全部输入保留，0不变空值 | 通过：32.5×8、RIR=0，添加与刷新后保留；training-browser/edge-results。 |
| U07 | 带入历史/结束训练 | 带入为草稿，不复制实际状态；未完成组/空训练不计完成 | 通过：草稿/未完成/空训练及结束摘要；源组核对见master_training。 |
| U08 | 刷新/断线/旧回执/多页签 | 草稿可恢复、幂等、冲突不静默丢记录、保存状态真实 | 通过：延迟/丢回执/刷新/断线/双页签冲突与显式重试；真实浏览器合成情景。 |
| U09 | 10动作多组长训练 | 主页面滚动、末行和添加动作可达，无内嵌小滚动窗 | 通过：30动作，其中10动作各3组；末端入口与取消后滚动恢复。 |
| U10 | 320/375/390/430/768/1440宽度 | 主页面无横向溢出，宽表仅内部滚动，训练输入不靠横向滚动 | 通过：320/375/390/430/768/1440训练与身体/联合/报告几何检查。物理设备另列。 |
| U11 | 键盘/焦点/局部加载 | 不跳顶、不丢焦点、固定元素不遮挡；巨大时钟问题不存在 | 部分验证：Chromium焦点、局部回执、缩小视口和加载图标通过；真实iOS键盘/输入法/安全区未验证。 |
| U12 | 空/旧/单点/部分数据 | 状态真实，已有内容可用，无演示数值冒充用户数据 | 通过：当前app的empty/old/single各6页面×1440/390；states-*回执；稀疏长期页局部回退。 |
| U13 | 返回首页/结束/历史更正删除撤销 | 返回不结束，未同步草稿保留；结束后历史与实际源组一致，修订后统计和缓存一致 | 通过：返回不结束、结束后更正/删除/撤销和实际组一致；训练边界浏览器与缓存回归。 |
| D01 | RHR64对59的合成案例 | 高5bpm、实际窗口/覆盖；不是固定输出或医学异常阈值 | 合成验证通过：`test_health_fact_comparisons`：RHR 64 对 59，差 +5，真实覆盖和前置参考；不是固定值或疾病阈值。详见master_science及本轮回执。 |
| D02 | 两期2天对20天 | 真实数值/覆盖，不补零、不随机删到相等 | 合成验证通过：同文件 sparse periods，2 天与20天完整保留；weekday sensitivity；没有均衡删样本或假设随机缺失。详见master_science及本轮回执。 |
| D03 | SDNN一天20条、一天1条 | 按日代表值等权，采样数可追溯 | 合成验证通过：同文件 dense SDNN day：20条与1条，日代表值等权；保留21条来源与各日n。详见master_science及本轮回执。 |
| D04 | 只有普通HR；混有RMSSD | 已有HR可用，不冒充RHR；指标身份分开 | 合成验证通过：`test_state_energy_prediction`、`test_health_fact_comparisons`：普通HR/SDNN/RMSSD身份；不由普通HR推造RHR。详见master_science及本轮回执。 |
| D05 | 主动测量比例增加/换设备 | 不自动宣布恢复改善，分组/断点正确 | 合成验证通过：同文件 protocol/context/device分组；新旧设备不同流；不因主动测量增多宣称恢复改善。详见master_science及本轮回执。 |
| D06 | 午夜/DST/轮班/23:50与00:10 | 实际时长和事件先后正确，时点不平均成中午 | 合成验证通过：DST实际时长、午夜边界、`test_master_science`圆周时点、`test_alternate_observations`午夜累计；真实工作/轮班类别只有明确记录才可分组。详见master_science及本轮回执。 |
| D07 | 父子睡眠/awake冲突/多来源/无分期 | 不重复累计或拼假完整夜；总量可用、分期未知 | 合成验证通过：父子/awake/分期冲突/多来源测试，分期未知仍有总量；不拼完整夜，不把未知分期算零。详见master_science及本轮回执。 |
| D08 | SRI缺完整睡醒状态 | 不把未记录时段补为清醒 | 合成验证通过：`test_master_science` SRI实际测得状态与未知配对范围；只有睡眠片段不报完整SRI。详见master_science及本轮回执。 |
| D09 | 同Workout能量/距离多结构出现 | 不重复累计；日历完整与覆盖完整分开 | 合成验证通过：`test_alternate_observations`：50样本、50整场、500活动环为3个独立流，重复整场/子区间不再加；历史删除；未合成600的重复总量；总能量字段不冒充活动能量。详见master_science及本轮回执。 |
| D10 | 低频重复发布/窗口重叠/估计上限 | 不造每日点、独立测试或能力停滞 | 合成验证通过：`test_master_science`：真实2个6MWD发布点、支持窗口重叠、显式Apple-2021方法的500m上限；没有对应版本时不套28日/500m。详见master_science及本轮回执。 |
| D11 | 稀疏SpO₂/腕温/呼吸紊乱 | 不估整夜低氧、不当体温或AHI | 合成验证通过：同文件：SpO₂ .97、腕温35.6℃、呼吸紊乱3，真实夜间关系；不是整夜低氧/核心体温/AHI。详见master_science及本轮回执。 |
| D12 | 步数下降但可比步速稳定 | 活动量与能力分别解释 | 合成验证通过：同文件：步数下降、共同日期步速1.2稳定，W7同时呈现；活动量与能力分开。详见master_science及本轮回执。 |
| D13 | 站立小时/分钟、METs、噪声 | 各自物理含义及单位正确，不转成RIR或普通dB均值 | 合成验证通过：同文件：stand1小时与7分钟分开、MET3.2、70/80dBA声能平均；不换成RIR，不普通dB均值。详见master_science及本轮回执。 |
| D14 | 每次30×10达目标停止 | 不自动判停滞；RIR缺失仍显示实际表现 | 合成验证通过：既有组序/训练验收及 `training/exercise-progress.json`；达目标停止与未见PR不自动判停滞。详见master_science及本轮回执。 |
| D15 | 首组稳定/后组下降/休息缩短 | 联合解释使用这些具体记录，行动对应问题 | 合成验证通过：W1/W2调用实际 `compare_work_sets`；组位/休息/RIR和具体下一步；休息变化作为条件，不归因肌肉损伤。详见master_science及本轮回执。 |
| D16 | 训练后睡眠/不同月份指标 | 不倒置先后、不拼同步变化 | 合成验证通过：W6只匹配睡眠先于SDNN，W7只用共同日期，双方向训练配对；不倒置先后、不跨月份拼同步变化。详见master_science及本轮回执。 |
| D17 | 睡眠几乎不变、共同时间趋势 | 不制造睡眠效应；模型检查伪关联 | 合成验证通过：`test_master_science`近常量睡眠、时间共趋势无因素重叠局部回退；不制造睡眠因果效应。详见master_science及本轮回执。 |
| D18 | 体重下降、绝对力量维持 | 比值变化不当独立力量进步 | 合成验证通过：同文件与W5：体重下降同时展示40kg×8绝对组、负荷/体重；比值受分母影响。详见master_science及本轮回执。 |
| D19 | 无饮食/只有一餐/单次周期症状 | 主要分析可用，不编全天缺口或周期相位 | 合成验证通过：正常ZIP350kcal部分餐、旧nutrition_day partial、单次周期/症状；主要分析可用，不补全天能量缺口/周期相位。详见master_science及本轮回执。 |
| D20 | 无通知/功能未知/导出不支持 | 准确不同状态，真实通知独立处理 | 合成验证通过：availability声明及无导入/无可见记录/无效测试；8类真实事件/计数；已知关闭/不支持须有来源声明，无通知仍未知。详见master_science及本轮回执。 |
| D21 | 类型/日期修订、删除、历史as-of | 当前正确、旧记录不复活、冻结结果不改写 | 合成验证通过：既有 source_revision 类型/日期/删除/冻结测试；新增辅助表迁移、更新、删除、回补幂等测试；旧历史不可见时不回填过去。详见master_science及本轮回执。 |
| D22 | 模型无趋势/趋势/相关误差/缺失 | 分别报告偏差、区间覆盖、误报和适用范围；模拟不冒称人体验证 | 合成验证通过：两随机种子的8场景模拟JSON，非线性/边界/因素回退测试；simulation_only。详见master_science及本轮回执。 |
| D23 | 正式模型实际页面成功与回退 | 长时段合成记录在真实长期页显示计算趋势、单位、区间、范围与方法；有预设个人内关系和条件重叠的记录在联合页显示计算关联；稀疏/不适用记录局部回退，不能仅有后端函数或预写文案 | 合成验证通过：`pages/acceptance/browser.json` 的长期正式模型、联合模型、稀疏回退；对应390/1440截图；真实浏览器读取计算值和图点；不是仅后端测试。详见master_science及本轮回执。 |
| D24 | 同日晨练/午睡/晚练/跨午夜睡眠 | 分别构造睡眠→随后训练与训练→随后睡眠；真实配对和未匹配原因独立，不能同日拼接替代方向 | 合成验证通过：`test_master_science`晨练/午睡/晚练/跨夜；`test_alternate_observations`正常问题入口跨所选训练范围取先后支持事件；两方向和未匹配原因独立。详见master_science及本轮回执。 |
| D25 | 历史范围/测量误差/重要变化 | 合成误差证据与独立目标尺度分别驱动三层结论，缺任一依据不自动升级；生活记录SD不自动生成MDC或报警线，已有差值仍显示 | 合成验证通过：`test_master_science`三层独立；`test_alternate_observations`正常MetricResult+cache的匹配误差3、独立目标5、实际差4；超过误差=True、达到目标=False；无证据不升级。详见master_science及本轮回执。 |

## 工作流逐项

| 工作流 | 事实/问题入口 | 当前资料检索的具体边界 | 实际UI/行动复评证据 |
|---|---|---|---|
| W1 | 力量进步与下一次 | 负荷/次数可比与睡眠先后有受限用途；非个体预测/任意重量处方 | master_training：完整实际记录与逐组建议链路；问题事实由question-census逐项核对 |
| W2 | 恢复与训练耐受 | Carter/SDNN方法返回；新动作组受6段预算影响 | question-census实际计算；共享行动保存/反馈流程由W6真实浏览器走通，未逐题录屏 |
| W3 | 心肺变化 | WHO活动机会、VO2测量限制返回；具体行动仍缺 | question-census实际计算；低频支持窗口、重叠、重复发布与方法上限已传入问题，W7同口径支持表在workflow-completion/browser.json实证；通用行动保存由W6浏览器走通 |
| W4 | 长期目标、轨迹与已选行动 | de Vet与负荷比较返回；原因反例及行动用途仍缺 | 读取截止时可见目标与冻结行动、实际执行反馈、同来源/设备/时区后续值；571项专项含W4空库、反馈更新、历史冻结与动态依赖，workflow-completion/browser.json实证目标/执行/10→12与未知8→未匹配；UI改反馈后即时刷新且基线不变 |
| W5 | 体重与力量 | BIA条件、去脂体重定义、称重方法返回；不推算肌肉/热量缺口 | question-census实际计算；共享行动保存/反馈流程由W6真实浏览器走通，未逐题录屏 |
| W6 | 睡眠与训练 | 睡眠覆盖/结构及NIH睡眠日志行动已实取 | D24真实先后测试；W6模型、选择/反馈/冻结基线浏览器通过 |
| W7 | 活动量与行动能力 | WHO术语区分及HHS渐进活动行动已实取；设备特异误差仍有限 | workflow-completion/browser.json真实表格核对两次500m发布、支持重叠/版本上限及步行稳定性未知支持反例；共享行动流程由W6浏览器走通 |
| W8 | 周期与症状 | 日志不确定性、个体观察/异质性可用；不推断相位 | 真实事件连接实际训练组；同动作跨事件配对保留可比正例与条件未知负例，不推断相位；可选组按真实记录/主动开启显示；workflow-completion/browser.json核对10→12及未知8→8，并打开原训练核对真实input值 |
| E | 健康/安全事件 | 官方字段及本地事件事实可用；现有已审核事件回应说明返回 | 真实导入事件、已记录症状与训练先后均进入问题；日期精度未知时不推断日内顺序；workflow-completion/browser.json核对疼痛、备注及实际组；未逐种通知录屏 |
