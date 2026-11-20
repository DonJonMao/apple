# HealthZIP 产品体验改版

后续修复：心率、睡眠“查阅依据并解释变化”的缓存过期与查询日志误失效问题，见[依据查询结果修复](rag_result_fix.md)。下文完整改版冻结成绩属于 `42f43dc`；后续补丁验证单独记录。

2026-11-21：未定义的目录动作已[统一默认次数并兼容旧库](../v14_catalog.md)，可直接添加。另完成[自有模型直接回答的四例真实试验](../../artifacts/product_redesign/direct_model_probe/evaluation.md)及[当前证据缺口诊断](evidence_gap_diagnosis.md)；模型试验只用合成数据，没有改动页面的解释路径或联网配置。

本轮基线 `351822c`，工作分支 `feat/healthzip-product-redesign`。实现留在工作分支，不合并主分支、不部署。旧 [PR #1](https://github.com/DonJonMao/apple/pull/1) 核对时仍为未合并草稿，仅复用经重新验证的窄范围代码；五份原有未跟踪 PDF 未修改。

## 现在怎样使用

1. 桌面从顶部切换九个页面；手机点击顶部菜单。设置中管理导入/同步、工作区数据库、时区与可选模型授权。
2. 总览选择本周/本月，先看完成训练、有效工作组与已有健康数据，再看本期主趋势、发现和开始/继续训练。卡片比较上周/月同期并列出实际边界；旧记录明确标日期。
3. 心率、睡眠、体重、有氧分别选择本周、本月、近30天或自定义。数值、趋势、首末变化与明细使用同一快照。数据少或缺失时仍可操作；依据和明细默认折叠。
4. 力量点击开始，自动生成日期标题。添加动作进入独立选择页，搜索/筛选/最近/收藏后点一个动作，收到回执即回训练页。填写负荷、次数或秒/米与可空的RIR，点击完成本组。再加动作时原输入保留。完成和草稿分开；结束时可保存未完成草稿，或只计完成部分并保留本机待同步输入。
5. 复盘以周月复盘、问题分析、报告为次级入口。前置动作与后续表现可直接选择两场核对。完整分析与报告由明确按钮生成，报告支持本周、本月和当前分析窗口，旧报告可再次打开。健康解释和训练建议在独立任务中运行，未配置、慢或失败不会阻挡记录。

## 逐项覆盖

“浏览器”均指隔离合成数据库上的本机 Chromium；没有用 Python 单测替代 DOM/几何验收。实现文件和详细数据证据见 [数据覆盖](data_coverage.md)、[性能](performance.md)、[健康解释](../product_health_details.md)及[训练流程](../product_redesign_training.md)。

|场景|实现及验证|状态/边界|
|---|---|---|
|A01 顶部入口|`app.py`、`ui/theme.py`；9入口桌面/手机菜单，移除侧栏及重复控件|真实浏览器6宽度及AppTest|
|A02 总览周/月|`ui/overview.py`、`analytics/workspace_summary.py`；卡、主趋势、发现及上期同期|数据合同与真实控件|
|A03 详情层级|`ui/body_pages.py`；数值/趋势优先，依据和明细折叠|桌面/手机截图及浏览器|
|A04 月/30天/时区|单一`workspace_scope`，半开本地日历窗口|月界/时区后端测试，浏览器切换|
|A05 旧VO₂|当前窗口无点，历史单独标注日期|数据测试、old状态浏览器|
|A06 心率性能|窄依赖、分域有界缓存、阶段计时|10万/百万、5冷30热后端及30次浏览器返回|
|A07 外进程/写锁|普通页面不`persist_analysis`，读连接独立|真实SQLite写锁、外进程导入及AppTest|
|A08 修订/撤销|候选身份后取最新可见修订，再过滤类型/时间/删除|类型日期更正、删除恢复、历史截止、跨进程|
|A09 直接开始|自动标题，无命名/计划前置|真实浏览器|
|A10 点选即回|独立目录，回执成功后展开新动作并定位输入|30次实际点击回执计时|
|A11 小数/RIR0|`32.5×8/RIR0`保留，单边/单只/总重标签|服务、UI、连续浏览器|
|A12 取消/乱序|取消去抖，旧查询响应不替换新查询，原输入保留|前端事件、真实浏览器及30动作取消位置专项|
|A13 完成事实|完成组统计、复制只成草稿、空会话不计完成|后端与浏览器结束场景|
|A14 草稿恢复|本机/保存中/已存/失败区分，稳定ID重试|刷新、丢回执、数据库核对|
|A15 并发输入/冲突|局部DOM更新、响应不覆盖新编辑、版本冲突明确核对|保存中输入、重试及真实双页签冲突/显式核对|
|A16 长训练|内容高度同步iframe，无内部纵向滚动依赖|30动作、前10动作各3组，几何检查|
|A17 状态图标|局部18–20px图标，失败保输入、真实回执|加载/超时/失败截图与尺寸检查|
|A18 手机输入|字号≥16px、操作触控约44px、焦点稳定|Chromium六宽度；真机Safari软键盘未验证|
|A19 空/旧/单点/缺项|不补零、真实点、旧参考独立、可导入或训练|empty/old/single截图与数据测试|
|A20 RAG独立|限容量任务队列、线程独立连接、授权/证据/版本键|异步单测、真实HTTP撤回正反例；[慢/失败重试/未授权/未配置4个最终浏览器场景](../../artifacts/product_redesign/explanations-consent-final/explanation-browser-results.json)|
|A21 前置疲劳案例|`training/sequence_review.py`、`ui/sequence_review.py`；顺序/口径/逐组RIR/已知休息睡眠核对|实际科学和知识审核/撤回正反例，真实UI异步；不判因果|
|A22 六种宽度|320/375/390/430/768/1440px，主页面无横向溢出|真实浏览器与训练几何；非真机认证|

## 关键数据与状态修复

完成训练必须整场结束且有实际完成组；进行中、未完成、冲突、删除和空会话不变成完成次数。参考复制不携带实际RIR/RPE、症状、质量、时间或完成身份。负荷保留单边、单只、自重、辅助等原口径，不推测杆重。完成保存与更正沿用既有事件服务及乐观版本。

健康事实不再因普通页面访问写入分析卡，也不计算无关训练/模型。跨进程修订触发持久领域版本，窗口按用户时区，移除分钟缓存键。解释与事实分开缓存；证据、声明或事实变化使旧解释失效。新报告在用户明确生成时绑定当前选择和当前事实，显式历史查看保留截止时间与回顾身份，既有冻结报告保持原样。指标解释按工作区、浏览会话和知识库隔离；排队或检索期间撤回联网授权，会在模型请求发送前再次核对。

## 界面与演示证据

全部图片/视频只含合成记录。[改版前](../../artifacts/product_redesign/before/)与[改版后](../../artifacts/product_redesign/final-visual/)使用相同1440×1000、390×844画布；主要页面数据来自`tests/product_redesign_fixture.py`。训练基线早期截图来自另一个明确标为合成的既有夹具。

|页面|改前桌面|改后桌面|改后手机|
|---|---|---|---|
|总览|[图片](../../artifacts/product_redesign/before/overview-1440.png)|[图片](../../artifacts/product_redesign/final-visual/overview-1440.png)|[图片](../../artifacts/product_redesign/final-visual/overview-390.png)|
|心率|[图片](../../artifacts/product_redesign/before/heart-1440.png)|[图片](../../artifacts/product_redesign/final-visual/heart-1440.png)|[图片](../../artifacts/product_redesign/final-visual/heart-390.png)|
|睡眠|[图片](../../artifacts/product_redesign/before/sleep-1440.png)|[图片](../../artifacts/product_redesign/final-visual/sleep-1440.png)|[图片](../../artifacts/product_redesign/final-visual/sleep-390.png)|
|体重|[旧混页](../../artifacts/product_redesign/before/weight-cardio-1440.png)|[图片](../../artifacts/product_redesign/final-visual/weight-1440.png)|[图片](../../artifacts/product_redesign/final-visual/weight-390.png)|
|有氧|同上混页|[图片](../../artifacts/product_redesign/final-visual/cardio-1440.png)|[图片](../../artifacts/product_redesign/final-visual/cardio-390.png)|
|进行中训练|[旧窗口](../../artifacts/product_redesign/before/strength-record-1440.png)|[整页动作](../../artifacts/product_redesign/training/training-active-desktop.png)|[手机逐组](../../artifacts/product_redesign/training/training-active-mobile.png)|

另有[动作选择](../../artifacts/product_redesign/training/training-picker-mobile.png)、[历史](../../artifacts/product_redesign/training/training-history-mobile.png)、[超时待重试](../../artifacts/product_redesign/training/training-timeout-mobile.png)、[字段错误](../../artifacts/product_redesign/training/training-validation-mobile.png)、[结束](../../artifacts/product_redesign/training/training-finish-mobile.png)。[连续交互视频目录](../../artifacts/product_redesign/training/video/)记录添加动作、输入、再添加、结束及恢复场景，最终连续视频见[录屏](../../artifacts/product_redesign/training/video/page@6553f0d087fa133f8304396ead527b0e.webm)，逐项行为见[训练浏览器回执](../../artifacts/product_redesign/training/training-browser-results.json)。

[空数据](../../artifacts/product_redesign/states-empty/)、[仅旧数据](../../artifacts/product_redesign/states-old/)、[单点](../../artifacts/product_redesign/states-single/)各含九页面桌面/手机截图和真实浏览器回执。软件测试不构成医学/科学有效性验证。

## 性能、测试与兼容

性能完整结果、逐次样本、环境与迁移耗时见[性能报告](performance.md)。百万健康样本＋1万训练组的后端心率冷P95从7516ms降至37.79ms；后端和端到端成绩分开列示。本机浏览器热返回30次的事实/主趋势P95为：10万库546.5ms、百万库411.7ms；训练点选动作到可编辑页P95 686.3ms，搜索187.9ms，输入16.8ms。浏览器第一次新进程/新客户端打开仍需加载Streamlit资源，约3.9秒；运行中冷范围与热返回另外测量，不能冒充手机线上速度。

最终冻结版本完整pytest：**2123通过、0失败、1项既有JUnit格式警告**，144个测试文件分四个隔离副本运行；源码哈希与工作区一致。Ruff（src/app/tests及新增tools）、Node3项事件测试和JS语法、依赖锁及wheel构建校验通过。详细命令、各层证据和前两轮失败修复记录见[验证记录](validation.md)及[最终摘要](../../artifacts/product_redesign/validation/final-results.json)。

保留Python/SQLite与既有服务、来源、原始值、修订和科学指标。schema主版本仍为5，增量迁移revision 3，时态投影4.5；新索引自动、事务化、可重复执行，无需清库。单位转换版本1.4.1仅补VO₂等价单位写法。安装依赖明确为Python≥3.11、Streamlit≥1.67（本次实际1.67.0/Python3.11）；新Streamlit的状态化顶部菜单要求该运行时，旧Python环境需要先升级运行时，数据库无需重建。本机草稿仍使用原工作区/会话/组隔离键，不新增云同步或账号。

未验证真实iPhone/Safari软键盘、真实手机网络；模型慢/失败采用隔离故障注入，没有未经授权发送个人健康数据。没有合并或部署线上，也未接触真实健康库进行测试。
