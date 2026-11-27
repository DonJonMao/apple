# 联合分析与普通训练修复证据（2026-11-27）

本次在 `feat/healthzip-product-redesign` 的 `88de09a4b907e23a544d1134e1d798e14f2a8142` 当前工作区继续实现。核对时 F01/F02/F04 仍存在；没有回退分支、覆盖旧冻结结果、清库或改动未跟踪 PDF。以下验证只使用独立临时数据库中的合成数据。主交付中的最终全量回归与源码身份优先于这里的中间专项结果。

## F01 / F02：睡眠与 SDNN

`analytics/body_questions.py::sleep_sdnn_associations` 保留原 `calendar-gap-ar1-reml-profile-1.1` 模型。删除以睡眠变化和 SDNN 变化的乘积区分支持／削弱的逻辑，也没有改为依据同批数据的拟合方向判支持。各组新增：

- `identity`：来源、设备、协议、来源版本、已记录采样条件、实际本地采样时间跨度、睡眠来源、配对日期／观察／原始 SDNN 数量。
- `measurement_signature`：采样方式、姿势、记录时长、算法版本等条件不同分别分组。已知和未知不合为一组。
- `neutral_observations`：相邻观察的两项真实变化，注明共享日期、不是独立假设证据。默认没有预指定方向，`hypothesis.status=exploratory_no_prespecified_direction`。
- `direction`：依据原模型区间描述正向、负向、方向不明确或无法估计；不代表恢复好坏或睡眠质量。多个组不产生全局最大系数结论。

6 小时测量开始时间桶继续保留为产品分组方法，详情明确同桶不是相同生理条件。散点图显示原始配对，明确没有扣除时间因素；无法估计的组仍显示实际配对与具体限制。协议 ID、内部组身份和诊断放在展开区，首层显示来源、设备、已知条件、实际时段、日期和样本数。

`ui/question_page.py` 使用短标题、紧凑本地日期和可直接打开的“记录来源”控件，避免重复长问题和大段日期先占据首屏。更完整的生活记录和观察保存在展开区。新增 `data-hz-question` 绑定真实 `fact_id`，浏览器切换验收等待新身份和新值。

## F03 的共同统计部分

`analyze_questions` 新增可选 `period`／`previous`，传入周/月边界；`question_views` 同次批量准备本期与前期记录。指标行复用详情使用的 `_points` 和 `_daily_summary`：`value`、`first_value`、`difference` 表示本期／前期完整本地日代表值的期间中位数及差值，不再拿末条减首条冒充期间变化。`comparison` 保存相同范围、覆盖、完整日与部分日、原始来源引用；`comparison_identity` 延续详情的分组身份。原始实际首末轨迹以明确的 `trajectory_*` 附加字段保留。

关联、事件、训练及生活记录仍仅使用所选本期，不将前期查询结果混入。本期睡眠定义明确保存为按睡眠事件结束本地日期归属的已观察时长；不同睡眠口径不能宣称同身份。数值文案使用 `analytics/display_format.py`，原始单位和未舍入值不改。

报告由主代理接入同一 `analyze_questions` 结果；这里的测试实际验证独立心率夹具前期中位数 60、本期 62、差 2，而末次减首次数值为 39，并核对详情与问题页的来源引用和覆盖完全一致。单问题与多问题请求的该题 `fact_id` 相同。

## F04：普通记录的长期描述

`workflows/longitudinal.py::ordinary_review` 接收所有可见、未删除且已完成的实际组，不要求 `reference_set`。物理条件复用 `training.daily_history.daily_identity`，按动作身份、器械／设置／侧别／ROM／负荷口径、组类型和原始组位分层。每组保留全部实际日期、原始重量和单位、次数、RIR、训练／动作实例／记录身份与修订。

同一场中相同条件、相同组位存在多个记录时不挑最优配对；这些记录完整保留且列入未配对身份。已知且唯一的组位按实际时间顺序比较相邻场次。负荷、次数和已填写的 RIR 分别比较；RIR 空值和 0 不合并。辅助重量减少标明“辅助减少”，不套用负荷下降＝退步。条件未知仍有实际轨迹，只限制依赖条件的比较。

阶段摘要将所选范围等时长分成较早／近期两段。这是明确的产品显示选择，不是医学阈值；每段再按同负荷列出全体次数／RIR 中位数、最小／最大值、记录数、场次数和原始引用，不取最好成绩、不合成能力分数、不推断停滞。原 STR-11 参考序列及依赖它的专项方法完全保留。

调用关系：

- 问题页 W1/W2/W4/W5：`analyze_questions → question_views → ordinary_review → ordinary_training`，同一请求只计算一次普通轨迹和一次兼容强度行。
- 原专项长期入口：`run_workflow → ordinary_strength_review → ordinary_review → supplements.ordinary_training`，与原 `strength_points`／`long_term_review` 并存。
- 页面：`render_ordinary_training` 显示实际多点趋势、完整记录和阶段表；控件／图按问题 ID 或运行 ID 隔离。周期报告使用相同问题结果中的 `ordinary_training`。
- 报告请求内普通描述按范围、截止、时区、任务选择和输入修订复用；`_training` 只读复用报告事件投影，只解还原所需的 after/result，不复制每个事件的请求及 before；复用只在既有请求上下文内生效。公开页面缓存仍使用既有隔离复制、修订失效和清空代际机制。

## 独立软件与真实页面证据

`tests/science/test_repair_association_training.py` 的独立场景日期为 2024 年，关联随机种子 91241／91243；真实截图采用 2026 年不同夹具，未将截图日期和值照抄为唯一测试。

| 场景 | 精确验证 |
|---|---|
| T01/T02/T03 | 正系数 4.3、负系数 −3.7、零系数；估计区间／方向；支持和削弱数量均为 0；131 条相邻描述；时间不可区分时仍保留 132 对观察 |
| T04 | 两来源方向相反及第三个 4 点稀疏来源；全部组分别保留来源／设备／实际时段／配对数；算法版本／记录时长改变分组 |
| T05 | 同一范围、来源下详情与问题期间中位数、差值、覆盖、来源引用相等；单题／批量 `fact_id` 相等 |
| T06 | 无参考普通训练 30 kg×10、×11、×12 全部存在；阶段较早中位数 10.5、近期 12；真实 TrainingService 到问题和旧工作流；STR-11 没有被伪造 |
| T07 | 换器械、负荷口径、组位、组类型、侧别分别分层；缺 RIR 与 RIR=0；增重降次数分别保留；辅助重量；未知条件和同场重复实例不产生虚假配对 |

专项命令：

```bash
.venv/bin/python -m pytest tests/science/test_repair_association_training.py tests/science/test_master_science.py tests/science/test_question_context.py -q --disable-warnings --maxfail=3 --junitxml=artifacts/repair_20261127/science/core-final-tests.xml
.venv/bin/python -m pytest tests/science/test_repair_association_training.py tests/science/test_master_science.py tests/science/test_question_context.py tests/integration/test_analysis_w1_flow.py tests/integration/test_workflow_six_repairs.py -q --disable-warnings --maxfail=3 --junitxml=artifacts/repair_20261127/science/targeted-final-tests.xml
```

核心最终记录为 `final-core-tests.xml` 的 90 通过（含新增 15 个独立场景）；广域最终专项 `acceptance-tests.xml`／`acceptance-tests.log` 为 123 通过（54.13 秒）。并补验请求内修改返回 session 的次数及嵌套设置，不会污染下一次 `session_as_of`；后续全应用统一验收另记。曾包含旧报告长度要求的广域测试记录为 130 通过／4 失败（`targeted-tests.xml`），失败原因是新可读报告 952 字未满足旧 `len(markdown)>1000`，上下文撤销提示仍存在；此原失败不删除。Ruff 和 `git diff --check` 均已通过本子任务修改范围。

浏览器工具 `tools/repair_science_browser.py` 启动真实 Streamlit，数据库和日志全部在临时目录；禁用外网，远程模型调用为 0。只读导出的审查代码在独立 `/tmp/hz-repair-20261127-baseline` 中生成旧版合成数据库，当前仓库不切换。

- [旧版同夹具回执](../artifacts/repair_20261127/science/pages-before-final/browser.json)：保留旧支持／削弱行为和缺完整普通轨迹的真实对照。
- [当前页面与真实点击回执](../artifacts/repair_20261127/science/pages-delivery/browser.json)：三组分别显示 +2.92、−2.92 ms/小时睡眠和无法区分时间因素的局部失败；实际选择负向来源后等待新的 `fact_id`，只余负向结果的一张图；普通三次记录的真实 Plotly y 为 `[10,11,12]`。
- 两页在 320／375／390／430／768／1440 宽度主页面均无横向溢出，390／1440 截图在上述目录。真实点击、来源切换、展开记录、选择动作轨迹与截图分别保留。
- 初次旧版验证因拿到新 schema 的合成数据库被旧应用正确拒绝（`pages-before`），以及第一次切换未等待新渲染身份的浏览器断言失败（`pages-final`）均保留。后续工具改为按相应代码生成合成库、等待真实问题 `fact_id`，没有改写旧失败为通过。

## 尚未完成与结论边界

上述验证证明软件的描述方向、分组、普通记录入口和页面数据行为；没有授予模型人体效度、个体因果效应、恢复改善判断、独立专家审定或设备误差阈值。没有实体 iPhone、Safari、软键盘或真实移动网络验证。完整报告性能、最终全量回归与报告冻结完整性由主交付统一记录，本文件不把专项测试耗时当作产品性能达标。手机首屏因范围控件和分组身份仍有滚动，全部实际记录与趋势可达；未以删除事实压缩正文。

## 全量发现的旧断言与日期夹具复核

首轮全量的 `test_w4_normal_page_produces_candidate_feedback_and_shared_reports` 在月度复核直接访问不存在的 `long_term_review`。保留其合成失败库检查后确认：当天为 11 月 27 日，原夹具六条参考均在 11 月；周／近 30 天仍正常触发长期复核，而月度专项按既有合同只比较 9／10 两个完整月，11 月参考完整保留在 `partial_current_period`，没有产品回归。阳性夹具现用 `completed_periods` 仅确定前两个完整月各自的中点作为两次实际参考日期，再添加 26／18／10／6 天前的参考。仍明确要求所有三个范围有真实参考且 `start_long_term_review=True`，候选 34 kg、数值来源、拒绝／未执行反馈等断言不变。无参考运行不能伪造专项长期复核。

`test_daily_training_page` 旧断言要求可读报告含原始字符串 `420`。实际报告显示 `7.0 小时睡眠` 且来源仍在；更新为检查人读小时值，并额外检查冻结 `STATE-SLEEP-24H` 原始 420 分钟、W6 原始轨迹 420／来源、当前实际组 55 kg×12 的 UUID 和无 reference 标志。没有删除或降低科学数值断言。

仅修改上述两份测试和 `test_analysis_w1_flow.py` 的可选日期夹具参数，产品代码未变。`post-full-regression-r1` 的调查失败保留；r2 三个完整文件为 17 通过／45.97 秒；明确按完整月选日期后的最终 r3 为 **17 通过／46.61 秒**，记录于 `artifacts/repair_20261127/science/post-full-regression-r3.xml` 和 `.log`。Ruff 与 `git diff --check` 通过。最终全量由主交付继续验证。
