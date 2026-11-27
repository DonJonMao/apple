# 附件 R01–R07 修复交付

在 `feat/healthzip-product-redesign` 的实际代码上继续，未回退审查提交 `00a35d2`。本次从已发布 `64cdd53` 续修；其[交付原文](followup_delivery_through_64cdd53.md)、更早失败及历史结果保留。前一附件 F01–F09 的逐项实现与证据见[前轮交付](repair_delivery.md)。

现有原始数据、用户修改、历史行动/冻结报告和五份未跟踪 PDF 保留。健康验收只使用隔离合成库，未调用外部模型。本次公共库先备份，再仅新增两条 W1 用途边；28 张保护表、920,586 个旧行逐行一致。数据库、备份、原 PDF、私人记录及含文献原文的完整审计包不发布到 GitHub。

## 逐项结果

| 项目 | 状态 | 实际行为与证据 |
|---|---|---|
| R01 日历 | 已修复 | 每天都有稳定独立身份，点击三个实际日期打开各自训练。28/29/30/31 天、跨月、返回、刷新、添加动作与完整训练输入通过，RIR=0 保留。[日历与训练](followup_calendar.md) |
| R02 主题判定 | 已修复 | 仅疲劳保留主观摘要，不再虚构步态、周期或通知任务；仅步数可描述活动量，真实事件及周期三状态独立处理。[主题实页](../artifacts/followup_20261127/pages/topics-final/browser.json)、[空目标补验](../artifacts/followup_20261127/pages/topics-empty-goal-final/browser.json) |
| R03 行动观察单位 | 已修复 | 低频估计保留发布点、支持窗、重叠/重复、版本/上限及执行关系；当天已可见值继续显示，不冒称独立的行动后测量。旧定义及固定随访窗口不改写。[行动证据](followup_actions.md) |
| R04 行动依据及当前状态 | 已修复 | 排第三的适用行动依据进入正文；局部冲突及其依赖、撤销和服务故障分别显示。争议组不挤掉独立说明，旧正文不变。[知识端到端](followup_knowledge.md)、[冲突反例](../artifacts/followup_20261127/knowledge-conflict-budget-review/receipt.json) |
| R05 六问内容 | 部分完成 | 已有核心解释继续使用；本次补通普通训练直接 RIR 的定义与方法限制，页面/报告绑定同一事实，缺失/区间/RPE 换算不能绕过。未知器械条件不阻断定义，但不变成可比条件。个人精度与部分目标设备协议仍缺证据。[W1 接线](followup_w1_rir_context.md)、[六问内容](followup_knowledge_six_questions.md)、[剩余缺口](followup_knowledge_content_gaps.md) |
| R06 报告性能 | 部分完成 | 普通打开读取小型冻结对象，单题/轨迹按需读取，审计独立导出；再生成保留独立报告 ID。本次减少比较中不用的能量/体重/症状派生、重复复制及解码遍历。压力冷生成仍远超 15 秒，具体实测如下。[存储合同](followup_workflow_storage_plan.md)、[比较优化](../artifacts/followup_20261127/comparison-required-facts/README.md)、[复制边界与诊断](../artifacts/followup_20261127/performance/result-copy-r10/README.md) |
| R07 阅读与页面 | 部分完成 | 生成后只有一条报告阅读路径；来源/协议、统计单位和时区明确，手机首屏有完整发现，下载对应所选冻结正文。六种宽度与真实历史选择通过；实体手机/Safari/软键盘未验证。[协议阅读](followup_stream_labels.md)、[历史交互](followup_history_interaction.md)、[最终目视范围](../artifacts/followup_20261127/validation/continuation-visual-review-r10.json) |

## 最终源码与行为验证

最终候选为 [r10 源码清单](../artifacts/followup_20261127/validation/continuation-source-r10.json)：549 个 Git 选择的源码、测试、资源、工具和配置文件，基于 `64cdd53`。报告呈现版本为 3.0.2，检索为 1.6.0，回答需求为 3；W1 资料上下文独立版本化，科学分析方法仍为 `body-questions-1.5`，不会因此给旧行动误报方法改变。

[全量回归](../artifacts/followup_20261127/validation/continuation-full-r10/results.json)为 **2,576/2,576 项通过**，186 个文件，失败/错误/跳过均为 0；发现数与执行数相同，运行前后源码一致。[产品 Ruff](../artifacts/followup_20261127/validation/continuation-product-ruff-r10.txt)覆盖 `src tests tools app.py`。不限目录的 Ruff 命令另报 636 项历史/诊断脚本样式问题，其[原输出](../artifacts/followup_20261127/validation/continuation-ruff-r10.txt)保留，未改写原始工件来消除这些提示。专项与不同轮次测试有重叠，不累加。

[最终 W1 实页](../artifacts/followup_20261127/knowledge-content-gaps/w1-rir-browser-r5-final-r10/browser.json)实际完成直接/混合两场景、范围切换、生成/下载与冻结重建，共 5 项检查、13 张截图，零页面异常，175 个 Python 产品文件与 r10 一致。入口为 **复盘 → 问题分析 → 同动作完成表现 → 依据与原文**。页面与报告事实 ID 相同，两个完整说明、限制和链接进入冻结结果；RIR=0、缺失及转换保持区别。[多宽度目视](../artifacts/followup_20261127/knowledge-content-gaps/w1-rir-browser-r5-final-r10/visual-r5-final-r10.json)与根代理回执明确区分 AI 目视、真实点击和实体设备验证。

此前 r8 的 2,572 项回归及 119.03 秒压力测量只是中间版本，见[r8 记录](followup_continuation_r8.md)。随后发现通用复制的键/值顺序、memo 别名和对象生命周期边界，修前失败保留。最终仅快速复制纯内建图；遇扩展类型或外部 memo，整根交给标准 deepcopy，兼容反例及最终回归通过。r9 较慢候选未采用，其原代码和样本保留。

## 最终性能：原三档夹具

[完整汇总及原样本](../artifacts/followup_20261127/performance/continuation-performance-r10-v2.md)对应最终 r10，十二项任务顺序完成；新进程、服务就绪、首次周/月范围、热访问、生成、重开与审计分别计时。热测均为 30 次 nearest-rank P95，冷测为单次。浏览器等待新报告/渲染身份、真实数值与图点、旧节点清除及可交互。

| 原夹具 | 后端冷生成 | 页面冷生成 / 热 P95 | 页面冷重开 / 热 P95 |
|---|---:|---:|---:|
| 两年个人 | 10.56 s | 11.97 / 1.45 s | 1.11 / 0.49 s |
| 10 万＋1 万训练组 | 122.12 s | 127.03 / 1.49 s | 1.07 / 0.44 s |
| 100 万＋1 万训练组 | 160.74 s | 165.98 / 1.52 s | 1.10 / 0.63 s |

个人冷报告、三档热生成和重开达标；**两压力档完整冷生成仍未达 15 秒**。运行中冷详情的事实＋趋势为 **3.08–5.17 秒**，压力冷预览首批事实为 **4.64–5.77 秒**，均未达 3 秒；三档热详情/预览 P95 均在 1 秒内。历史菜单准备另计，不能把点击“打开”后的耗时当成整个导航时间。

两压力档审计为 267.89/298.64 MB，导出 12.84/13.88 秒；实际导出文件逐报告及逐工作流离线重建相等。77 指标、原 1 万组、独立未知条件任务及八张原始表哈希保留。生成峰值树 RSS 约 2.00/2.38 GiB，包含 Streamlit/Chromium 的报告浏览器任务峰值约 3.01/3.43 GiB；完整原样本及各阶段内存另列，不将正文、审计、存储或内存大小混称。

25 份源码清单按各自范围核对通过，公共知识权威身份未变。初版汇总将不包含依赖文件的运行时清单误判为不完整；原初版保留，v2 分别核对完整运行时清单与包含依赖的控制器清单。两版使用相同原始样本，14 项预算失败保持，不是修改预算或重写测量。

宿主为共享 aarch64 Kunpeng，192 个逻辑 CPU、约 2 TiB RAM；其他宿主负载不可控，OS 缓存保留。这不是普通设备性能结论，也不能从三对局部复制诊断推算整份报告提速。64cdd53/r5 的精确成绩继续作为历史证据，不改称 r10。

## 未完成与运行状态

- 压力完整冷报告、冷详情及压力冷预览仍未达预算。阶段回执仍显示本期事实、训练/知识工作流、历史周期和冻结整理有显著成本；已有修复不足以达到目标。
- 部分呼吸率、腕温和通知的精确设备/算法协议与个人变化效度未补齐；个人 RIR/e1RM 精度、精确处方及 W4 新资料用途未由本次接线验证。已有事实和适用的局部说明继续可用。
- 未做独立专家审定、人体行动有效性、实体 iPhone/Safari/软键盘、普通硬件或目标远程模型验收。AI 内容核对、模拟、软件和 Chromium 验证不替代这些结论。

现有 8501 服务（11 月 21 日启动，文件监听关闭）未重启，尚未加载本次代码。本轮验证使用隔离实例；GitHub 提交不是线上部署。原始失败、旧冻结结果及测试/驱动重跑记录均保留。

逐场景 T01–T23 的原证据映射见[上一阶段对照](followup_delivery_through_64cdd53.md)，本页追加最终源码、W1 及三档性能。发布范围与文件哈希见[续修发布检查](../artifacts/followup_20261127/validation/continuation-publication-scan-r10-v2.json)。
