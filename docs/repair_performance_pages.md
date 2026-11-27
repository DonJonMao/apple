# 2026-11-27 页面性能与训练流程验收

本轮所有健康记录、训练操作和截图均来自合成数据库。原 10 万/100 万压力数据库只以 SQLite backup 读取，未改时间分布、未知条件或组数；确切规模仍为 100001/1000001 条健康记录、各 10000 个训练组。原历史结果保留，本文件只引用本轮工件。

## 计时身份和环境

原压力库的全部训练组发生在 2026-11-20。直接用本轮今天的日历周会排除这些组，改变验收负载。因此通过临时启动 wrapper 固定**分析请求时钟**为原 preview 回执中的截止：100k 为 `2026-11-22T10:07:49.556032+00:00`，1m 为 `2026-11-22T10:09:40.013597+00:00`；数据时间不改。原 fixture 的 365 日健康分布和同日 10000 组仍完整参与相应范围。

同机 HTTP/Streamlit WebSocket，Chromium 158，Python 3.11，aarch64 Kunpeng-920，宿主可见 192 CPU、约 2 TB RAM。共享机器不是普通个人电脑或实体手机性能；未清 OS 文件缓存。正式页面计时与 root 报告 cProfile 分开执行，各回执附开始/结束 host load 和进程树资源采样。

每次浏览器计时先等待新的、尚未出现过的 `data-hz-render` 且 workspace 正确，再等待真实指标值及非空 Plotly 数据。结束后使用相同截止的正常本地分析逐项核对卡片与全部已显示图点；旧 DOM 不能成为成功样本。点击计时从 DOM 实际 click 捕获开始；Playwright 发命令至完成另外保存，不混为同一种指标。

首进程启动至服务 ready、服务 ready 后第一次打开、运行中首次新范围、30 次热返回分列。单次冷结果不叫 P95。每个冷范围均核对卡片和真实趋势，热返回保留30个原始样本；不以后台函数耗时代替浏览器目标，也未额外运行30次后台清缓存诊断。两档复盘范围都保留10000个已完成源组。

## 已取得结果

| 场景 | 100001健康＋10000组 | 1000001健康＋10000组 | 口径 |
|---|---:|---:|---|
| 运行中冷复盘周首批事实 | 4.603 秒 | 4.776 秒 | 两档均未达 ≤3秒 |
| 运行中冷复盘月首批事实 | 5.085 秒 | 5.902 秒 | 两档均未达 ≤3秒 |
| 复盘30次热事实＋趋势 P95 | 0.211 秒 | 0.386 秒 | 新render及真实值均核对 |
| 运行中冷健康详情周事实＋趋势 | 0.787 秒 | 1.358 秒 | 后台与浏览器分别记录 |
| 运行中冷健康详情月事实＋趋势 | 0.967 秒 | 2.601 秒 | 同上 |
| 健康详情30次热事实＋趋势 P95 | 0.858 秒 | 0.951 秒 | 两档达 ≤1秒，旧内部800ms目标均未达 |

完整原始样本位于 `artifacts/repair_20261127/performance/preview-100k.json`、`preview-1m.json`、`detail-100k.json` 及相应 `*-resources.json`。preview 原始数据包含每次离开/返回的不同 render ID、卡片、实际趋势数组、选择范围与独立验证结果；没有生成任何完整报告。

回执保存计时当时的源码SHA-256。计时后 `ui/review_page.py` 的报告历史/报告明细分支有后续修复；本次测量经过的无报告 `_preview` 首批事实路径及 `workspace_summary` 没有因此改变。不能据此声称该文件最终全文与计时回执同hash；最终报告分支由报告与页面专项另行验收。

后续真实窄屏验收还为数值和变化标签增加了换行CSS。该修复由最终几何验收覆盖；本节不冒称CSS修改后重新计时，亦不将阶段源码清单等同最终全仓身份。

复盘资源峰值为100k约1769.6MiB、1m约1847.6MiB，这是被测命令、真实应用和Chromium等活跃子进程的RSS总和采样峰值，不是单独数据库引擎内存，也不能代替报告内存。监测约0.1秒一次，短暂峰值可能遗漏。

健康详情对应进程树峰值约1602.1/1685.9MiB。新进程服务ready后的首次健康详情事实与趋势为4.169/6.671秒，另外的服务启动阶段为2.362/2.373秒；两者不混入运行中冷范围，也不称P95。复盘启动及首次打开的分阶段原始值同样保留在回执及汇总中。

优化来自按所选周期准备事实，以及训练事件最小字段投影。前后仍使用真实 as-of、修订、删除与冲突语义；没有把当前表count当历史，也没有减少10000个未知条件组。冷复盘仍未达预算，热返回通过不能替代冷路径通过。

## 训练真实交互

`tests/training/product_redesign_training_browser.py` 本轮完整完成17项：直接开始、选动作立即返回、32.5×8和RIR=0、再次添加、取消、刷新草稿恢复、延迟回执仍保留焦点和新输入、无效次数局部报错、复制仍是草稿、丢回执原请求幂等重试、真实修订冲突、结束后未完成草稿不算实际、动作历史和长训练。七种状态分别检查320/375/390/430/768/1440 iframe布局。

最终页面验收 [delivery-fixed-r3/browser.json](../artifacts/repair_20261127/pages/delivery-fixed-r3/browser.json) 的 `training-home-main` 和 `training-input-main` 另核对这六种宽度的主document与stMain，全部无横向溢出；32.5×8、RIR=0在连续改宽后保留。该轮源码前后身份一致；已目视核对同目录 `training-input-main-390.png`，输入值、0与本机待同步状态完整可见。主页面几何、组件内部几何、实际交互与截图各有独立回执。

`tests/training/master_training_browser.py` 本轮继续验证离开后恢复同一训练、显式丢弃未完成草稿而保留实际、历史8→9更正、删除/撤销计数1→0→1，以及真实关闭WebSocket并离线输入后重新连接恢复8次并保存。

普通夹具30次选动作返回 P50 **498.1ms**、P95 **619.3ms**，包含点击到真实持久回执与可编辑视图。该训练轮与 root 报告 cProfile 有并发，记录为共享负载成绩；不冒称独占性能或触摸键盘延迟。完整原始数组和视频见 `training/full-flow/training-browser-results.json`；历史/断网回执见 `training/history-offline/captures.json`。

原 `product_redesign_training_search.py` 另做30次当前查询输入→真实结果下一动画帧测量，含既有防抖，P50 **184.6ms**、P95 **187.5ms**。每次结果与正常 `TrainingService.search_catalog` 精确相同，用户别名、收藏移除及初始加载状态通过，搜索没有产生组件网络命令。原始数组见 `training/training-search-results.json`，进程树资源见 `training/training-search-resources.json`；该轮暂停报告计时，未与最终页面浏览器并发，仍为共享宿主结果。

既定边界脚本另保留40次输入事件→本机草稿状态→下一动画帧的原始数组，P50/P95均约 **16.7ms**，无组件网络命令，满足原脚本 `<100ms` 检查；不等于物理按键或软键盘延迟。自重、助力0、时长、距离、真实组序、待回执刷新、删除撤销、双页签真实冲突和结束保留非法本机草稿均已通过。回执见 `training/edges/training-edge-results.json`。

该边界脚本首次执行在跨工作区的最后一项失败：旧脚本进入“设置”后直接查找“SQLite 路径”，没有选择当前的“导入与同步”分区。该次退出1及前7项实际成功完整保留于 `validation/training-edges.log`、`training/edges-resources.json` 和上述部分回执；不能将首次整轮称为全通过。修复限于验收脚本的真实导航和追加原始输入数组，不更改产品设置行为。

随后仅补跑跨工作区场景，未重测前7项或替换其输入计时。两次脚本导航失败（点击被装饰层遮挡、使用旧入口名“力量”）及日志继续保留；最终以可见“导入与同步”标签及当前“训练”一级入口真实点击，`training/edges-workspace-r3/training-edge-results.json` 为 `completed=true`：新库没有原本机草稿，切回恢复未同步的 `7x`，原训练仍为已完成。各轮身份及失败原因见 `training/search-input-measurement.json`。

已目视核对本轮 `training-active-mobile.png` 与 `corrected-history.png`：输入32.5、次数8/历史更正9、RIR=0、草稿/完成状态实际可见。截图不替代点击、数据库核对和断网回执。

## 工具、失败保留与未验证

新工具 `tools/repair_preview_benchmark.py`、`repair_page_benchmark.py` 复用原基准测量流程，只适配当前UI/按需period、固定原分析截止和增强实际结果核对；原工具和历史工件未覆盖。`repair_measure_run.py` 记录进程树RSS/CPU及共享host load。

第一组连续批处理在两档preview成功后、detail启动时收到退出143，没有报成功；未知终止原因与恢复步骤保存在 `page-sequence-interruption.json`。随后每档独立运行，原preflight和首版资源监测回执保留。资源监测从扫描全宿主进程改为仅扫描被测子进程树，降低监测本身开销；100k健康详情正式重跑，首轮保存在 `detail-100k-first-monitor*`。

尚无实体iPhone/Safari/软键盘、真实移动网络或普通设备结果；本地页面性能不包含外部模型时间，也不等同完整报告或审计导出性能。完整报告由 root 单独计时，不能拿本节预览成绩替代。

## 两年个人使用样例

另建 `/tmp/healthzip-repair-personal/synthetic-two-year.sqlite3`，由 `tools/repair_personal_fixture.py` 生成；与原压力库分开。730天、11680条健康记录（每日RHR/SDNN/睡眠及13次普通心率）、209场/1672组，周二和周五各2动作×4工作组，覆盖24个月以上的真实日期分布。每11场保留ROM未知，每5场RIR为空，其余末组RIR=0，无预指定参考；详见 `personal-fixture.json`。

该样例真实健康详情周/月冷事实与趋势为0.718/0.787秒，30次热返回P95为0.672秒；每个卡片及Plotly数组与相同截止的后端结果精确核对，见 `detail-personal.json`。它说明这种分布下的本机日常体验，不能替代原10万/百万压力目标。完整个人报告另由root记录。

全部浏览器阶段、明确预算结果及进程树内存汇总见 [page-performance-summary.json](../artifacts/repair_20261127/performance/page-performance-summary.json)。
