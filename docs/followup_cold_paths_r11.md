# c71358d 后的冷路径续修

基于 GitHub 已发布 `c71358d` 继续，未回退、迁移或重写历史结果。最终候选固定为 [r11 的 549 文件清单](../artifacts/followup_20261127/validation/continuation-source-r11.json)。与 r10 相比，仅改两个产品文件及对应两个测试文件；指标方法、统计与事实身份、工作流哈希、知识用途、报告格式及原始数据均未改变。

## 两项实际改动

- `workflows/report_objects.py`：同一批次普通训练 series 复用存储 scope，仍逐个保存完整独立对象。批后检查路径/inode；失败只回滚本批次，保留调用者此前待保存的写入；成功不提前提交。旧 JSON、对象 ID、组顺序、去重、跨库隔离、旧冻结、NaN 严格/宽松边界及审计离线重建均有回归。原 1 万组的成对阶段中位 **2.398→1.310 秒**，10,002 行对象字节及引用顺序相等。[最终配对及原样本](../artifacts/followup_20261127/performance/freeze-scope-r11-final/README.md)
- `ui/body_pages.py`：只有实际使用 Express 绘图时才导入；心率详情不再额外加载它。原图形数据和构图不变；24 小时睡眠区间图检查自己实际需要的 graph_objects，缺组件时继续展示数值与明细。包含两张实际图序列化与 Streamlit 表格转换的轻诊断中位 **0.878→0.590 秒**；不能将只测 import 的 0.83 秒差值称为整页节省。[导入与图表证据](../artifacts/followup_20261127/performance/lazy-express-import-r1/completion.json)

## 验证与失败保留

[完整回归](../artifacts/followup_20261127/validation/continuation-full-r11/results.json) **2,591/2,591 通过**，186 个文件，失败/错误/跳过为 0，源码前后相同。[产品 Ruff](../artifacts/followup_20261127/validation/continuation-product-ruff-r11.txt)检查 `src tests tools app.py` 通过。专项与全量有重叠，不相加；原不限目录 Ruff 的历史/诊断样式失败继续保留。

[当前已发布版剖析](../artifacts/followup_20261127/performance/continuation-c71358d-profile-r1/README.md)保留插桩全路径与八张原始表哈希。其耗时不能替代未插桩性能验收。减少身份哈希的标量递归曾通过等价检查，但未插桩阶段实测更慢，已经撤回。第一轮存储配对期间事务边界被修正，末尾源码稳定检查失败，也保留原样本；最终单独重测稳定版本，未将失败轮次改写为成功。

## 完整行为和性能范围

完整请求顺序测量三档原始夹具的后端生成、30 次热生成、冷/30 次热重开和审计，以及三档真实心率详情和 100k 浏览器报告生成/下载/重开。每档保留原数据分布、全部 77 指标、原始训练组及未知条件身份。完整审计包留在隔离合成工作区，不上传到 GitHub。

性能原样本、完成身份、图点核对、导出重建、峰值内存和预算结果见 [r11 汇总](../artifacts/followup_20261127/performance/continuation-performance-r11.md)。这是本次受影响路径的复测；冷复盘预览及另外两档浏览器报告没有在本轮重测，继续引用明确标识的 [r10 历史结果](../artifacts/followup_20261127/performance/continuation-performance-r10-v2.md)。不能把未重测的路径算作 r11 达标。

| 原夹具 | 后端完整冷报告 | 运行中冷详情周 / 月 | 热事实＋趋势 P95 |
|---|---:|---:|---:|
| 两年个人 | 10.490 s | 2.291 / 2.502 s | 0.738 s |
| 10 万＋1 万组 | 117.905 s | 2.357 / 2.482 s | 0.822 s |
| 100 万＋1 万组 | 156.869 s | 2.992 / 4.188 s | **1.000100 s，未达标** |

100k 真实报告页面冷生成 112.079 秒、30 次热可交互 P95 1.496 秒；冷重开 1.077 秒、热 P95 0.532 秒。生成、重开均验证新 DOM/报告身份、图点、单一阅读路径、冻结正文下载及六宽度布局。两压力审计导出为 267.89/298.64 MB、13.129/14.340 秒，离线还原和工作流重建另计。

七项完整任务的各工作进程均退出 0；所有源清单、八张原始表及知识权威身份核对通过，汇总有 5 个预算失败、0 个验证失败、0 个缺失回执。外层等待器另被工具报告为退出 143，原因未确定；[异常记录](../artifacts/followup_20261127/validation/continuation-wrapper-exit-r11.json)保留，未宣称该外层包装器正常退出，未重写已完成的子任务样本。

[根代理目视](../artifacts/followup_20261127/validation/continuation-visual-review-r11-root.json)直接检查 7 张报告/详情截图；[子代理目视](../artifacts/followup_20261127/validation/continuation-visual-review-r11-agent.json)检查 8 张手机/桌面主要发现、下一步及重开截图。375/390/430 等窄屏至少一条主要发现完整可见，统计与来源可读；静态截图不代替真实交互，AI 目视不称为人类审阅。

**完整压力冷报告仍未达到 15 秒；局部阶段优化不等于整体达标。** 共享宿主外部负载不可控、OS 缓存保留，单次冷样本不是 P95；普通设备、实体 iPhone/Safari/软键盘、独立专家、人体行动有效性及目标远程模型依旧未验证。既有精确设备/算法、个人 RIR/e1RM 效度等内容缺口不因本轮性能修改而改变。

用户原有 8501 服务未重启，发布到 GitHub 不等于部署到该进程。后续可检验的小范围重复计算线索另列在[只读诊断](../artifacts/followup_20261127/performance/continuation-c71358d-profile-r1/next-readonly-findings.md)，未混入本轮固定源码或宣称收益。
