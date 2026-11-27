# 附件 R01–R07 修复交付

在 `feat/healthzip-product-redesign` 的实际代码上继续，未回退审查提交 `00a35d2`。本次从已发布 `c71358d` 续修；[上一版交付原文](followup_delivery_through_c71358d.md)、更早失败及历史结果完整保留。前一附件 F01–F09 的逐项证据见[前轮交付](repair_delivery.md)。

原始数据、用户修改、旧行动/冻结报告和五份未跟踪 PDF 保留。本轮只用隔离合成库验收，未调用外部健康模型，未修改真实健康库或既有公共资料。数据库、备份、PDF、私人记录及含文献原文的完整审计包不发布到 GitHub。

## 逐项结果

| 项目 | 状态 | 实际行为与证据 |
|---|---|---|
| R01 训练日历 | 已修复 | 日期具有稳定独立身份，点击实际日期打开对应训练；28/29/30/31 天、跨月、返回、刷新及完整训练输入通过，RIR=0 保留。[日历与训练](followup_calendar.md) |
| R02 主题判定 | 已修复 | 仅疲劳保留主观摘要，不虚构步态、周期或通知任务；仅步数可描述活动量，真实设备事件及周期三状态独立处理。[主题实页](../artifacts/followup_20261127/pages/topics-final/browser.json)、[空目标补验](../artifacts/followup_20261127/pages/topics-empty-goal-final/browser.json) |
| R03 行动观察单位 | 已修复 | 低频估计保留发布点、支持窗、重叠/重复、版本/上限和执行关系；当天可见值继续显示，不冒称独立行动后测量。旧定义和固定随访窗口不改写。[行动证据](followup_actions.md) |
| R04 行动依据和当前状态 | 已修复 | 排第三的适用行动依据进入正文；冲突及依赖、撤销、服务故障分别显示，独立说明保留，旧正文不变。[知识端到端](followup_knowledge.md)、[冲突反例](../artifacts/followup_20261127/knowledge-conflict-budget-review/receipt.json) |
| R05 六问内容 | 部分完成 | 核心说明继续可用；普通训练直接 RIR 已接通定义及方法限制，页面/报告绑定同一事实。未知条件不变成可比条件；缺失、区间或换算 RIR 不绕过用途边界。个人精度、部分目标设备协议等仍有缺口。[W1 接线](followup_w1_rir_context.md)、[六问](followup_knowledge_six_questions.md)、[剩余缺口](followup_knowledge_content_gaps.md) |
| R06 报告性能 | 部分完成 | 普通打开读取小型冻结对象，细节按需读取、审计独立导出，显式再生成有独立 ID。本次按批复用冻结 scope；1 万组阶段中位 2.398→1.310 秒，对象字节/ID/顺序相等。**压力冷报告仍超 15 秒。** [续修与边界](followup_cold_paths_r11.md)、[完整实测](../artifacts/followup_20261127/performance/continuation-performance-r11.md) |
| R07 阅读与页面 | 部分完成 | 一条报告阅读路径，来源/协议、单位和时区明确，下载对应所选冻结正文；本次详情按需加载 Express，实际趋势与表格保留。六宽度及历史交互证据保留；实体手机/Safari/软键盘未验证。[协议阅读](followup_stream_labels.md)、[历史交互](followup_history_interaction.md)、[续修实页](followup_cold_paths_r11.md) |

## 最终源码与验证

[r11 清单](../artifacts/followup_20261127/validation/continuation-source-r11.json)固定 549 个源码、测试、资源、工具和配置文件，仅两个产品文件及其两个测试相对 c71358d 改变。指标算法、知识用途、工作流哈希和报告格式不变。完整回归为 **2,591/2,591 通过**，186 个文件，失败/错误/跳过均为 0；[结果与源码核对](../artifacts/followup_20261127/validation/continuation-full-r11/results.json)保持一致。[产品 Ruff](../artifacts/followup_20261127/validation/continuation-product-ruff-r11.txt)覆盖 `src tests tools app.py` 通过；诊断驱动另有 3 项导入样式提示，原输出保留，不将其称为全目录 lint 通过。专项和全量有重叠，不累加。

受影响路径按固定源码顺序复测：原两年个人、10 万/100 万健康记录加 1 万训练组的后端生成/重开/审计，三档真实心率详情，以及 100k 真实浏览器报告生成/下载/重开。热访问均 30 次，冷测为单次。原始表、77 指标、独立未知条件任务、冻结结果及离线重建逐项核对。具体值、预算失败、输出大小、内存和源清单见 [r11 性能汇总](../artifacts/followup_20261127/performance/continuation-performance-r11.md)。

本轮未重测的冷预览及另外两档报告浏览器保留 [r10 原测量](../artifacts/followup_20261127/performance/continuation-performance-r10-v2.md)，不冒充 r11。此前 r10 的 2,576 项回归、W1 页面和三档十二任务有其原源码身份，见[上一版原文](followup_delivery_through_c71358d.md)。

## 未完成与运行状态

- 压力完整冷报告仍为 117.9/156.9 秒，远超 15 秒。个人和 10 万档运行中冷详情本次达到 3 秒目标；百万档冷月 4.188 秒、热事实＋趋势 P95 1.000100 秒仍失败，未舍入成达标。冷预览继续保留 r10 的失败结果。部分进一步重复计算已有只读线索，尚未纳入本轮固定代码或宣称收益。
- 部分呼吸率、腕温和设备通知的精确协议/算法与个人变化效度未补齐；个人 RIR/e1RM 精度、精确处方及 W4 新资料用途仍有限制。已有事实和适用局部说明继续可用。
- 未做独立专家审定、人体行动有效性、实体 iPhone/Safari/软键盘、普通硬件或目标远程模型验收。AI 内容/截图核对、模拟、软件与 Chromium 验证不替代这些结论。

宿主为共享 aarch64 Kunpeng、192 个逻辑 CPU、约 2 TiB RAM；其他宿主负载不可控，OS 缓存保留。现有 8501 服务（11 月 21 日启动、文件监听关闭）未重启，尚未加载这些代码。**GitHub 提交不是部署。** 验证均使用隔离实例。

逐场景 T01–T23 的原证据映射见[早期逐项对照](followup_delivery_through_64cdd53.md)，本次新增内容、失败试验和实际验收范围见[冷路径续修](followup_cold_paths_r11.md)。

发布文件范围、排除项和哈希见[本次发布检查](../artifacts/followup_20261127/validation/continuation-publication-scan-r11.json)。
