# 本轮性能与正确性边界（2026-11-22）

所有规模数据均为合成记录；数据库和公共知识库工作副本位于临时目录，不作为私人数据交付。机器为共享Linux aarch64、192逻辑CPU、约2TB RAM、Python3.11.7，Chromium158.0.8127.18。保留OS文件缓存。基准期间存在并行页面测试、报告诊断或pytest负载；不代表独占机器、普通笔记本或真实手机网络成绩。

## 页面与训练

| 项目 | 100001健康记录＋10000组 | 1000001健康记录＋10000组 | 口径 |
|---|---:|---:|---|
| 训练选动作返回 P50/P95 | 353.2/491.5ms | 391.1/550.7ms | 30次真实点击至持久确认和可编辑页 |
| 训练新进程至首次页 | 3.833s | 3.800s | 各1次，独立于运行中导航 |
| 健康详情热访问 P50/P95 | 0.775/0.842s | 0.829/0.898s | 各30次；新快照事实＋趋势出现 |
| 健康详情新进程 | 4.170s | 6.682s | 不能当作热页成绩 |

页面分阶段和原始样本见 [100k](../artifacts/master_redesign/performance/pages-100000.json)、[1m原始](../artifacts/master_redesign/performance/pages-1000000.json)、[1m优化后](../artifacts/master_redesign/performance/pages-1000000-optimized.json)。百万规模曾有3.078s冷范围超目标，保留原结果；优化后运行中首次周1.429s、月2.871s。当前请求内去重相同来源协议的metadata解析，不跨请求伪造新事实；SQL与剖析见 [detail-profile.txt](../artifacts/master_redesign/performance/detail-profile.txt)。

训练搜索30次P95=187.8ms；本地输入40次P95=16.7ms，后者是input处理到下一帧，不是物理触控延迟。完整交互和未验证手机键盘边界见 [master_training.md](master_training.md)。

## 复盘预览补测

复盘预览另用真实Chromium测量；它没有调用完整报告，不能用上面的健康详情或下面的完整报告成绩替代。两档各用三个独立进程与合成库备份：服务就绪后直接首次打开复盘、先打开设置再首次进入本周、先打开设置再首次进入本月。摘要一次计算周/月及同期对照，所以顺序切换本月不能称为冷计算。仅冷月场景用临时bootstrap预置第一次单选框值，不改产品算法、数据或缓存。每个冷场景仅测1次，不推断冷P95。

本轮最终热测在范围保留修复后重跑。先在真实页面点击“本周”再点击“本月”；第一次访问总览时也实际选本月。随后30次往返均先等新总览完成标识，再从实际点击开始计时等待新复盘完成标识。两页均核对周/月恰有一项选中、本月仍选中、实际卡片等于正常月摘要；并验证每次离开复盘、到达总览、返回复盘三个标识互异，以及30个总览和30个返回复盘标识各自唯一。不能以预置session值或旧DOM推断范围保留。

| 项目 | 100001健康记录＋10000组 | 1000001健康记录＋10000组 |
|---|---:|---:|
| 新进程服务就绪后首次打开：首批事实／事实与趋势 | 6.853/8.222s | 10.318/11.718s |
| 运行中首次本周：首批事实／事实与趋势 | 6.085/7.494s | 9.402/10.845s |
| 运行中首次本月：首批事实／事实与趋势 | 7.189/8.585s | 9.386/10.805s |
| 热返回本月事实与趋势 P50/P95（各30次） | 249.3/266.6ms | 586.9/622.7ms |
| 热返回本月整页可交互 P50/P95（各30次） | 256.4/280.1ms | 593.4/630.1ms |
| 目标结论 | 冷首批事实未达3s；热P95达到800ms | 冷首批事实未达3s；热P95达到800ms |

新进程行从`page.goto`开始，不包含此前服务就绪的2.342/2.349s；运行中样本从实际DOM点击开始。每次先等唯一的新`data-hz-render`完成标记且`workspace=review`，再读取事实、Plotly及交互就绪，排除旧页DOM；这是保守阶段上界。各档实际100场训练、10000组及健康卡片与正常`workspace_summary`结果核对，三个进程的`rendered_values_verified=true`、`full_reports_generated=0`。各30个热样本均为真实点击选择后的本月往返，不能推广为所有周/月切换的完整分布。

最终阶段、样本、源码SHA256、每次往返标识和实际值见 [100k](../artifacts/master_redesign/performance/preview-100k.json)、[1m](../artifacts/master_redesign/performance/preview-1m.json)，逐项预算与导航证据核对见[最终预览汇总](../artifacts/master_redesign/performance/preview-final-summary.json)。原始 [100k历史](../artifacts/master_redesign/performance/preview-100k-before-range-fix.json)、[1m历史](../artifacts/master_redesign/performance/preview-1m-before-range-fix.json) 保留。原测月范围由bootstrap初始化；即使原测显示月值，也不能据此证明用户真实点击选择后的范围生命周期已保持，且不复用其数值作为本轮最终成绩。冷预览≤3秒仍未通过本次验收。

当前环境复跑命令（百万档替换数据库名及输出名）：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tools/master_preview_benchmark.py \
  --database /tmp/healthzip-product-benchmark/synthetic-100000.sqlite3 \
  --output artifacts/master_redesign/performance/preview-100k.json
```

正常10万合成库的单次后端`workspace_summary(总览)`剖析为7.063s，包含cProfile开销，排除备份、Repository打开和浏览器，不能与无剖析页面时间直接计算速度比。时间窗口返回140条健康记录及完整10000组，周/月各保留100场训练、10000组。`history_as_of`累计5.040s，其中`events_as_of`4.798s、10300次事件`_decode`3.871s；33342次JSON `raw_decode`自身3.388s。四周期`_strength_summary`累计0.938s。上述函数嵌套，不能相加。主要开销是训练事件中JSON字段的完整还原及多个周期的日期整理；摘要需保留as-of回放、冲突/删除过滤和来源ID，不能删组或改成当前表计数凑预算。

SQL跟踪记录12次执行：健康查询使用`source_revision_type_window`与`source_revision_record_versions`，训练窗口和场次事件使用`training_event_support`与`training_event_session_versions`；小型候选集合有DISTINCT临时B树。没有证据把主要开销归因于健康全表扫描。完整SQL、EXPLAIN、调用耗时及源码身份见 [剖析回执](../artifacts/master_redesign/performance/preview-100k-profile.json)、[调用栈](../artifacts/master_redesign/performance/preview-100k-profile.txt)。本次仅定位开销，未在最终回归期间改动产品代码。

## 完整本地报告

口径从 `create_report` 调用至返回冻结报告（不计复制合成库、Python启动及Repository打开；首次进程页面在上表单列），包含该模式全部本地事实、知识检索、当前用途核查、训练前背景、前两个完整周期比较、客观建议对照、Markdown和SQLite冻结。没有远程模型调用。每次显式热请求仍新建独立报告版本；浏览预览不计为完整报告。

小型固定夹具的原始cProfile记录为110.475s（含剖析开销，不能直接与无剖析成绩计算速度比）。先前无剖析完整本地报告cold=10.621s，30次hot P50=0.114s/P95=0.140s；批量普通任务初测cold=7.155s、一次hot=0.086s，该一次值不能称P95。[优化前](../artifacts/master_redesign/performance/report-before.json)、[首次30次](../artifacts/master_redesign/performance/report-small.json)、[批量初测](../artifacts/master_redesign/performance/report-small-batched.json)均保留。

原规模夹具的10000组集中在同一当前周，均缺少完整可比条件，因此形成10000个独立未知任务。不得改成已知条件、改时间分布或抽样删组来通过目标。原先145.2s剖析尚未结束首个事实阶段，已有78461次指标evaluate；无剖析中间版本180.047s仍未形成完整报告，停在本期核查阶段，见 [未完成回执](../artifacts/master_redesign/performance/report-100k-before-final-optimizations.json)。这些是明确未达标结果，不能计算其热P95。

本轮针对实际重复做了以下改动：

1. 单报告共用相同时间/选择的事实、源快照及知识工作台。相同瞬间的UTC/+08:00表示统一缓存键；当前W4/W3/W5明确消费同一日历事实，前两个完整周期另算。
2. 完整保留77项全局MetricResult、每个普通任务独立ID/hash/原始组引用。没有预指定参考的任务仅计算所需参考缺失结果，按批次展示实际记录；其他专项预测标记`requested_only`，不伪装已执行。已有参考任务及完整分析入口继续计算原专项指标。
3. 时间可见性、规范化和相同选择只准备一次，复用原evaluate；W2只更换其三项参考基线计算。真实训练开始前的身体背景只读取它消费的身体来源。
4. 客观建议对照按该场训练读取全部as-of事件，避免每个动作重复读取整个10000组窗口；当前私有修订和知识权限在冻结前仍复核。
5. 已核对的报告内容使用有容量边界、同键并发合并和清空代际保护的缓存；每次显式调用另行冻结。临时知识服务失败的内容不进入热缓存。

两档均已完成端到端及30次热调用，原始结果保留如下。该模式当前运行W4普通事实、W2/W3/W5及历史W4，保留77项全局指标和已有来源观测；每次都重新核对输入/知识身份并冻结独立版本。

| 合成规模 | 完整cold（各1次） | hot P50（30次） | hot P95（30次） | 目标结论 |
|---|---:|---:|---:|---|
| 100001健康记录＋10000组 | 113.194s | 2.449s | 2.650s | cold未达15s；hot达到3s |
| 1000001健康记录＋10000组 | 167.684s | 3.260s | 3.394s | cold/hot均未达标 |

[100k完整结果](../artifacts/master_redesign/performance/report-100k-delivery.json)、[1m完整结果](../artifacts/master_redesign/performance/report-1m-delivery.json)各保留77项全局MetricResult、10000个独立task、10000个源组和10000个明确的参考缺失结果。没有把另外18项/任务的未请求专项计算标为已完成。最终JSON约80.7/99.9MB，Markdown UTF-8约97.2/101.1MB；最新cold进程峰值RSS分别1941.6/2341.1MiB。历史与原始事实保留，因此复制/解析/冻结大内容也计时。

小夹具最新完整cold=5.189s，30次hot P50=0.093s/P95=0.110s，见[实测](../artifacts/master_redesign/performance/report-small-final.json)。该成绩不能代表规模夹具。

上表cold使用最后依赖清单复用后的新进程复测：[100k](../artifacts/master_redesign/performance/report-100k-final-cold.json)、[1m](../artifacts/master_redesign/performance/report-1m-final-cold.json)。此前两档完整cold123.049s/175.691s及各30次hot保留在delivery工件；两次测量的period_report源文件SHA256相同，热分支未改变，分段及预算结论见[汇总](../artifacts/master_redesign/performance/report-final-summary.json)。没有将旧的180s或901.872s未完成运行改写为成功；后者在客观对照阶段超时，见[原回执](../artifacts/master_redesign/performance/report-100k.json)。旧源代码的百万基线因拒绝较新合成schema而未进入计时，见[无法测量原因](../artifacts/master_redesign/performance/report-1m-before.json)，不降级schema来制造可比成绩。

[依赖清单复用前的完整剖析](../artifacts/master_redesign/performance/report-delivery-profile.txt)另耗209.853s（含cProfile开销，且在最后依赖清单复用之前，非上述无剖析cold）：4次analyze累计59.7s（约28.5%）、100次客观对照57.2s（27.3%，含公开可变结果隔离的deepcopy）、10次依赖清单21.8s（10.4%）、正文渲染16.9s（8.1%）。这些累计函数存在嵌套，不可直接相加。相对于前轮7次analyze172s、重复事件JSON解码61.6s已有实质减少，剩余cold仍远超预算。最新无剖析阶段（100k/1m）分别为：事实31.80/42.13s，本期核查30.49/33.90s，前期比较11.55/49.16s，客观对照及正文37.84/40.84s，冻结1.50/1.64s。再降低需要对大规模普通训练的指标准备、不可变事件快照和重复证据表示作更深的结构性复用；不能删原始记录、改可比身份或移除私有版本/来源权限核查来凑数。

冻结内容只计算一次JSON＋正文SHA256；新版本追加独立时间/标识，避免每次全量重新编码。UI extra锁定orjson3.13.0用于新报告可控JSON解码；超64位整数、NaN/Infinity、解析异常或未安装可选包使用stdlib回退，旧报告加载始终使用stdlib。ARM64轮子和极值/Unicode/负零/未知元数据已实测。

复跑命令：

```bash
.venv/bin/python tools/master_report_benchmark.py \
  --knowledge-root /tmp/hz-master-report-baseline/knowledge \
  --synthetic /tmp/healthzip-product-benchmark/synthetic-100000.sqlite3 \
  --output artifacts/master_redesign/performance/report-100k.json \
  --warm 30 --max-seconds 900
```

百万规模将路径中的100000换为1000000，输出独立 `report-1m.json`。`--max-seconds` 是单次工程测量超时，不是产品科学参数；超时保留已发生阶段、耗时和未完成身份。cProfile必须另列，不能作为无剖析端到端结果。

## 正确性验收与未验证项

`tests/integration/test_master_report_performance_contract.py`逐项比对共享执行与独立evaluate、W2变体全部77指标、完整报告任务原始ID/hash、热调用独立冻结、源修订立即失效和旧报告不变；连同逐TASK_METRIC等价、快解码边界、回放隔离/修订失效及空库训练共9项通过；最后依赖清单与知识工作流19项通过。报告/缓存/权限回归85项通过、消费者与计划达成43项通过；初始空库持有写锁时仍可只读展示，实际命令后目录可用。证据见[后端验证回执](../artifacts/master_redesign/performance/backend-verification.json)。这些集合有重叠，不相加成独立总数。最终全量pytest/Ruff状态另以本轮最终回归为准。

明确未达标：两档复盘预览冷首批事实、两档完整报告cold及百万规模完整报告hot P95。

尚未验证：真正首次安装/升级迁移；真实iOS/Safari软键盘、安全区和实际网络；私人数据远程模型首内容/完成时间与可配置超时。公共模型调用的证据见知识验收，不把本地无模型性能当远程模型成绩。
