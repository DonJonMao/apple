# 00a35d2 后续修复交付

本轮基于 `feat/healthzip-product-redesign` 的实际进度继续修改，没有回退审查提交。第一批已按用户要求发布为 `f863e2e80af5da41bd1e211a91ca9d788e44a38f`；本文件继续记录其后的资料接入、冷计算及页面补修。**软件通过、内容核验、页面行为与性能预算分别判定。**

前一附件 F01–F09 与 T01–T24 的既有修复和验收保留于[前轮逐项交付](repair_delivery.md)。下文对应后续附件 R01–R07 与 T01–T23，继续检查这些分析主路径；旧轮次的性能和测试计数不冒充本轮结果。

原始健康库、冻结历史、已有失败工件和五份原有未跟踪 PDF 保留。健康验证只用隔离合成库；公共资料先备份核验，再追加到实际资料库，28 表、920,291 条原有内容行逐行哈希不变。无私人记录外发或外部模型调用。公开提交不包含数据库、用户 PDF 或受限文献原件。

## 逐项状态

| 项目 | 状态 | 实际变化与证据 |
|---|---|---|
| R01 日历 | 已修复 | 日期使用实际日期身份，其他重复控件有实体/角色身份，旧节点只消费一次。真实 28/29/30/31 天、多月、三个不同日期的训练 ID/名称/组 UUID、刷新/返回/焦点及完整训练操作通过；[日历交付](followup_calendar.md) |
| R02 主题成立 | 已修复 | 只有疲劳时保留疲劳事实，不生成步态/周期/通知任务；仅步数可描述活动量；真实通知保留日期/设备/来源记录；周期三状态独立。问题、行动候选、报告及导出消费同一主题状态。当天已有体重保留日内记录，未塞入完整日期间中位数；[专项](../tests/integration/test_followup_topic_applicability.py)、[页面](../artifacts/followup_20261127/pages/topics-final/browser.json) |
| R03 行动观察单位 | 已修复 | 低频估计保留支持窗口、重复发布、版本/上限与实际执行关系；当日可见估计不被排除；420→445 m 不再冒称独立行动后测量。旧冻结定义不改写；[行动交付](followup_actions.md)、[最终页面](../artifacts/followup_20261127/actions/browser-final/browser.json) |
| R04 证据与当前状态 | 已修复 | 排第三的适用行动进入正文并带限制/引用；同原文链接去重而保留定位。新增冲突、前提冲突、撤销、缺版本及服务故障分别处理，旧正文不变；[知识交付](followup_knowledge.md)、[最终真实报告](../artifacts/followup_20261127/knowledge/browser-publish-final/browser.json) |
| R05 六问资料 | 部分完成（六核心主题已接入） | 六核心主题有 36 条实际答案、直接出处与限制；五条窄主张已追加实际公共库，HRV 两个具体问题进入默认有界检索，原行动依据保留。六主题有数据/缺失共 12 个页面与报告流程通过。设备特异、人群/个人误差、部分全文与独立专家范围仍受限；[实际安装及页面](followup_knowledge_completion.md)、[六问与剩余缺口](followup_knowledge_six_questions.md) |
| R06 报告性能 | 部分完成 | 新报告普通读取只加载小型冻结阅读对象，单题/轨迹按需读取，完整审计可离线重建，每次明确生成有独立 ID。最终 r3 浏览器个人生成/重开已验；10 万与 100 万规模完整生成各等待 600 秒仍未完成，相关热生成和历史重开未验收。此前 r2 后端压力冷生成 103.15/174.88 秒也未达 15 秒，三档后端热生成和读取达标；两种时钟与源码范围分别保留，全部原组/未知条件身份核对见后端证据；[后端证据](../artifacts/followup_20261127/performance/final-backend-summary-r2.md)、[页面及瓶颈](followup_performance.md) |
| R07 阅读与页面 | 部分完成 | 默认报告生成后只有一条阅读路径、一张所选冻结趋势；两来源与分析时区明确，下载正文逐字相等。补修当前来源提示挤出手机首发现，以及空目标元信息错误优先“先前目标”步骤；来源限制仍在解释/行动之前，旧冻结不变。历史版本选择的首次菜单操作仍可能关闭，正式热样本需第二次操作；该准备过程与打开后读取分开计时。实体手机/Safari/软键盘和所有设备组合未验证；[页面证据](../artifacts/followup_20261127/pages/topics-final/browser.json)、[后续真实诊断](followup_performance.md) |

## 行为与读取证据

`topics-final` 以真实 Streamlit/Chromium 完成只有疲劳、只有步数、真实事件、周期三状态及双来源 RHR 七个独立合成场景。每次等待新的事实/渲染/报告身份，核对实际文字与数值；320/375/390/430/768/1440 检查主页面溢出，390/1440 还核对第一条完整发现的屏幕边界。第二次明确生成得到不同报告 ID；打开历史不再叠加当期预览；下载与对应冻结 Markdown 逐字比较。

最后补正 W4 的空目标身份：`goal_context` 存在但 `goal` 为空不代表用户选了目标；只有疲劳时也不再生成“按先前目标复评”的空任务。保留原空目标元信息供旧消费者读取。七场景重跑见 `topics-goal-final`；补齐空目标元信息后的疲劳/未开启周期/双来源及历史流程见 [topics-empty-goal-final](../artifacts/followup_20261127/pages/topics-empty-goal-final/browser.json)。主代理已目视检查手机新报告、重开、估计结果及带行动依据正文。

`tests/integration/test_followup_report_reading.py` 通过 SQL 追踪证明普通读取仅一个 reading 对象、单题仅其冻结问题，未读取 analysis_run/workflow_run；源修订删除后旧结果不变，审计离线重建与显式完整读取相等。旧格式保持读取兼容，没有后台重写历史。高级科学分析是明确的完整详情消费者，继续显式加载完整结果。

r2 后端在同一固定源码、原三档夹具上顺序执行，每档冷调用与 30 次热调用分别记录；没有剖析器、没有团队并发重任务，OS 缓存保留，共享宿主外部负载不受控。个人/10 万/100 万冷生成分别 10.51/103.15/174.88 秒，热生成 P95 分别 0.0208/0.0204/0.0236 秒；普通读取只查询一个阅读对象，热读取 P95 均低于 0.005 秒。压力档仍保留全部 77 指标、1 万原组和 1 万独立未知条件任务；八张原始表前后逐行哈希相同。完整审计仍约 313/344 MB，导出约 15.61/17.37 秒，真实文件离线重建与完整读取精确相等。**读取达标不代表冷生成达标**；真实页面时钟与服务时钟另列，均不代表普通硬件。

最终 r3 个人报告已完成真实冷生成与 30 次热生成，以及[独立进程冷重开和 30 次热重开](../artifacts/followup_20261127/performance/final-browser-history-personal-r1/reopen.json)。31 次重开逐次核对完整报告 ID 与实际图点，末份下载正文与所选冻结版本逐字相等；原有 31 份报告没有新增或改写。点击“打开”后的冷可交互 1.477 秒、热 P95 0.607 秒达读取目标；但选择准备的热 P95 为 2.647 秒，30 个热样本都曾首次菜单操作失败、第二次恢复。**这不等于整个历史选择流程在 1 秒内完成**，首次展开稳定性仍待解决；所有准备失败、重试与耗时保留。手机/桌面[人工看图回执](../artifacts/followup_20261127/validation/visual-review-r3.json)区分实际可见内容和仅有 DOM 状态的截图。

最终 r3 的[10 万](../artifacts/followup_20261127/performance/final-browser-generation-100k-r2/summary.json)与[100 万浏览器报告生成](../artifacts/followup_20261127/performance/final-browser-generation-1m-r1/summary.json)分别等待 600 秒后超时，完整样本和保存报告均为 0；失败截图仍显示正确预览，任务停在“分析本期实际问题与行动”。两条路径均未取得热生成与历史重开样本，不能用 r2 后端结果替代；最终 UI 额外延迟尚未定位。更早批处理收到未知来源 SIGTERM 的中断另存，与这两次真实等待超时区分。三档详情/预览的[独立冷与 30 次热返回汇总](../artifacts/followup_20261127/performance/final-browser-page-summary-r5.json)完整：热事实与趋势均达标，冷详情及两压力档冷预览仍超预算。

T01–T03 对应日历及完整训练回执；T04–T07 对应主题与原联合分析回归；T08–T12 对应行动专项/真实页面与冻结兼容；T13–T16 对应知识专项/真实语料端到端；T17–T19 对应双来源页面、时区专项与手机截图；T20 对应按需读取/离线重建；T21 对应缓存、权限、源与知识修订、撤销及并发清空。T23 对应 [W6 中性方向、来源/协议分组和无参考普通训练](../tests/science/test_repair_association_training.py)及[实际背景与事实绑定](../tests/science/test_question_context.py)回归。**T22 两压力档冷生成未达标**；最终浏览器回执单列，其余软件/页面证据不替代人体有效性或专家审定。

## 提交前验证与失败保留

首批发布源码文件哈希见 [source-publish.json](../artifacts/followup_20261127/validation/source-publish.json)，本轮最终快照见 [completion-source-r3.json](../artifacts/followup_20261127/validation/completion-source-r3.json)。测试和页面各自保存开始/结束源码身份；较早阶段回执不冒充最后源码验证。全量回归与末次影响范围分别记录，不将有重叠的专项数相加。

四个隔离进程完整执行发现的 **2421 项 / 173 文件**，快照结果为 **2419 通过、2 失败**，零错误/跳过；原回执保留于 [final-complete](../artifacts/followup_20261127/validation/final-complete/results.json)。两项失败均为原测试要求 caption 含原始 ISO，与本轮自然日期/当前时区展示要求冲突；保留全部训练计划分母、完成/跳过/未知和来源断言，改为核对精确日历起点、结束时刻、UTC 与半开边界，相关整文件及夏令时专项 [8 项通过](../artifacts/followup_20261127/validation/period-ui-final.txt)。最后 W4 判定修正发生在全量快照之后，其问题、行动、冻结读取与报告影响范围 [135 项通过](../artifacts/followup_20261127/validation/topic-goal-final-r2.txt)。这是“完整快照回归＋末次影响范围补验”，没有把旧快照说成所有最终文件从头重跑通过。

产品范围 [Ruff](../artifacts/followup_20261127/validation/ruff-publish-final.txt)、[Node 日历结构检查](../artifacts/followup_20261127/validation/calendar-node-final.txt) 和源码差异空白检查通过。原始失败日志/XML的尾随空白保持原字节，不为 `git diff --check` 改写历史证据。

第一次全量发现 7 项失败后中断排查：高级页完整报告变量/读取契约错误，以及当天体重只剩“完整日暂无”。已修实现并保留原数值、来源、训练和历史断言；两文件专项 28 项重新通过。误用系统旧 Streamlit 的中间复跑单独保留，不算产品回归结论。页面早期等待旧 DOM、周期否定句断言和历史折叠问题的失败截图/日志全部保留。

Ruff 产品范围为 `src tests tools app.py`；首批发布时根目录 `ruff check .` 另报 37 个旧执行包/历史证据片段问题，其原始日志保留，未修改历史快照来美化结果。

后续完整快照回归见 [completion-full](../artifacts/followup_20261127/validation/completion-full/results.json)：2441 项/177 文件全部通过，零失败、错误、跳过，逐例身份无缺漏/重复。产品与测试源码稳定；期间仅浏览器性能工具修改，原汇总如实保留 `needs_review`，工具需另行真实验证。随后发现的空目标下一步问题有[修前失败](../artifacts/followup_20261127/workflow-compute/goal-step-before.txt)，末次影响范围与页面补验单列，不用完整快照替代后改文件验证。

末次报告补修：无实际目标/行动时，W4 指向已有体重/RHR 的来源、日期与条件核对，报告优先真实设备事件；[71 项影响范围](../artifacts/followup_20261127/workflow-compute/goal-step-after-r2.txt)及[真实报告补验](../artifacts/followup_20261127/pages/no-goal-report-final/browser.json)通过，下载/冻结/审计一致。同一分钟生成的历史报告原来显示相同标签，真实点击曾打开错误版本；现在加入可区分的稳定版本标识，短标识冲突会延长。固定创建时钟的测试又发现重复生成 ID 冲突，现每次明确生成保存独立请求身份，新签名有版本，旧报告不改写。[末次 58 项报告/行动/界面专项](../artifacts/followup_20261127/workflow-compute/history-versions-r2.txt)通过，含同一时刻生成、逐份实际选择及冻结 ID 核对；原失败保留，不与其他专项相加。

最终再收窄 W4 两个边界：只有训练时明确指向训练历史；旧行动缺结果定义或观察单位未区分时，分别保留旧反馈并指向新的明确行动，不再假定已有冻结标准。[67 项影响范围](../artifacts/followup_20261127/validation/w4-next-steps-final/receipt.json)及[报告版本/读取 43 项](../artifacts/followup_20261127/workflow-compute/report-presentation-version-final.txt)通过，均不与上述重叠结果相加。独立 `question-guidance-1.1` 区分步骤版本和缓存，科学 `body-questions-1.5` 不变，已有定义行动仍保持方法相符；新报告标为 `joint-period-report-3.0.1`，历史不迁写。最终受验源文件见 [completion-source-r2](../artifacts/followup_20261127/validation/completion-source-r2.json)。

真实个人报告截图最后还发现 W2 无条件声称存在“已经填写的疲劳”，但该合成库没有主观记录。现按实际可见的训练、睡眠、疲劳分别生成下一步，缺失时使用可选记录/导入核对；已有疲劳（包括 0）不会再次被当成缺失，未来、窗外或截止后才可见的记录不冒充已填写。指导身份升为 `question-guidance-1.2`，科学身份不变；完整报告缓存也跟随问题算法和指导身份失效，旧冻结正文不改。[10 项修前失败及 77 项修后影响范围](../artifacts/followup_20261127/validation/w2-next-steps-final/receipt.json)保留；77 项包含此前 67 项，不累加。最后仅调整导入格式后再核对两个报告缓存用例；[合并验证范围说明](../artifacts/followup_20261127/validation/completion-regression-receipt-r3.json)与[最终 Ruff](../artifacts/followup_20261127/validation/ruff-publication-r3.txt)分别记录。[发布前源码核对](../artifacts/followup_20261127/validation/publication-source-and-lint-r3.json)确认产品、测试及配置与 r3 冻结快照一致，只有两个浏览器驱动按真实失败修正；其实际成功/失败路径另有回执。r2 后端时钟早于这次补修，最终页面时钟另列。

尚待完成的工作：继续降低压力档必要冷计算成本与重复工作流存储；解决历史菜单首次展开/选择的稳定性；扩展设备特异内容与独立专业审核。实体手机、Safari、软键盘、普通硬件、人体行动效果及目标远程模型没有本轮验证结论。实际公共库安装和 HRV 默认漏召回已解决，不再列为待办。
