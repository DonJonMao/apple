# 附件 R01–R07 修复交付

从 `feat/healthzip-product-redesign` 的实际代码继续，未回退 `00a35d2`。上一批提交为 `6f7d9c3`；其完整交付及失败记录保留在[历史交付](followup_delivery_through_6f7d9c3.md)。本页对应后续附件；前一附件 F01–F09 的行为与证据见[前轮交付](repair_delivery.md)。

原始健康数据、历史行动/报告、用户修改和五份未跟踪 PDF 保留。健康验证只用隔离合成库，未调用外部模型。公共资料先独立备份再追加；原有 28 表、920,396 行逐行核对不变，权限和原审核保留。数据库、备份、私人记录及受限文献原件不进入 GitHub。

## 逐项结果

| 项目 | 状态 | 用户可见行为与核验证据 |
|---|---|---|
| R01 日历 | 已修复 | 每个日期有独立稳定身份，三个实际训练日期能打开对应训练。28/29/30/31 天、跨月、返回、刷新和完整训练输入通过；RIR=0 保留。[日历证据](followup_calendar.md) |
| R02 主题判定 | 已修复 | 只有疲劳保留主观摘要，不再虚构步态、周期和通知任务；仅步数仍可描述活动量；真实通知与周期三状态分别处理。问题、行动、报告、导出共享判定。[真实场景](../artifacts/followup_20261127/pages/topics-final/browser.json)、[空目标补验](../artifacts/followup_20261127/pages/topics-empty-goal-final/browser.json) |
| R03 行动观察单位 | 已修复 | 低频估计保留发布点、支持窗、重叠、重复、版本/上限与实际执行关系；当天已可见值仍展示，不冒称独立的行动后测量。旧定义和固定随访窗口不改写。[行动证据](followup_actions.md) |
| R04 行动依据及当前状态 | 已修复 | 第三位行动依据进入正文；冲突、前提冲突、撤销及服务故障分别处理。新增饱和冲突反例修复，争议组不再挤掉完整独立说明；旧报告正文保持不变。[既有端到端](followup_knowledge.md)、[新增冲突回归](../artifacts/followup_20261127/knowledge-conflict-budget-review/receipt.json) |
| R05 六问内容 | 部分完成 | 核心六问与原行动继续可用；补通 HRV 片段缺口、力量群体模型与个人换算区别，以及血氧/步数/呼吸率/腕温的精确研究范围。实际公共库已追加，14 主题有/无数据页面及报告通过，另实际点击历史打开/下载/返回；仍有设备/个体效度与具体协议缺口。[六问](followup_knowledge_six_questions.md)、[本轮内容与剩余缺口](followup_knowledge_content_gaps.md) |
| R06 报告性能 | 部分完成 | 普通打开只读取小型冻结阅读对象；单题/轨迹按需恢复，审计另行导出。新工作流共享不可变训练对象，旧内联格式仍可读；同条件重生成保留独立报告 ID。已修复页面进度刷新反复强制 GC 导致的额外停滞。最终三档测量见下文；15 秒冷生成不能由热读或后台启动代替。[GC 对照](followup_report_gc.md)、[存储与离线还原](followup_workflow_storage_plan.md) |
| R07 阅读与页面 | 部分完成 | 生成后只有一条报告阅读路径；同来源/设备的不同协议在摘要与趋势菜单中可辨认，未知条件保留。W5/W6 缺记录时显示具体核对步骤。手机有完整主要发现，下载对应所选冻结正文；真实旧报告导航可区分协议，旧行及 36 个对象字节不变。六种宽度已检查，实体手机、Safari 与软键盘未验证。[协议与实页证据](followup_stream_labels.md)、[历史交互](followup_history_interaction.md) |

## 最终验证身份与性能

全量回归与完整性能测量使用 [source-r5](../artifacts/followup_20261127/validation/completion-source-r5.json)，基于 `6f7d9c3` 的 539 个 Git 选择文件。忽略的构建元数据与用户 PDF 不作为产品源码。报告缓存现同时依赖检索算法和回答要求版本；[26 项专项](../artifacts/followup_20261127/validation/evidence-method-cache/receipt.json)证明版本改变重算、相同版本复用、旧原始冻结字节不变。全量与各后续工具验证分开记载，不累加重叠专项。

[最终全量回归](../artifacts/followup_20261127/validation/completion-full-r5/results.json)：2,506/2,506 项、181 文件通过，零失败、错误或跳过。产品、测试、入口、配置和依赖文件开始/结束均与 r5 相同，见[来源核对](../artifacts/followup_20261127/validation/completion-full-r5/r5-provenance.json)。运行期间仅知识浏览器驱动继续修正，原工具汇总因此为 `needs_review`/exit 1，未改写为全源稳定；该驱动另以真实页面验收。既有 `record_property` 与 JUnit xunit2 提示保留。

[知识真实页面](../artifacts/followup_20261127/knowledge-content-gaps/live-browser-r6/browser.json)完成 14 主题×有/无数据与报告检查，零页面错误；随后 [r7 补验](../artifacts/followup_20261127/knowledge-content-gaps/live-history-r7/browser.json)实际点击历史打开、下载及返回，不能与此前 Repository 重开混称。驱动修前失败均保留；该轮产品/tests/config 与 r5 相等，驱动单独保存 hash。

后续空状态与协议显示补修的[末次影响范围](../artifacts/followup_20261127/knowledge-content-gaps/empty-state-and-stream-after-r4.json)为 75 项通过；[全局 Ruff](../artifacts/followup_20261127/knowledge-content-gaps/global-ruff-final-r3.json)通过。实页 [r9](../artifacts/followup_20261127/knowledge-content-gaps/live-empty-r9/browser.json)核对 W5/W6 说明及下一步；[r11](../artifacts/followup_20261127/knowledge-content-gaps/stream-labels-r11/browser.json)覆盖 320/375/390/430/768/1440、实际切换图值及新旧冻结下载；[r12](../artifacts/followup_20261127/knowledge-content-gaps/stream-legacy-menu-r12/browser.json)补齐实际展开的旧报告菜单。截图经 AI 直接目视，390 页顶与滚动到首条发现的视口分别留图，未把滚动截图冒充页顶。最终源码清单另见 [publication-r7](../artifacts/followup_20261127/validation/completion-source-publication-r7.json)，r6 保留为中间身份。

三档完整测量已结束，见[原始样本与阶段汇总](../artifacts/followup_20261127/performance/completion-performance-r5.md)。三档报告浏览器均使用修正后的完成判定：新冻结身份、真实图点、旧渲染节点清除且可交互；保留首次压力页面驱动失败及个人旧判定样本。

| 原夹具 | 后端冷生成 | 页面冷生成 / 30 热 P95 | 页面冷重开 / 30 热 P95 |
|---|---:|---:|---:|
| 两年个人 | 10.37 s | 12.51 / 1.58 s | 1.43 / 0.49 s |
| 10 万＋1 万训练组 | 119.11 s | 126.36 / 1.45 s | 1.40 / 0.46 s |
| 100 万＋1 万训练组 | 172.93 s | 181.35 / 1.58 s | 1.40 / 0.56 s |

压力冷报告仍远超 15 秒。三档运行中冷详情为 3.09–5.05 秒，压力冷预览首事实为 4.52–6.50 秒，均未达 3 秒；各档热详情/预览 P95 达标。菜单准备另计，各档 31 次首试选择成功，不能把点击“打开”后的耗时称为整个导航时间。

两压力档审计为 264/295 MB，导出 13.52/13.78 秒；全部 77 指标、1 万原组与独立未知任务保留，八张原始表哈希不变。实际导出文件逐报告、逐工作流重建均相等。训练工作流共享后的 UTF-8 冻结负载净减少各 50.08 MB（已扣唯一引用对象）；生成峰值约 2.0/2.4 GiB。正文、审计、内存与存储净节省分别计量，不互相替代。

后续问题空状态与协议碰撞显示补修使用新报告呈现版本 3.0.2，科学计算不变；它们的末次影响范围与实际页面验收单列，不能把 r5 的精确计时改称 3.0.2 样本。此前 600 秒失败和所有旧成绩保留。

共享宿主为 aarch64 Kunpeng；重性能任务顺序运行，外部宿主负载不受控，OS 缓存保留。服务启动、首次页面、运行中冷范围、完整冷/热生成、冻结重开和审计各自计时；无目标远程模型或普通设备结论。

## T01–T23 对照

| 场景 | 实际证据 |
|---|---|
| T01–T03 月份、实际日期、完整训练 | [日历及训练完整流程](followup_calendar.md) |
| T04–T07 疲劳、部分主题、事件/周期、共同日期 | [真实主题页面](../artifacts/followup_20261127/pages/topics-final/browser.json)、[主题专项](../tests/integration/test_followup_topic_applicability.py) |
| T08–T12 支持窗、重复/上限、执行、旧行动和冻结 | [行动专项与实际页面](followup_actions.md) |
| T13–T16 排位、局部冲突、当前状态及缺证据 | [端到端知识证据](followup_knowledge.md)、[饱和冲突补验](../artifacts/followup_20261127/knowledge-conflict-budget-review/receipt.json)、[六问内容](followup_knowledge_content_gaps.md) |
| T17–T19 来源、时区、手机阅读 | [双来源页面](../artifacts/followup_20261127/pages/topics-final/browser.json)、[同来源协议区分及六宽度实页](followup_stream_labels.md)、[时区/偏移专项](../tests/unit/test_report_timestamp.py)、[历史选择](followup_history_interaction.md) |
| T20 小型读取、单题、离线审计 | [冻结读取专项](../tests/integration/test_followup_report_reading.py)、[工作流存储与实际文件重建](followup_workflow_storage_plan.md) |
| T21 修订、权限、关系和并发失效 | [既有缓存/撤销证据](followup_delivery_through_6f7d9c3.md)、[算法版本失效补验](../artifacts/followup_20261127/validation/evidence-method-cache/receipt.json) |
| T22 三档性能 | 部分未达标；最终原始样本、内存、体积和完整性另列，保留失败。 |
| T23 既有分析主路径 | [W6 中性关联/来源分组/普通训练](../tests/science/test_repair_association_training.py)、[实际背景与事实绑定](../tests/science/test_question_context.py)、本轮全量回归。 |

## 未完成范围

- 压力完整冷报告仍需 119/173 秒后端、126/181 秒页面，未达 15 秒；冷详情与压力冷预览亦未达 3 秒。阶段回执显示本期事实、训练/知识工作流、历史周期和冻结整理仍有显著冷计算成本；现有共享与 GC 修复未使其达到预算。3.0.2 后续显示补修的精确压力计时未重新测量。
- 呼吸率、腕温、部分通知的目标设备/算法协议与个人变化效度尚未补齐；力量个人 e1RM 误差和 W1 直接 RIR 上下文未接通。已有事实和有依据的局部说明继续可用，具体替代内容见 R05。
- 未做独立专家审定、人体行动有效性、实体 iPhone/Safari/软键盘、普通硬件或目标远程模型验收。AI 辅助内容核对、模拟与软件通过不替代这些结论。

现有 8501 服务（11 月 21 日启动、关闭文件监听）未被本轮重启。真实页面验证使用隔离实例；现有服务需要正常重启后才会加载新代码与 `postScriptGC=false`，本轮不把隔离验收称为线上部署。

全部修前失败、测试夹具/驱动失败及重跑证据保留，原始日志/XML不因空白检查被改写。

[知识发布扫描](../artifacts/followup_20261127/knowledge-content-gaps/publication-scan-final.json)覆盖该范围的 433 文件（含被 Git 忽略的日志），未发现受限 E7 原文段落前缀或非空原始证据载荷；PNG 另依赖合成夹具来源和直接目视。此扫描范围不包含原 PDF、数据库、备份或完整原文审计包，不将零命中解释成所有知识内容均可公开。

[其余新增工件扫描](../artifacts/followup_20261127/validation/publication-other-artifacts-r7.json)另核对 432 件：277 件文本同样零命中，155 件合成截图/性能剖析二进制只核对哈希和来源。三份名为 `audit.json` 的工件仅为导出时间、大小及还原结果回执，不含完整审计内容。
